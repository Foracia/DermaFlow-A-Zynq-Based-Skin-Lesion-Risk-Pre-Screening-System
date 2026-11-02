---
name: heterogeneous-performance-evaluation
description: Use when benchmarking CPU, ARM, FPGA, heterogeneous inference, image archiving, or end-to-end applications; when comparing baseline and optimized latency; or when timing boundaries, warmup, paired inputs, P95, and speedup claims need review.
---

# 异构系统性能测量与受控对照

## Overview

先固定输入、实现身份和计时边界，再讨论速度。分别报告组件、标准化推理事务和用户完整路径，保留均值、中位数、P95、极值和原始行。

## Procedure

1. **画出时间线**：标出预处理、数据搬运、硬件事务、后处理、质量复核、编码、回读、fsync、结果显示和完整归档的起止点。
2. **定义测量对象**：为每个字段写清包含和不包含什么；避免分项重叠或把余量直接归因给某个函数。
3. **冻结身份与输入**：记录软硬件版本、模型、频率、线程、图像和顺序。移动拍摄或不同照片只能形成非受控观察。
4. **先验证等价**：确认输出、像素、质量判据和持久化合同满足要求，再比较耗时。
5. **预热并交替测量**：排除预热；优先使用 ABBA 等配对交替顺序，减少温度和 I/O 漂移的偏置。保存每轮原始记录。
6. **同时报分布**：至少给样本数、均值、中位数、P95、最小／最大值；中位数改善而 P95 变差时必须显式保留。
7. **按同边界计算加速比**：只比较同一输入、同一操作范围、同一单位的配对数据。不能把硬件事务与 CPU 完整推理拼成加速比。
8. **限制外推**：离板归档不等于视频吞吐，单张调用的耗时不等于连续多张总耗时，典型延迟不等于实时保证。

## Minimal Result Table

| 字段 | 必填内容 |
|---|---|
| 实现 | baseline／optimized 及哈希或版本 |
| 工作负载 | 固定输入、模式、样本数、预热和顺序 |
| 边界 | 起点、终点、包含项、排除项 |
| 分布 | mean、median、P95、min、max |
| 正确性 | 输出／像素／合同对照 |
| 异常 | 尾部尖峰、跳过项、未分解余量 |
| 结论范围 | 组件、完整调用、首屏、吞吐中的哪一层 |

## Common Mistakes

- 用不同实拍输入的两组均值证明优化因果。
- 只报中位数，隐藏 P95 或 max 变差。
- 把总耗时减去已测组件后的余量命名为某个未测函数。
- 把模型事务、标准化输入到 logits、完整归档和首屏显示混成一个“推理速度”。
- 用 PC 结果替代 ARM，或用组件结果替代整机吞吐。

案例见 [references.md](references.md)，应用检查见 [validation.md](validation.md)。
