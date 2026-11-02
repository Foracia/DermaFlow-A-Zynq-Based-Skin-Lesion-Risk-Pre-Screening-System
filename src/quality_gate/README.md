# 图像质量门

本文件夹为皮肤图像采集与风险预筛系统的图像质量门模块，包含 FPGA 统计电路、ARM 侧驱动和参考计算。质量统计用于筛选送入 CNN 的图像。

质量门计算图像质量统计量并参与采集帧筛选。

```text
quality_gate/
├── rtl/axis_quality_gate.sv                 # 流式统计核心
├── rtl/axis_quality_gate_axi.sv             # AXI 控制包装
├── rtl/quality_gate_bd.v                    # 整机连接包装
├── python/quality_gate_driver.py            # 寄存器配置及统计读取
├── python/reference.py                      # 整数参考及保留图像的质量复核
├── frame_quality.py                         # 整数参考及保留图像的质量复核
├── python/capture_session.py                # 采集、稳定性及标定采集辅助
├── stability_capture.py                     # 采集、稳定性及标定采集辅助
├── calibration_capture.py                   # 采集、稳定性及标定采集辅助
├── python/calibration.py                    # 离线标定候选计算
├── python/accelerator_input.py              # 输入适配及预览
└── preview_hud.py                           # 输入适配及预览
```

测试台位于 [sim/quality_gate](../../sim/quality_gate/)，集成运行入口见 [板端部署](../../board/README.md)。
