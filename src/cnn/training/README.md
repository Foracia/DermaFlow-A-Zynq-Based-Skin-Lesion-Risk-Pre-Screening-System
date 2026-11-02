# CNN 模型定义与导出

本文件夹为皮肤图像采集与风险预筛系统的 CNN 模型定义与导出部分，提供网络结构代码和 PyTorch 检查点到 ONNX 的导出程序。

```text
src/cnn/training/
├── model_hybrid.py       # HybridDermCNN 模型结构
├── model_derm.py         # 基础 CNN 结构及模型构造函数
├── export_onnx.py        # 检查点加载、ONNX 导出与数值核对
├── prob_utils.py         # 概率计算辅助
├── requirements.txt      # 模型代码的 Python 依赖
└── requirements-lock.txt # 原模型开发环境的精确版本
```

本目录保存模型定义与导出辅助代码。已训练模型保存于工程根目录的 `data/models/`：`checkpoint.pt` 为 PyTorch 检查点，`model.onnx` 为包含网络和权重的 ONNX 文件；`training_config.json` 记录检查点采用的结构与训练参数。

模型输入为 RGB float32 `[1,3,128,128]`，输出为两个 logits。预处理参数及固定划分分别由 `data/models/preprocess.json` 和 `split.json` 定义。板端 CPU 模型位于 `board/cpu/models/`，CNN 硬件实现位于 `src/cnn/hls/` 和 `src/cnn/rtl/`。

## ONNX 导出

从工程根目录运行。默认读取 `data/models/checkpoint.pt`，导出结果写入新的 `build/output/model_export/`；`--checkpoint` 和 `--output-dir` 可指定其他路径。已提供的 ONNX 与检查点保留原样。

```bash
python src/cnn/training/export_onnx.py --checkpoint data/models/checkpoint.pt --output-dir build/output/model_export --split data/models/split.json --dataset /path/to/dataset.csv --img-root /path/to/images
```

`--dataset` 指包含疾病类别字段的原始索引表，`--img-root` 指外置图片根目录。训练目录输入也可通过 `--run` 指定。`requirements.txt` 为最低依赖约束，`requirements-lock.txt` 为原模型开发环境的版本记录。
