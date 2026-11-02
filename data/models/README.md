# 模型文件

本文件夹为皮肤图像采集与风险预筛系统的 CNN 模型部分，保存训练结果、硬件定点参数以及预处理和数据划分定义。

```text
models/
├── pl_quantized/                            # 最终加速电路的整数权重、偏置及精度定义
├── model.onnx                               # 冻结网络与权重
├── checkpoint.pt                            # PyTorch 检查点
├── contract.json                            # 输入输出接口
├── preprocess.json                          # 缩放、通道与归一化定义
├── training_config.json                     # 训练配置
├── split.json                               # 固定样本、标签和分组
└── calibration_list.txt                     # 训练集中 298 张量化校准样本名单
```

模型输入为 RGB float32 `[1,3,128,128]`，PIL BILINEAR 缩放；mean 为 `[0.66557,0.522759,0.462534]`，std 为 `[0.14092,0.140212,0.146932]`。输出为两个 logits。

ncnn 模型位于 [board/cpu](../../board/cpu/README.md)，PL 部署文件位于 [board/hardware](../../board/hardware/README.md)。

模型结构代码位于 `src/cnn/training/`（相对工程根目录），其中 `model_hybrid.py` 定义检查点采用的 HybridDermCNN，`model_derm.py` 提供 CNN 构造函数，`export_onnx.py` 完成检查点到 ONNX 的导出及核对。`model.onnx` 同时包含网络与已训练权重；`checkpoint.pt` 为对应 PyTorch 检查点。
