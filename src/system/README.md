# 整机连接与约束

本文件夹为皮肤图像采集与风险预筛系统的整机硬件集成部分，定义 Zynq PS 与视频、质量门、CNN、DMA、时钟及复位的连接。

```text
system/
├── system_bd.tcl                            # PS、视频、质量门、CNN、DMA、时钟及复位的 Block Design
└── constraints.xdc                          # 整机实现约束
```

由 [create_project.tcl](../../build/scripts/create_project.tcl) 登记源码和本地 IP 后加载。工程创建、综合及实现步骤见 [构建说明](../../build/README.md)。
