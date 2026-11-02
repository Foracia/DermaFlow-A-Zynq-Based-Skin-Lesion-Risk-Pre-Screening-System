# CNN 硬件定点量化与参数导出

本文件夹为本项目最终 CNN 加速电路的量化部分。脚本读取已训练的 ONNX 模型，按固定精度规则生成整数权重和偏置，再按硬件并行计算顺序打包为 HLS 权重头文件。

```text
src/cnn/quantization/
├── fixed_model.py          # 加载 ONNX，执行固定点参数量化并描述各层计算
├── fixed_arithmetic.py     # 整数舍入、饱和、卷积与池化参考运算
├── export_parameters.py    # 导出 11 份整数参数与 weights.h，并检查一致性
└── requirements.txt        # NumPy、ONNX 依赖
```

## 输入与输出

输入为工程根目录的 `data/models/model.onnx` 和 `data/models/pl_quantized/recipe.json`。原有最终参数保存在 `data/models/pl_quantized/parameters/`，HLS 使用的参数保存在 `src/cnn/hls/weights.h`。

本实现采用各层独立的有符号固定点格式，舍入采用 ties-to-even，超范围值采用饱和处理。逐层位宽、小数位和参数误差见 `data/models/pl_quantized/quantization.json`。这是 PL 计算采用的参数形式；CPU ncnn 的 KL／EQ 模型另存于 `board/cpu/models/`。

## 参数导出与核对

在安装本目录依赖的 Python 环境中，从工程根目录执行，输出目录须为新目录：

```bash
python src/cnn/quantization/export_parameters.py --out build/output/pl_parameters
```

程序将重新计算的整数参数与随包参数逐项比较，再检查打包结果是否与 HLS 的 `weights.h` 完全一致。成功标记为 `PARAMETERS_AND_HLS_HEADER_MATCH`；输出包含参数 NPY、`weights.h`、量化说明和 SHA 清单。该操作只执行参数量化与导出，不训练模型或构建 FPGA 工程。
