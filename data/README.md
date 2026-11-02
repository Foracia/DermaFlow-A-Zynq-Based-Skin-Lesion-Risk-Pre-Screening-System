# 模型与评估数据

本文件夹为皮肤图像采集与风险预筛系统的模型与评估数据部分，包含已训练 CNN、PL 定点参数、参考样本、数据划分和评估结果。

```text
data/
├── models/                                  # 已训练模型、PL 定点整数参数、预处理及划分
├── golden/                                  # 模型黄金输入与输出参考
├── evaluation/                              # 各 CPU 候选指标及 PC／ARM 计时
├── dataset/                                 # 外部完整数据集目录
│   └── README.md                            # 数据来源、许可、类别映射及处理方式
└── calibration/                             # 外置校准张量占位
```

固定划分为 train 1610、val 342、test 343。正类为 ACK／BCC／MEL／SCC，负类为 NEV／SEK；DF 不在该任务中。完整图片、校准张量和批处理 NPZ 不随本目录提供。

`.npy` 保存单个数组，`.npz` 保存命名数组集合；`.json` 为配置或结果，`.csv` 为表格。评估入口见 [board/batch](../board/batch/README.md)。

数据来源与处理方式见 [数据说明](dataset/README.md)。
