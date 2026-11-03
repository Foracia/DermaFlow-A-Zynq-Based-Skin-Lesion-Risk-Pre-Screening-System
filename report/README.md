# 报告材料

本文件夹为 DermaFlow 皮肤病变智能预筛终端的报告材料部分，包含正式技术报告、独立的系统复现说明和测试结果，以及大模型协作工作流与案例。

```text
report/
├── technical_report.pdf           # 正式项目技术报告，保留原始 PDF
├── reproduction.md                # 完整系统的环境、部署、操作与结果检查
├── measurements.md                # 模型、CPU 基线、PL 加速与整机测试结果
├── images/                        # 从正式报告提取的原始插图和表格
└── collaboration/                 # 大模型协作材料
    ├── workflow.md                # 智能体工作流设计
    ├── task-packet.md             # 任务包模板
    ├── evidence-scope.md          # 来源及验证范围
    └── cases/                     # 四个协作与纠错案例
```

| 阅读目的 | 文件 |
|---|---|
| 阅读完整设计、优化过程及结论 | [正式技术报告](technical_report.pdf) |
| 部署并运行完整系统 | [系统复现说明](reproduction.md) |
| 查看模型、CPU 与 PL 性能、资源时序及整机实测 | [测试与实测结果](measurements.md) |
| 查看大模型协作方法与案例 | [协作工作流](collaboration/workflow.md) |

两份 Markdown 从正式报告中提取整理，启动命令与本仓库统一入口对齐。报告中的 `fpga2026_release` 指工程根目录，在公开仓库中直接对应根目录下的 `board/`、`src/` 等文件夹。

工程原始结果分别见 [实现报告](../build/reports/README.md)、[CPU 评估](../data/evaluation/README.md) 和 [板端实测](../board/results/README.md)。
