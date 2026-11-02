---
name: hls-numerical-validation
description: Use when converting CNN or other numerical models to HLS, fixed-point, generated RTL, FPGA overlays, or when software and hardware logits disagree.
---

# HLS 数值等价与分层验证

## Overview

把“模型能转换”拆成图语义、布局、定点、仿真、RTL、实现和板端证据。每一层都使用同一身份链；上一层成功不能代替下一层。

## When to Use

适用于 ONNX→HLS、FP32→INT8／ap_fixed、NCHW／NHWC 迁移、池化边界、Flatten 顺序、ROM 重排，以及 HLS／RTL／板端输出比较。纯训练精度评估不包含硬件层，不能冒充本流程完成。

## Quick Reference

| 层 | 核心问题 | 最小证据 |
|---|---|---|
| G0 身份 | 比的是哪个模型和输入 | 模型、权重、预处理、split、标签、参考哈希 |
| G1 图语义 | 算子属性是否等价 | Conv／Pool／Gemm 属性与边界检查 |
| G2 布局 | 轴序和打包是否一致 | shape、dtype、NCHW／NHWC、字序与通道序 |
| G3 定点 | 舍入、饱和、累加是否一致 | 类型合同、部分和界、逐层整数参考 |
| G4 仿真 | 生成实现是否按合同工作 | golden＋边界＋多帧逐层或端到端原码 |
| G5 物理／板端 | 集成后是否仍一致 | 实现身份、板端 logits、误差和清理记录 |

## Procedure

1. **冻结参考**：记录源模型、权重、预处理、输入顺序、类别映射、温度／阈值来源。不得复用旧模型的分析 JSON。
2. **检查真实算子属性**：不要只看算子名称；核对 stride、padding、group、池化计数、Flatten 排列和 Gemm 转置。
3. **显式建立布局合同**：用固定输入验证 RGB／BGR、NCHW／NHWC、打包字序和输出通道序； ROM 重排后还原逐值比对。
4. **建立整数参考**：先证明乘积对齐、部分和不溢出以及舍入／饱和顺序，再使用快速矩阵乘或重放；否则逐运算模拟。
5. **先小后全**：golden smoke 只证明运行与局部一致；完整 validation 才用于候选指标比较。保留边界、重复帧、背压和帧间状态测试。
6. **逐层锚定后接完整链**：先定位到最小差异层，再在完整网络检查输出和周期，防止局部修复被集成抵消。
7. **分层报告**：分别写 C 仿真、RTL、物理实现和板端结果。物理通过不证明数值，数值一致也不证明时序。

## Common Mistakes

- 用六样本误差直接淘汰或选定模型。
- 删除类型断言来“修复”新位宽，而不检查它保护的算术条件。
- 把逻辑相等和文件字节相同混为一谈；换行变化需分别检查语义与执行身份。
- 把 ncnn INT8、HLS 定点和源 FP32 当成天然同一参考。
- 只报 argmax 一致，遗漏 logits、概率、阈值决策或原始码差异。

## Validation

根据任务声明最高证据层。完整板端比较至少报告样本数、参考来源、max／mean 误差、argmax／阈值分歧和清理状态；若数据集参与过开发，必须保留非盲测说明。

案例见 [references.md](references.md)，基线与应用检查见 [validation.md](validation.md)。
