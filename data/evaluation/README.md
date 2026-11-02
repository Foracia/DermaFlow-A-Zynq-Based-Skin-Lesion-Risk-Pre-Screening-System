# CPU 评估结果

本文件夹为皮肤图像采集与风险预筛系统的 CPU 模型评估部分，保存各量化候选的分类指标与 PC／ARM 计时记录。

```text
evaluation/
├── cpu/fp32/                                # 固定划分的 metrics.json 与 logits.npz
├── cpu/kl/                                  # 固定划分的 metrics.json 与 logits.npz
├── cpu/eq/                                  # 固定划分的 metrics.json 与 logits.npz
├── cpu/aciq/                                # 固定划分的 metrics.json 与 logits.npz
├── cpu/pc/                                  # FP32／KL／EQ 的 PC 计时及环境记录
└── cpu/arm/                                 # FP32／KL／EQ 的 ARM 计时及阶段记录
```

`metrics.json` 中 `val` 与 `test_development` 分别表示验证集和开发测试集。原评估器的 `candidate` 文本沿用通用 EQ 标签，候选对应关系以目录、工作点及模型身份为准。

CPU 计时保留 prepared-Mat API 等阶段定义；PL 分阶段结果见 [board/results](../../board/results/README.md)。运行入口见 [CPU 说明](../../board/cpu/README.md)。
