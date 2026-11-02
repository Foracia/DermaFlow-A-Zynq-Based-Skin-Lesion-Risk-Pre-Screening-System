---
name: quantized-model-evaluation
description: Use when comparing FP32, QDQ, INT8, PTQ, ORT, ncnn, HLS, or FPGA model candidates; when calibrating temperature or thresholds; or when model identity, preprocessing, data splits, golden references, and classification metrics may be inconsistent.
---

# 量化模型参考锁定与候选评估

## Overview

先锁定“模型—输入—数据—参考—工作点—指标”身份链，再比较候选。固定原工作点与重新标定是两类实验；不同 golden 的误差不能横向排名。

## Procedure

1. **锁定模型身份**：记录源模型、候选权重、转换工具、runtime、provider、线程和哈希。不要仅信 JSON 中硬编码的候选名称。
2. **冻结输入合同**：保存 shape、dtype、RGB／BGR、NCHW／NHWC、resize、mean／std、类别映射和样本顺序；禁止复用旧模型分析文件。
3. **核对数据边界**：确认 calibration 来自 train，val 用于拟合／选择，dev／test 的实际开发历史如实记录。区分图像级与患者级划分证据。
4. **建立分层参考**：先建立当前环境 FP32 reference，再检查转换后 FP32，最后评估 INT8／定点。ORT、ncnn 和 HLS 参考不得默认互换。
5. **拆分工作点**：分别保存“固定原温度／阈值”和“val 重标定温度／阈值”；后者写明拟合 split 和选择规则，不在开发评估集上重新调参后仍称盲测。
6. **统一指标定义**：报告混淆矩阵、recall、specificity、BA、macro-F1、AUC、NLL／Brier及数值误差；注明 binary F1 或 macro-F1。单病种子集只计算有定义的指标。
7. **联合选择**：同时展示精度、数值、文件体积和已测性能；数值误差更小不代表所有分类指标更好，文件缩小不代表 RAM／BRAM 同比例缩小。
8. **保留边界**：小样本 smoke 只证明运行与局部一致；PC 延迟不代表 ARM；没有批准的验收阈值时报告结果，不伪造 PASS。

## Required Candidate Record

```text
candidate identity + hashes
runtime / provider / threads
preprocessing + class mapping
calibration / validation / evaluation split history
reference model and golden identity
temperature + threshold + fitting split + comparison rule
confusion counts + metric definitions + numeric errors
measured performance boundary + unresolved limitations
```

## Common Mistakes

- 把固定阈值结果与 val 重标定结果当作互相矛盾或同口径排名。
- 用 KL 对 KL 的零误差和 EQ 对 FP32 的非零误差直接比较候选优劣。
- 沿用早期“untouched test”措辞，忽略该 split 后续已参与开发。
- 把单病种子集的缺失类计 0 后解释为很差的 BA 或六分类能力。
- 用六张 golden 或 argmax 一致代替完整指标和逐值误差。

案例见 [references.md](references.md)，应用检查见 [validation.md](validation.md)。
