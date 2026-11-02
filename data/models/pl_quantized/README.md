# CNN 加速电路定点参数

本文件夹为本项目最终 CNN 加速电路使用的量化模型参数。参数由已训练 CNN 转换得到，并用于生成 `src/cnn/hls/weights.h`。

```text
data/models/pl_quantized/
├── parameters/               # 11 份整数权重与偏置数组
│   ├── conv_0_weight.npy     # 首层卷积权重
│   ├── conv_0_bias.npy       # 首层卷积偏置
│   ├── conv_1_weight.npy     # 第二层卷积权重
│   ├── conv_1_bias.npy       # 第二层卷积偏置
│   ├── conv_2_weight.npy     # 第三层卷积权重
│   ├── conv_2_bias.npy       # 第三层卷积偏置
│   ├── conv_3_weight.npy     # 第四层卷积权重
│   ├── conv_3_bias.npy       # 第四层卷积偏置
│   ├── matmul_0_weight.npy   # 输出层权重
│   ├── matmul_0_bias.npy     # 输出层矩阵计算偏置
│   └── add_0_bias.npy        # 输出层加法偏置
├── recipe.json               # 从原模型到固定点格式的精度规则
├── quantization.json         # 各层格式、量化误差及累加范围
└── manifest.json             # 本参数包及配套 HLS 权重 SHA
```

NPY 保存整数值；其对应的比例系数、小数位、舍入和饱和规则由 JSON 定义。该固定点模型通过整数参数与硬件运算规则表达，HLS 权重头文件和 RTL 共同实现其计算。

量化及导出程序位于 `src/cnn/quantization/`。CPU 用的 ncnn INT8 模型位于 `board/cpu/models/kl/` 和 `eq/`，用于软件对照测试。
