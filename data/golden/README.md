# 模型黄金参考

本文件夹为皮肤图像采集与风险预筛系统的模型参考测试数据部分，保存少量固定输入和预期输出，用于核对模型导出及数值计算。

```text
golden/
└── model/
    ├── input.npy                           # 六张预处理后的 NCHW float32 输入
    ├── pytorch_out.npy                     # PyTorch logits
    ├── onnx_out.npy                        # ONNX logits
    ├── prob.npy                            # 概率参考
    └── meta.json                           # 样本与预处理说明
```

各 ncnn 候选参考另存于 [board/cpu/references](../../board/cpu/references/)，PL 原码参考位于 [expected.hex](../../board/hardware/expected.hex)。黄金样本用于功能核对，完整评估结果见 [evaluation](../evaluation/README.md)。
