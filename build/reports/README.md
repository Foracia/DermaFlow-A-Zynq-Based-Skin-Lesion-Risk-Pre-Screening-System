# 综合与实现报告

本文件夹为皮肤图像采集与风险预筛系统当前硬件实现的构建报告部分。

```text
reports/
├── system/                       # 视频、质量门、CNN 和 DMA 整机报告
│   ├── system_postroute_utilization.rpt # 布局布线后资源
│   ├── system_timing.rpt          # 建立／保持时序与约束覆盖
│   ├── system_route_status.rpt    # 布线完成情况
│   ├── system_drc.rpt            # 设计规则检查
│   ├── system_cdc.rpt            # 跨时钟检查
│   └── routed_cnn_banked_cells.rpt # 整机内 CNN ROM 的实际映射
├── cnn/                          # 当前 CNN 核的独立实现报告
└── pending/                      # 报告扩展目录
```

整机资源为 10613 Slice、22181 LUT、33855 FF、71.5 BRAM Tile、70 DSP；setup slack 为 +0.099 ns，hold slack 为 +0.014 ns。报告保留原视频时钟、CDC 和外部 IO 约束相关警告，具体范围见原始报告。

报告对应当前硬件实现，构建入口位于 `build/scripts/`。
