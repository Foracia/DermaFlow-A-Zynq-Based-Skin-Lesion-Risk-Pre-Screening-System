# CNN 实现

本文件夹为皮肤图像采集与风险预筛系统的 CNN 模型与加速电路部分，包含模型定义、固定点量化、HLS 计算代码和当前部署 RTL。

```text
cnn/
├── quantization/                            # 最终 PL 定点模型的量化与导出脚本
├── hls/core.cpp                             # HLS 顶层 grouped_network 及声明
├── core.h                                   # HLS 顶层 grouped_network 及声明
├── hls/grouped.h                            # 分组计算和首层并行结构
├── stem16.h                                 # 分组计算和首层并行结构
├── hls/weights.h                            # 权重常量及调试定义
├── debug.h                                  # 权重常量及调试定义
├── rtl/cnn_accel_axi.v                      # AXI 控制与流接口包装
├── rtl/grouped_network.v                    # 计算顶层
├── rtl/grouped_network_*.v                  # 生成的计算单元与配套 ROM 初始化
├── *.dat                                    # 生成的计算单元与配套 ROM 初始化
├── training/                                # 模型定义、ONNX 导出及概率辅助代码
└── ncnn_license.txt                         # ncnn 许可证
```

整机构建采用 `rtl/` 中的实现；独立 HLS 综合输出位于构建工作目录。`stem16` 表示计算并行结构。测试输入和参考见 [sim/cnn](../../sim/cnn/README.md)，部署接口见 [board/hardware](../../board/hardware/README.md)。
