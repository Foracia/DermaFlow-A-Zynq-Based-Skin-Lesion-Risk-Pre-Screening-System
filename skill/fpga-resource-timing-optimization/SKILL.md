---
name: fpga-resource-timing-optimization
description: Use when optimizing FPGA or HLS resources, timing, latency, memory banking, scheduling, or generated RTL, especially when LUT, BRAM, DSP, WNS, or cycle improvements must be compared without changing numerical behavior.
---

# FPGA 资源—时序—延迟协同优化

## Overview

把每次优化视为一项可否决的受控候选，而不是单项指标故事。同时守住源身份、数值合同、真实物理资源、周期和完整链回归。

## Required Inputs

- 固定基线的源文件、模型／权重、工具版本、器件、频率和实现策略。
- 同口径的 LUT、FF、Slice、BRAM、DSP、WNS／WHS、TNS／THS 和周期基线。
- 可重放的数值或原码参考，以及允许修改和禁止修改的范围。

缺少任一项时先补测量或标记未知，不用估算值填空。

## Procedure

1. **分解成本**：按层、存储、数据搬运和控制定位成本；区分 HLS 估算、综合、实现和整机实测。
2. **冻结基线**：保存源身份、报告、配置和日志；只使用同一部署基线做配对比较。
3. **提出单变量候选**：说明改变的结构、保持的接口／精度／并行度，以及预期收益和可能迁移的成本。
4. **先做数值门**：逐地址、逐周期或端到端比较；包含边界、多帧、背压和帧间状态。失败即否决，不用物理收益抵消。
5. **检查真实 primitive**：阅读综合／实现报告，确认目标资源确实落在预期 RAM／DSP／逻辑上。`ram_style` 或 `rom_style` 只是提示，不是映射保证。
6. **做联合评价**：同时列出 LUT、FF、BRAM、DSP、频率余量和周期；若目标资源下降伴随其他资源大幅上升，明确判定为迁移或折中。
7. **接回完整计算链**：重放原码、接口、周期和控制测试，再做同条件物理实现；局部节省未被整核保留时不得扣减整机预算。
8. **分层签核**：分别报告局部候选、完整 CNN 计算链和完整系统结果。未集成、未实现或未上板的阶段保持未验证。

## Decision Gate

| 门 | 通过条件 | 失败动作 |
|---|---|---|
| 身份 | 基线、候选、工具和输入可追踪 | 停止比较 |
| 数值 | 参考、原码和接口合同通过 | 否决候选 |
| 映射 | 实际 primitive 符合设计意图 | 检查资源迁移 |
| 物理 | 资源与 setup／hold 同口径可接受 | 保留报告，不签核 |
| 完整链 | 原码、周期、背压和集成回归通过 | 回退或局部化结论 |

## Common Mistakes

- 把 BRAM 变少直接写成优化成功，忽略 LUT 暴增。
- 用平均工作量推断有限 FIFO 流水线吞吐，或直接相信 HLS 延迟估算。
- 用旧模型、旧包装或不同实现策略的报告拼出“新整机”。
- 只看单项 setup WNS，遗漏 hold、周期、数值和真实映射。
- 为保留失败候选而删除失败日志或放宽参考。

## Output

输出基线／候选对照表、数值证据、真实资源映射、完整链回归、保留或否决决定，以及未覆盖层级。案例见 [references.md](references.md)，应用检查见 [validation.md](validation.md)。
