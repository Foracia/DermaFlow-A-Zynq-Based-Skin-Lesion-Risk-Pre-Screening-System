# CNN 测试文件

本文件夹为皮肤图像采集与风险预筛系统的 CNN 仿真部分，包含 HLS C 和 RTL 测试数据，用于检查模型数值及硬件接口行为。

```text
cnn/
├── real_core_tb.sv                          # 实际 CNN RTL 及 AXI 包装的测试台
├── input.hex                                # 四帧输入与 raw 输出参考
├── expected.hex                             # 四帧输入与 raw 输出参考
├── simulate.log                             # 原研发仿真日志
├── hls/test.cpp                             # HLS C 测试台
├── hls/inputs.bin                           # 普通及边界测试向量
├── expected.bin                             # 普通及边界测试向量
└── boundary_*.bin                           # 普通及边界测试向量
```

四帧参考依次为 `1ce3 / ff00 / d12f / 1ce3`。执行命令和输出路径见 [仿真说明](../README.md)。
