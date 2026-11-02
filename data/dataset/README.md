# 数据来源与处理说明

## 来源与许可证

本项目使用 Pacheco 等人发布的 **PAD-UFES-20** 皮肤病变临床图像数据集。

- 数据下载：https://data.mendeley.com/datasets/zr7vgbcyr2/1
- 数据 DOI：https://doi.org/10.17632/zr7vgbcyr2.1
- 数据集论文：https://doi.org/10.1016/j.dib.2020.106221
- 许可证：**CC BY 4.0**，https://creativecommons.org/licenses/by/4.0/

数据及其派生图像遵循 CC BY 4.0，使用和分发时保留来源署名、许可证链接及处理说明。项目代码的 MIT 许可不替代数据集许可。

## 本项目的处理

**类别映射。** 使用 ACK、BCC、MEL、NEV、SCC、SEK 六类，共 2295 张图像。根据本项目风险预筛任务，将 ACK、BCC、MEL、SCC 归入 label=1，NEV、SEK 归入 label=0。这是本项目的二分类定义。

**数据划分。** 以患者 ID 为单位划分，同一患者的图像只进入一个集合，避免同一患者同时出现在训练与评估中。固定划分为训练集 1610 张、验证集 342 张、开发测试集 343 张，记录于 `split.json`。

**图像预处理。** 转换为 RGB，以 PIL 双线性插值缩放至 128×128，不裁剪、不填充。像素除以 255 后按通道归一化，均值和标准差由训练集计算：

```text
mean = [0.66557, 0.522759, 0.462534]
std  = [0.14092, 0.140212, 0.146932]
```

发布工程中的划分与预处理参数分别位于 `data/models/split.json` 和 `data/models/preprocess.json`。完整数据集从上述来源获取；随包参考样本保留同一数据来源与许可。
