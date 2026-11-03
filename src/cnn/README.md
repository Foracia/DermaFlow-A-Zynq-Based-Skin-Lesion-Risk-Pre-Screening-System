# CNN 实现

本文件夹为皮肤图像采集与风险预筛系统的 CNN 模型与加速电路部分，包含模型定义、固定点量化、HLS 计算代码和当前部署 RTL。

```text
cnn/
├── training/                               # 模型定义、ONNX 导出及概率辅助代码
├── quantization/                           # PL 定点模型的量化与参数导出
├── hls/                                    # HLS 计算实现
│   ├── core.cpp                            # grouped_network 顶层
│   ├── core.h                              # 顶层声明
│   ├── grouped.h                           # 分组计算
│   ├── stem16.h                            # 首层并行结构
│   ├── weights.h                           # 权重常量
│   └── debug.h                             # 调试定义
├── rtl/                                    # 整机构建采用的 CNN 电路
│   ├── cnn_accel_axi.v                      # AXI 控制与流接口包装
│   ├── grouped_network.v                   # 计算顶层
│   ├── grouped_network_*.v                 # 计算子模块
│   └── *.dat                               # ROM 初始化数据
└── ncnn_license.txt                        # ncnn 许可证
```

整机构建采用 `rtl/` 中的实现；独立 HLS 综合输出位于构建工作目录。`stem16` 表示计算并行结构。测试输入和参考见 [sim/cnn](../../sim/cnn/README.md)，部署接口见 [board/hardware](../../board/hardware/README.md)。
