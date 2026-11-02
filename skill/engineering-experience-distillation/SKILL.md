---
name: engineering-experience-distillation
description: Use after engineering, debugging, FPGA, AI-collaboration, or documentation sessions to turn scattered records into evidence-linked reports or reusable Agent Skills; when classifying failures, decisions, evidence, attribution, and validation boundaries without fabricating history.
---

# 工程经验蒸馏与 Skill 迭代

## Overview

保存可复用知识和工程判断，不堆积聊天。先核查实际证据，再路由到 `REPORT`、`SKILL`、`BOTH` 或 `NONE`；证据不足时降低结论强度，而不是补造确定性。

## Procedure

1. **记录最小上下文**： contributor、工作包、活动类型、阶段、日期和实际使用的工具；未知字段留空或标未知。
2. **收集高价值事件**：优先选择改变方向的决策、可复用失败、实验结果、工程权衡、非显然调试和复现约束。常规确认、重复讨论和无项目价值的常识归入 `NONE`。
3. **分离事实与表达**：逐条区分实际执行、直接观察、模型解释、后续计划和被新证据替代的旧结论。AI 建议不得改写成已完成工作。
4. **标注证据状态**：按需使用下表，并附报告、日志、源码、命令、配置、哈希或外部来源。缺失来源就写缺失。
5. **选择材料路由**：项目特定事实和取舍进入 `REPORT`；可触发、可执行、可验证的一类任务流程进入 `SKILL`；两者兼有进入 `BOTH`；无长期价值进入 `NONE`。
6. **抽象项目常量**：把具体地址、病种、阈值和路径留在项目证据中，把识别问题、操作顺序、验证门和失效条件写进 Skill。
7. **形成最小 Skill**：写清触发描述、前置条件、步骤、验证、常见错误和边界。一次真实使用不是 Skill 的存在门槛；后续复用和失败反馈用于提高有效性。
8. **保留演进链**：记录“来源失败／观察 → 初版流程 → 实际应用 → 反馈 → 修订 → 当前边界”。不要为显得成熟而倒填不存在的复用历史。
9. **核查归属与发布风险**：区分团队原创、项目适配、外部思想、修改实现和直接复制；保留许可证与署名，移除凭据和隐私。
10. **执行反事实审查**：问“评委要求证明时能拿出什么”。没有证据的结论降级为 `INFERRED` 或 `UNVERIFIED`，无法支持者删除。

## Evidence Labels

| 标签 | 含义 |
|---|---|
| `VERIFIED` | 有直接测试、报告、产物或权威来源支持，保留测试条件 |
| `OBSERVED` | 直接观察到现象，根因未必确定 |
| `INFERRED` | 基于证据的工程推断 |
| `UNVERIFIED` | 尚未执行或验证的方案、假设、计划 |
| `FAILED` | 在明确条件下实际失败 |
| `SUPERSEDED` | 已被更强证据替代的旧结论 |
| `EXTERNAL` | 主要来自第三方资料或实现 |

成熟度可用来描述证据覆盖，但不得把 L4、跨项目复验或长期迭代误当成“能否整理为 Skill”的资格门槛。

## Output

- `REPORT`：候选要点、工程意义、证据状态、支撑证据、署名和建议章节。
- `SKILL`：可独立触发的 `SKILL.md`，必要时附按需读取的参考资料。
- `BOTH`：共享同一证据索引，分别写项目事实与可复用流程，避免重复正文。
- `NONE`：明确不长期保存，不强行生成材料。

## Common Mistakes

- 逐句压缩整场聊天，或因为记录很长就强行产生 Skill。
- 把后期复盘写成开发期原始对话，或虚构模型版本、提示词和验证记录。
- 删除失败、尾部变差和不利结果，只保留成功故事。
- 把外部方法、生成代码或开源实现包装成团队原创。
- 把“当前尚未跨项目验证”写成“不能形成 Skill”。

来源和最终收束材料时的人机协同应用见 [references.md](references.md)，纠错与验证见 [validation.md](validation.md)。
