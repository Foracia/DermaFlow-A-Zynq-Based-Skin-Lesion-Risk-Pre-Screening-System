# -*- coding: utf-8 -*-
"""
预训练骨干 + 硬件友好头部的混合模型。

## 为什么需要这个

当前模型是从零训练的，只有 1,206 张图 —— 这是精度上不去的根本原因之一。

但**不能直接拿 ImageNet 预训练模型来微调**，因为：
    MobileNetV2   : depthwise 卷积，hls4ml 不支持
    EfficientNet-B0: depthwise + SE 模块，不支持
    ResNet18      : 残差连接，首版明确不做

## 折中方案：只借"眼睛"，不借"大脑"

ImageNet 模型的**前几层**学的是通用视觉特征（边缘、纹理、色块方向），
这些对皮肤病变同样有用。后面的层是 ImageNet 专属语义（猫耳朵、狗鼻子），
那部分我们用自己的硬件友好结构。

于是：
    [ImageNet 预训练的前几个 block，冻结]  <- 借来的"眼睛"
                    ↓
    [我们自己的 Conv-BN-ReLU + MaxPool]    <- 硬件友好的"大脑"
                    ↓
    GAP -> FC(2)

## 对 hls4ml / INT8 的影响

- 借来的部分也是**规则卷积**（只要避开 depthwise），所以仍然可综合
- 冻结层不参与训练，但**仍然要进 ONNX、要量化**
- 本文件提供 --backbone 选项，可以对比"有/无预训练"的差距

用法：
    python train_pretrained.py --backbone resnet18 --freeze-blocks 2
    python train_pretrained.py --backbone none           # 对照组：从零训练
"""

import argparse
import sys
from pathlib import Path

import torch
import torch.nn as nn

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

INPUT_SIZE = 128
N_CLASSES = 2


# ---------------------------------------------------------------------------
# 骨干网络：只取前几个 block，输出特征图（不是分类结果）
# ---------------------------------------------------------------------------

class ResNet18Stem(nn.Module):
    """ResNet18 的前 N 个 block。

    ResNet18 的 layer1/layer2 是**普通 3x3 卷积**（没有 bottleneck），
    只有每个 block 内部的残差 shortcut。我们只取 stem + 前 1~2 个 block，
    把特征图拿出来，后续走自己的路。

    注意：ResNet18 的每个 BasicBlock 内部**有残差连接**。
    这对 hls4ml 是个风险点，所以提供 --no-residual 选项：
    只取 stem（conv1 + bn + relu + maxpool），那是纯顺序结构。
    """

    def __init__(self, n_blocks=1, pretrained=True):
        super().__init__()
        from torchvision import models
        w = models.ResNet18_Weights.IMAGENET1K_V1 if pretrained else None
        r = models.resnet18(weights=w)

        # stem: conv1(7x7,s2) + bn + relu + maxpool -> 128/4 = 32
        self.stem = nn.Sequential(
            r.conv1, r.bn1, r.relu, r.maxpool,
        )
        # 后续 block（有残差，谨慎使用）
        blocks = [r.layer1, r.layer2, r.layer3, r.layer4]
        self.blocks = nn.ModuleList(blocks[:n_blocks])
        self.out_channels = [64, 64, 128, 256, 512][n_blocks]
        # 空间尺寸：stem 后 /4，每过一个 block /2（layer1 不降采样）
        self.out_stride = 4 if n_blocks == 0 else 4 * (2 ** max(0, n_blocks - 1))

    def forward(self, x):
        x = self.stem(x)
        for b in self.blocks:
            x = b(x)
        return x


class MobileNetStem(nn.Module):
    """MobileNetV3 的前几层。⚠ 含 depthwise 卷积，hls4ml 风险高。

    仅作为"精度上限参考"——如果它的精度比 ResNet stem 高很多，
    说明我们在算子约束上付出的代价有多大，这个对比本身可以写进报告。
    """

    def __init__(self, n_blocks=2, pretrained=True):
        super().__init__()
        from torchvision import models
        w = models.MobileNet_V3_Small_Weights.IMAGENET1K_V1 if pretrained else None
        m = models.mobilenet_v3_small(weights=w)
        feats = list(m.features.children())
        self.stem = nn.Sequential(*feats[:n_blocks])
        self.out_channels = 16
        self.out_stride = 4

    def forward(self, x):
        return self.stem(x)


def build_backbone(name, n_blocks=1, pretrained=True):
    if name == "none":
        return None, 3, 1
    if name == "resnet18":
        b = ResNet18Stem(n_blocks=n_blocks, pretrained=pretrained)
        return b, b.out_channels, b.out_stride
    if name == "mobilenetv3":
        b = MobileNetStem(n_blocks=n_blocks, pretrained=pretrained)
        return b, b.out_channels, b.out_stride
    raise ValueError(f"未知骨干: {name}")


# ---------------------------------------------------------------------------
# 混合模型
# ---------------------------------------------------------------------------

class HybridDermCNN(nn.Module):
    """预训练骨干 + 硬件友好的顺序头部。

    头部严格保持：Conv3x3 -> BN -> ReLU -> MaxPool 的纯顺序结构，
    无残差、无 depthwise、无分支 —— 这是 hls4ml 能吃下去的前提。
    """

    def __init__(self, backbone_name="none", n_blocks=1, pretrained=True,
                 n_classes=N_CLASSES, width=1.0, head_ch=(32, 64, 128),
                 freeze_backbone=True):
        super().__init__()
        self.backbone_name = backbone_name
        self.backbone, c_in, stride = build_backbone(
            backbone_name, n_blocks, pretrained)

        if self.backbone is not None and freeze_backbone:
            for p in self.backbone.parameters():
                p.requires_grad = False

        # 当前空间尺寸（用于最后确认 GAP 窗口）
        h = INPUT_SIZE // stride
        self.feat_size = h

        from model_derm import ConvBlock
        c1 = max(8, round(head_ch[0] * width))
        c2 = max(8, round(head_ch[1] * width))
        c3 = max(8, round(head_ch[2] * width))

        self.head1 = ConvBlock(c_in, c1, pool=True, n_conv=1, first_in=c_in)
        self.head2 = ConvBlock(c1, c2, pool=True, n_conv=1, first_in=c1)
        self.head3 = ConvBlock(c2, c3, pool=False, n_conv=1, first_in=c2)

        # 头部走完后的空间尺寸
        hs = h // 4
        self.head_size = hs
        if hs < 1:
            raise ValueError(f"空间尺寸被压缩到 {hs}，骨干 stride 太大")
        self.gap = nn.AvgPool2d(kernel_size=hs, stride=hs)
        self.classifier = nn.Linear(c3, n_classes)

        self._init_head()

    def _init_head(self):
        for m in list(self.head1.modules()) + list(self.head2.modules()) \
                + list(self.head3.modules()) + [self.classifier]:
            if isinstance(m, nn.Conv2d):
                nn.init.kaiming_normal_(m.weight, mode="fan_out",
                                        nonlinearity="relu")
            elif isinstance(m, nn.BatchNorm2d):
                nn.init.ones_(m.weight)
                nn.init.zeros_(m.bias)
            elif isinstance(m, nn.Linear):
                nn.init.normal_(m.weight, std=0.01)
                nn.init.zeros_(m.bias)

    def trainable_parameters(self):
        return [p for p in self.parameters() if p.requires_grad]

    def forward(self, x):
        if self.backbone is not None:
            x = self.backbone(x)
        x = self.head1(x)
        x = self.head2(x)
        x = self.head3(x)
        x = self.gap(x)
        x = torch.flatten(x, 1)
        return self.classifier(x)


def build_hybrid(backbone="none", n_blocks=1, pretrained=True, width=1.0,
                 head_ch=(32, 64, 128), freeze_backbone=True):
    return HybridDermCNN(backbone_name=backbone, n_blocks=n_blocks,
                         pretrained=pretrained, width=width, head_ch=head_ch,
                         freeze_backbone=freeze_backbone)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 76)
    print("混合模型配置对比（预训练骨干 + 硬件友好头部）")
    print("=" * 76)
    print(f"{'骨干':<16}{'blocks':>7}{'特征尺寸':>10}{'总参数':>12}"
          f"{'可训练':>12}{'头部参数':>12}")
    print("-" * 76)

    for name, nb in (("none", 0), ("resnet18", 0), ("resnet18", 1),
                     ("resnet18", 2), ("mobilenetv3", 2), ("mobilenetv3", 4)):
        try:
            m = build_hybrid(backbone=name, n_blocks=nb)
            total = sum(p.numel() for p in m.parameters())
            train = sum(p.numel() for p in m.trainable_parameters())
            head = sum(p.numel() for n, p in m.named_parameters()
                       if not n.startswith("backbone."))
            print(f"{name:<16}{nb:>7}{m.feat_size:>10}{total:>12,}"
                  f"{train:>12,}{head:>12,}")
        except Exception as e:
            print(f"{name:<16}{nb:>7}  失败: {type(e).__name__}: {str(e)[:40]}")

    print("-" * 76)
    print("说明：")
    print("  - backbone=none 是从零训练的对照组")
    print("  - resnet18/0 = 只用 stem（conv1+bn+relu+maxpool），**纯顺序无残差，最安全**")
    print("  - resnet18/1+ 会引入残差块，hls4ml 有风险，但精度可能更好")
    print("  - mobilenetv3 含 depthwise，**仅供参考，不建议上板**")
