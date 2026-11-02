# -*- coding: utf-8 -*-
"""
皮肤病变风险预筛 - 学生模型 v1 (FP32)

设计目标：不是"精度最高的模型"，而是"能被 XC7Z020 + hls4ml 吃下去的模型"。
硬约束（来自技术选型报告 5.4 节，先于训练定死）：
    输入 128x128 / INT8 / 参数量 <= 0.5M / 纯顺序结构 Conv-ReLU-Pool / 无残差

算子白名单（全部在 hls4ml 支持范围内）：
    Conv2d(3x3, stride1, pad1)  -> 规则乘加，DSP 阵列
    BatchNorm2d                 -> 导出时折叠进前面的 Conv，推理期零成本
    ReLU                        -> 量化后等价于"截断负数"，零成本
    MaxPool2d(2x2, stride2)     -> 只比大小，无量化误差
    AdaptiveAvgPool2d(1)        -> 全局平均，替代 Flatten（关键！见下）
    Linear(64 -> 2)             -> 分类头

刻意排除：depthwise/分组卷积、SE/attention、残差 add、多分支 concat、
          F.interpolate、动态 shape、Dropout（推理期语义易在工具链出错）。

为什么必须用 GAP 而不是 Flatten：
    最后一段特征图是 16x16x64 = 16384 维。Flatten 后接一个隐藏层 FC(128)
    就是 16384*128 = 2.1M 参数，直接爆掉 0.5M 预算的 4 倍，
    而且 INT8 下 2.1MB 权重装不进约 600KB 的 BRAM，必须走 DDR 调度——
    报告里明确要避免这个坑。GAP 把它压成 64 维，问题消失。
"""

import torch
import torch.nn as nn

N_CLASSES = 2        # 0 = 阴性(benign), 1 = 建议就医(malignant)
IN_CHANNELS = 3      # RGB
INPUT_SIZE = 128


class ConvBlock(nn.Module):
    """n_conv 个 (Conv3x3 -> BN -> ReLU)，末尾可选接一个 MaxPool 降采样。

    BN 放在 Conv 和 ReLU 之间：导出时 Conv+BN 会折叠成一个带偏移的卷积，
    推理期 BN 完全消失，不占任何硬件资源。

    结构严格保持"纯顺序、无残差、无分支"，这是 hls4ml 能吃下去的前提。
    """

    def __init__(self, in_ch, out_ch, pool=True, n_conv=1, first_in=None):
        super().__init__()
        layers = []
        c_in = in_ch
        for i in range(n_conv):
            # 第 0 层负责升通道（in_ch -> out_ch），之后各层保持 out_ch
            c_out = out_ch
            layers += [
                nn.Conv2d(c_in, c_out, kernel_size=3, stride=1, padding=1,
                          bias=False),
                nn.BatchNorm2d(c_out),
                nn.ReLU(inplace=True),
            ]
            c_in = c_out
        if pool:
            layers.append(nn.MaxPool2d(kernel_size=2, stride=2))
        self.body = nn.Sequential(*layers)

    def forward(self, x):
        return self.body(x)


class DermCNN(nn.Module):
    """学生模型。

    两个可调旋钮（用于消融实验）：
      width          通道宽度倍数，1.0 -> 16/32/64；2.0 -> 32/64/128
      convs_per_stage 每个 stage 的 Conv3x3 层数，1 或 2

    关于"加深"的性价比（重要）：
        在 stage2/stage3 加卷积几乎不增加计算量（那里空间尺寸已经很小），
        只增加参数量。而我们的参数预算只用了 4.8%、BRAM 只用了 8.4%，
        所以加深是当前最划算的一步。
        但在 stage1 加卷积代价极大（128x128 全分辨率），要谨慎。
    """

    def __init__(self, n_classes=N_CLASSES, in_ch=IN_CHANNELS, width=1.0,
                 convs_per_stage=1, gap_mode="avgpool"):
        super().__init__()
        c1 = max(8, round(16 * width))
        c2 = max(8, round(32 * width))
        c3 = max(8, round(64 * width))
        self.width = width
        self.convs_per_stage = convs_per_stage
        self.gap_mode = gap_mode

        # 128x128 -> 64x64
        self.stage1 = ConvBlock(in_ch, c1, pool=True, n_conv=convs_per_stage,
                                first_in=in_ch)
        # 64x64 -> 32x32
        self.stage2 = ConvBlock(c1, c2, pool=True, n_conv=convs_per_stage,
                                first_in=c1)
        # 32x32 -> 16x16
        self.stage3_conv = ConvBlock(c2, c3, pool=False, n_conv=convs_per_stage,
                                     first_in=c2)
        self.pool3 = nn.MaxPool2d(kernel_size=2, stride=2)

        # 16x16xc3 -> 1x1xc3
        #
        # 为什么默认用 AvgPool2d(16,16) 而不是 AdaptiveAvgPool2d(1)：
        #   AdaptiveAvgPool2d 在 PyTorch 2.11 里会被导出成 ReduceMean，
        #   而该实现用了 opset 18 的语义（axes 由属性改为输入）。
        #   这导致导出到 opset <= 17 时 ONNX 版本转换失败：
        #       adapt: Assertion `node->hasAttribute(kaxes)` failed
        #   换成 AvgPool2d 后导出为 AveragePool 算子，opset 17 可正常产出。
        #
        #   此替换在数学上是**完全等价**的：pool3 之后空间尺寸恒为 16x16，
        #   所以 AvgPool2d(kernel_size=16, stride=16) 的输出就是全局平均。
        #   两者都没有可训练参数，state_dict 因此完全兼容，无需重训。
        if gap_mode == "avgpool":
            self.gap = nn.AvgPool2d(kernel_size=16, stride=16)
        else:
            self.gap = nn.AdaptiveAvgPool2d(1)

        self.classifier = nn.Linear(c3, n_classes)

        self._init_weights()

    def _init_weights(self):
        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                nn.init.kaiming_normal_(m.weight, mode="fan_out", nonlinearity="relu")
            elif isinstance(m, nn.BatchNorm2d):
                nn.init.ones_(m.weight)
                nn.init.zeros_(m.bias)
            elif isinstance(m, nn.Linear):
                nn.init.normal_(m.weight, std=0.01)
                nn.init.zeros_(m.bias)

    def forward(self, x):
        x = self.stage1(x)
        x = self.stage2(x)
        x = self.stage3_conv(x)
        x = self.pool3(x)
        x = self.gap(x)
        x = torch.flatten(x, 1)          # (N, c3)
        return self.classifier(x)        # (N, n_classes) logits


# ----------------------------------------------------------------------------
# 自检工具：每次改完结构都要跑一次，三个数必须都在预算内
# ----------------------------------------------------------------------------

OPERATOR_WHITELIST = {
    "Conv2d": "规则 3x3 卷积，hls4ml 一等公民",
    "BatchNorm2d": "导出时折叠进 Conv，推理期零成本",
    "ReLU": "量化后为截断操作，零成本",
    "MaxPool2d": "只比大小，无量化误差",
    "AvgPool2d": "固定窗口平均池化（替代 AdaptiveAvgPool2d，见下方说明）",
    "AdaptiveAvgPool2d": "自适应平均池化 —— 仅在 gap_mode='adaptive' 时使用，"
                         "会导出成 ReduceMean 并导致 opset<=17 导出失败，"
                         "正式导出请用 gap_mode='avgpool'",
    "Linear": "分类头，输入维度必须小",
}

# hls4ml 明确不支持 / 强烈不建议的算子，出现即告警
FORBIDDEN_OPERATORS = (
    "GroupNorm", "LayerNorm", "InstanceNorm",
    "Dropout", "MultiheadAttention", "Transformer",
    "ConvTranspose2d", "Upsample", "PixelShuffle",
    "LSTM", "GRU", "Embedding",
)


def count_parameters(model):
    """分组统计参数量。分类头如果吃掉总参数的 30% 以上，说明结构有问题。"""
    groups = {"conv": 0, "bn": 0, "fc": 0}
    for name, p in model.named_parameters():
        if not p.requires_grad:
            continue
        if ".body." in name and "weight" in name and p.dim() == 4:
            groups["conv"] += p.numel()
        elif "classifier" in name:
            groups["fc"] += p.numel()
        else:
            groups["bn"] += p.numel()   # BN 的 weight/bias 与 conv 的 bias
    groups["total"] = sum(groups.values())
    return groups


# XC7Z020 的硬资源上限（写死在这，体检时对照）
BRAM_TOTAL_KB = 600.0       # 约 4.9 Mb = 600 KB，实际可用受 IP 与实现影响会更少
DSP48_TOTAL = 220

# 硬件位宽假设（跑 W1 实测后可回来改这两个数）
W_BITS = 8      # 权重定点位宽
A_BITS = 8      # 激活定点位宽


def _line_buffer_kb(in_shape, module):
    """估算 2D 卷积/池化的行缓冲需求。

    硬件做 2D 卷积不需要缓存整张特征图，只要"当前行 + 上面 (k-1) 行"就能开始算。
    所以 BRAM 压力 = 行宽(像素) x 通道数 x 字节数 x 需要同时驻留的行数。

    这是工程估算，不是综合报告；准确数字以 Vitis HLS 报告为准。
    它的价值在于：改完结构立刻知道 BRAM 压力往哪个方向变了。
    """
    if len(in_shape) != 4:
        return 0.0
    _, c_in, h, w = in_shape
    if isinstance(module, nn.Conv2d):
        rows = module.kernel_size[0]
    elif isinstance(module, nn.MaxPool2d):
        rows = module.kernel_size if isinstance(module.kernel_size, int) else module.kernel_size[0]
    else:
        return 0.0
    bytes_per_elem = A_BITS / 8.0
    return c_in * w * rows * bytes_per_elem / 1024.0


def audit_model(model, input_size=INPUT_SIZE, verbose=True, device=None):
    """资源体检：参数量 / 行缓冲 / 权重体积 / 算子白名单，四项一起看。

    关于"逻辑中间张量"：它**不是** BRAM 占用。硬件只需要行缓冲就能流式算完
    一个卷积层，不需要把整张特征图存下来。所以那一栏只作参考，
    真正决定 BRAM 是否溢出的是下面算的行缓冲估算 + 权重的片上驻留形式。

    但也别完全无视中间张量：如果它大得离谱（比如超过几十 MB），
    说明某一层的空间尺寸或通道数失控了，那时候行缓冲也会跟着爆。
    """
    # 统一在 CPU 上做体检：不占显存，也不会因为设备不一致炸掉。
    # （训练脚本会在体检之后把模型搬到 GPU，见 train_derm.py）
    if device is not None:
        model.to(device)
    was_training = model.training
    model.eval()

    hooks, records, conv_metrics = [], [], []

    def make_hook(name, module):
        def hook(mod, inp, out):
            if not torch.is_tensor(out):
                return
            in_shape = tuple(inp[0].shape) if inp and torch.is_tensor(inp[0]) else ()
            lb = _line_buffer_kb(in_shape, module)
            if lb > 0:
                conv_metrics.append((name, type(module).__name__, in_shape,
                                     tuple(out.shape), lb))
            records.append((name, type(module).__name__, tuple(out.shape),
                            out.numel(), out.element_size(),
                            in_shape))
        return hook

    for name, module in model.named_modules():
        if isinstance(module, (nn.Conv2d, nn.ReLU, nn.MaxPool2d,
                               nn.AdaptiveAvgPool2d, nn.Linear, nn.BatchNorm2d)):
            hooks.append(module.register_forward_hook(make_hook(name, module)))

    with torch.no_grad():
        dummy = torch.zeros(1, IN_CHANNELS, input_size, input_size,
                            device=next(model.parameters()).device)
        out = model(dummy)

    for h in hooks:
        h.remove()
    if was_training:
        model.train()

    params = count_parameters(model)

    # 不可训练的参数（比如 BN）也要算进总量，但标为可折叠
    total_all = sum(p.numel() for p in model.parameters())

    def _weight_bytes(name, p):
        """INT8 量化下每个参数的字节数，按位宽假设估算。"""
        if p.dim() == 4:
            bpe = (W_BITS + 8) / 8.0          # 权重 INT8 + 每通道 scale
        elif p.dim() == 1:
            bpe = A_BITS / 8.0                # BN 折算后的偏置 / conv bias
        else:
            bpe = (W_BITS + 8) / 8.0
        return p.numel() * bpe

    weight_bytes = sum(_weight_bytes(n, p) for n, p in model.named_parameters())
    weights_kb = weight_bytes / 1024.0
    # 权重占 BRAM 的比例。超过 50% 提示（要留意层间工作集的余量），
    # 超过 70% 才算硬拒绝 —— "权重偏大"不等于"不能用"，
    # 报告里本来就预留了"权重驻留 DDR3 + DMA 搬层工作集"的备选方案，
    # 所以这里只把风险显式化，让决策留给设计者而不是脚本静默否决。
    weights_ratio = weights_kb / BRAM_TOTAL_KB

    real_tensors = [(n, o, s, numel, es, ins) for (n, o, s, numel, es, ins) in records
                    if o != "BatchNorm2d"]
    seen_shapes = {}
    peak = 0
    peak_name = "-"
    for n, o, s, numel, es, ins in real_tensors:
        if numel > peak:
            peak, peak_name = numel, n
        seen_shapes.setdefault(s, 0)
        seen_shapes[s] += 1
    peak_kb_tensor = peak * 4 / 1024.0
    peak_kb_int8 = peak * (A_BITS / 8.0) / 1024.0

    lb_peak = max((m[4] for m in conv_metrics), default=0.0)
    lb_peak_name = max(conv_metrics, key=lambda m: m[4])[0] if conv_metrics else "-"
    bram_estimate = lb_peak + weights_kb

    used_ops = sorted({r[1] for r in real_tensors})
    if any(r[1] == "BatchNorm2d" for r in records):
        used_ops.append("BatchNorm2d")

    ok = True
    msgs = []

    # 检查 1：参数量（对报告里的 0.5M 硬上限）
    if total_all > 500_000:
        ok = False
        msgs.append(f"总参数量 {total_all:,} 超过硬上限 500,000")
    elif total_all > 350_000:
        msgs.append(f"总参数量 {total_all:,} 偏大，位宽扫描余量不足")

    # 检查 2：分类头占比（Flatten 误用的典型症状）
    if total_all and params["fc"] / total_all > 0.30:
        msgs.append(f"分类头占了 {params['fc'] / total_all:.0%} 的参数，"
                    f"检查是否误用 Flatten")

    # 检查 3：权重能否常驻片上
    if weights_ratio > 0.70:
        ok = False
        msgs.append(f"权重约 {weights_kb:.0f} KB（占 BRAM {weights_ratio:.0%}），"
                    f"已无法与层间工作集共存，必须走 DDR 调度。"
                    f"报告里对应的备选方案：权重驻留 DDR3 + DMA 搬层工作集")
    elif weights_ratio > 0.50:
        msgs.append(f"权重约 {weights_kb:.0f} KB（占 BRAM {weights_ratio:.0%}）偏大，"
                    f"层间工作集余量紧张。若 W3 综合报 BRAM 溢出，"
                    f"优先降通道数或走 DDR 权重方案")

    # 检查 4：行缓冲（这才是真正的 BRAM 压力）
    # 阈值说明：真正危险的是"行缓冲就吃掉大半 BRAM"，那时候才必须降通道数。
    # 几百 KB 以下都只是"做 Reuse Factor 扫描时留意一下"，不影响综合。
    if lb_peak > BRAM_TOTAL_KB * 0.5:
        ok = False
        msgs.append(f"单层行缓冲约 {lb_peak:.0f} KB，超过 BRAM 的一半，"
                    f"需要降低该层通道数或提高 Reuse Factor")
    elif lb_peak > BRAM_TOTAL_KB * 0.15:
        msgs.append(f"单层行缓冲约 {lb_peak:.0f} KB 偏大，"
                    f"后续做 Reuse Factor 扫描时重点关注这一层")

    # 检查 5：分类头输入维度
    fc_in = next((m.in_features for m in model.modules() if isinstance(m, nn.Linear)), 0)
    if fc_in > 512:
        msgs.append(f"分类头输入 {fc_in} 维偏大，确认是 GAP 而不是 Flatten 送进来的")

    # 检查 6：算子白名单
    for name, module in model.named_modules():
        if type(module).__name__ in FORBIDDEN_OPERATORS:
            ok = False
            msgs.append(f"出现禁用算子 {type(module).__name__}（{name}）")
    for op in used_ops:
        if op not in OPERATOR_WHITELIST and op != "Sequential":
            msgs.append(f"算子 {op} 不在白名单中，需在 W1 单独验证可综合性")

    if verbose:
        print("=" * 68)
        print("模型资源体检")
        print("=" * 68)
        print(f"{'卷积层参数':<16}{params['conv']:>12,}")
        print(f"{'BN 参数':<16}{params['bn']:>12,}   (导出时折叠，推理期消失)")
        print(f"{'分类头参数':<16}{params['fc']:>12,}")
        print(f"{'总参数量':<16}{total_all:>12,}   "
              f"上限 500,000 ({total_all / 500_000:.1%})")
        print(f"{'INT8 权重体积':<16}{weights_kb:>12.1f} KB   "
              f"BRAM {BRAM_TOTAL_KB:.0f} KB 的 {weights_kb / BRAM_TOTAL_KB:.1%}")
        print("-" * 68)
        print("BRAM 压力（这才是决定装不装得下的数字）")
        print(f"  {'行缓冲峰值':<14}{lb_peak:>10.1f} KB   @ {lb_peak_name}")
        print(f"  {'权重驻留':<14}{weights_kb:>10.1f} KB")
        print(f"  {'合计估算':<14}{bram_estimate:>10.1f} KB   "
              f"占 BRAM {bram_estimate / BRAM_TOTAL_KB:.1%}  (A_BITS={A_BITS})")
        print(f"  （行缓冲 = 行宽 x 通道 x {A_BITS // 8} 字节 x 核行数，工程估算，"
              f"准确值以 Vitis HLS 报告为准）")
        print("-" * 68)
        print(f"逻辑中间张量峰值 {peak_kb_tensor:>10.1f} KB   @ {peak_name}  "
              f"(float32)")
        print(f"                  {peak_kb_int8:>10.1f} KB   (INT8, 仅供参考，"
              f"硬件只存行缓冲不存整图)")
        print("-" * 68)
        print(f"输出 logits      {tuple(out.shape)}")
        print("-" * 68)
        print("逐层激活：")
        seen = set()
        for name, op, shape, numel, es, ins in records:
            if id(shape) in seen or (name, shape) in seen:
                continue
            seen.add((name, shape))
            print(f"  {name:<22}{op:<20}{str(shape):<20}"
                  f"{numel * es / 1024:>8.1f} KB")
        print("-" * 68)
        print(f"用到的算子：{', '.join(used_ops)}")
        print("=" * 68)
        if msgs:
            print("提示：")
            for m in msgs:
                print(f"  - {m}")
            print("=" * 68)
        print("体检结论：" + ("通过" if ok else "不通过，必须改结构"))
        print("=" * 68)

    return {"params": params, "total_params": total_all,
            "weights_kb": weights_kb, "line_buffer_peak_kb": lb_peak,
            "bram_estimate_kb": bram_estimate, "ok": ok, "messages": msgs}


def describe_model(model):
    """逐参数打印名称/形状/数量。用来核对"我以为的结构"和"实际的结构"是否一致。"""
    print("=" * 68)
    print("逐参数清单")
    print("=" * 68)
    total = 0
    for name, p in model.named_parameters():
        total += p.numel()
        print(f"  {name:<44}{str(tuple(p.shape)):<20}{p.numel():>9,}")
    print("-" * 68)
    print(f"  {'合计':<44}{'':<20}{total:>9,}")
    print("=" * 68)
    return total


def build_model(width=1.0, n_classes=N_CLASSES, convs_per_stage=1,
                gap_mode="avgpool"):
    return DermCNN(n_classes=n_classes, width=width,
                   convs_per_stage=convs_per_stage, gap_mode=gap_mode)


if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    for w in (1.0, 2.0, 3.0):
        for cps in (1, 2):
            print(f"\n>>> width = {w}   convs_per_stage = {cps}")
            audit_model(build_model(width=w, convs_per_stage=cps))
