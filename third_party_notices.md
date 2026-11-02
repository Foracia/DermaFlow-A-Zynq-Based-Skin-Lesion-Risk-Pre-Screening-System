# 第三方内容与许可

根目录 LICENSE 中的 MIT 许可适用于项目团队拥有版权的代码、模型参数及 Skill。下面列出的第三方内容保留其原有版权和许可，根目录 MIT 不替代这些条款。

| 内容 | 本项目中的位置 | 来源与许可 |
|---|---|---|
| ncnn 及相关第三方声明 | `src/cnn/ncnn_license.txt`、`board/cpu/licenses/ncnn_license.txt` | Tencent ncnn；原文件含 BSD-3-Clause 及其附带组件声明 |
| Digilent 视频 IP | `src/video/ip/dvi2rgb/`、`rgb2dvi/` 等 | 保留各源文件中的 Digilent 版权及 BSD-3-Clause 条文；具体适用范围以各文件头为准 |
| 动态时钟与 AMD/Xilinx 文件 | `src/video/ip/axi_dynclk/`、其他 IP 和工具生成文件 | 保留源文件中的 AMD/Xilinx、Digilent 声明；例如 mmcme2_drp.v 中的 Xilinx 器件使用条款。此类文件不由根目录 MIT 重新授权 |
| CNN 训练交付 | `src/cnn/training/`、`data/models/` | 来源为项目模型训练交付，团队原创代码及自有训练结果采用根目录 MIT；依赖组件和外部权重按其来源许可 |
| 外部数据集 | `data/models/split.json`、`calibration_list.txt` 所引用的图片 | PAD-UFES-20（Pacheco 等，2020），CC BY 4.0；类别映射、患者划分及预处理见 data/dataset/README.md，图片许可不受根目录 MIT 覆盖 |
| Python、PYNQ 和模型工具依赖 | 各 requirements 文件及 Python 导入 | 分别遵循对应软件包的上游许可证 |

ncnn：https://github.com/Tencent/ncnn 。外部数据来源：https://data.mendeley.com/datasets/zr7vgbcyr2/1 ，采用 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)，数据来源和处理说明见 [数据说明](data/dataset/README.md)。仓库提供划分与索引，完整数据集由外部获取。

第三方子目录的原 LICENSE、NOTICE 及源文件版权头随组件保留。分发原组件或其修改版本时，保留相应的署名及许可声明。
