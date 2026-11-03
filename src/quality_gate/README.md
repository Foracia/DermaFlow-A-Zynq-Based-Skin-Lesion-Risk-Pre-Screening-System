# 图像质量门

本文件夹为皮肤图像采集与风险预筛系统的图像质量门模块，包含 FPGA 统计电路、ARM 侧驱动和参考计算。质量统计用于筛选送入 CNN 的图像。

质量门计算图像质量统计量并参与采集帧筛选。

```text
quality_gate/
├── rtl/
│   ├── axis_quality_gate.sv                # 流式统计核心
│   ├── axis_quality_gate_axi.sv            # AXI 控制包装
│   └── quality_gate_bd.v                   # 整机连接包装
└── python/
    ├── quality_gate_driver.py              # 寄存器配置及统计读取
    ├── reference.py                        # 整数参考
    ├── frame_quality.py                    # 实际图像质量复核
    ├── capture_session.py                  # 采集会话
    ├── stability_capture.py                # 稳定性检查
    ├── calibration_capture.py              # 标定采集
    ├── calibration.py                      # 离线标定
    ├── accelerator_input.py                # 输入适配
    └── preview_hud.py                      # 预览叠加
```

测试台位于 [sim/quality_gate](../../sim/quality_gate/)，集成运行入口见 [板端部署](../../board/README.md)。
