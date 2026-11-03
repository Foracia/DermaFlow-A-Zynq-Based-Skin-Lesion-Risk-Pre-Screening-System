# 板端实测结果

本文件夹为皮肤图像采集与风险预筛系统的板端实测结果部分，保存启动验证、CNN 评估、计时及完整系统采集运行的原始记录。

```text
board/results/
├── golden/                        # 分阶段启动与黄金事务
│   ├── board_result_*.json        # 四帧输出及清理状态
│   └── stage_*.jsonl              # metadata／load／control 事件
├── batch/                         # test 343 张评估及计时
│   ├── summary.json               # 运行状态及汇总
│   ├── test_pl_result.json        # 指标、参考差异与分阶段计时
│   ├── test_pl_predictions.csv    # 逐样本预测
│   ├── test_pl_logits.npy         # 逐样本 logits
│   └── session.json               # CNN 会话记录
├── timing/                        # 独立计时原件及汇总
└── system_ui/                     # 实际采图与运行记录
    ├── index.csv                  # 采集索引
    ├── export_report.json         # 导出核对记录
    ├── capture_*/                 # 每次采集的图像与结果
    └── sessions/                  # 系统运行会话
```

结果保留原测试条件、状态及计时范围。黄金目录的 `manifest.json` 列出该目录实际提供文件及其 SHA；执行结果见对应运行回执，JSONL 保存逐阶段事件。

正式报告中的模型指标、统一计时、整机操作图片和连续运行结果见[测试与实测结果](../../report/measurements.md)。本目录保留工程测试原件，报告摘录保留各项数据的测试范围。
