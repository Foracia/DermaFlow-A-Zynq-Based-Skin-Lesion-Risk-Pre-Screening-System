# 设计源码

本文件夹为皮肤图像采集与风险预筛系统的设计源码部分，包含 CNN、质量门、视频处理、整机连接及系统软件。

```text
src/
├── cnn/                                     # CNN 算法、权重、RTL 与模型导出辅助
├── system/                                  # 整机连接与约束
├── quality_gate/                            # 图像质量统计电路及 PS 驱动
├── video/                                   # 视频叠加与本地 IP
└── system_ui/                               # 采集、推理、界面和结果保存
```

仿真入口见 [sim](../sim/README.md)，工程构建见 [build](../build/README.md)，部署文件见 [board](../board/README.md)。
