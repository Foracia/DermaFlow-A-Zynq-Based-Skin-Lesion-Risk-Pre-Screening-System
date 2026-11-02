---
name: agent-engineering-handoff
description: Use when assigning engineering work to an AI agent, coordinating human and agent responsibilities, reviewing AI-generated changes, handing off FPGA or software tasks, or designing bounded Plan/Act/Verify/Review workflows with explicit permissions and evidence.
---

# 智能体工程协作与交接

## Overview

用任务包限定目标、权限、接口和验收，用确定性工具产生证据，用独立审查寻找遗漏，用人批准需求和风险。默认轻量单主 Agent，不以角色数量代替工程质量。

## Procedure

1. **建立任务包**：写可观察目标、非目标、允许／只读路径、接口事实、验收命令、预算、审批点和需归档产物。使用 [任务包模板](../../report/collaboration/task-packet.md)。
2. **冻结基线与身份**：记录代码、模型、数据、BIT／HWH、工具和输入版本；保留已有修改和失败现场。
3. **进入 Plan**：只读检索，列影响面、候选方案、验证层和回滚方式。契约、范围或验收不完整时先询问人。
4. **进入 Act**：只修改授权路径，只调用允许工具；每轮聚焦一个主要假设。需求或接口变化时停止并回到 Plan。
5. **分层 Verify**：按任务选择静态检查、黄金参考、仿真、实现、板测和整机层。前一层通过不能替代后一层。
6. **生成失败反馈包**：保存失败阶段、命令、退出码、首个关键错误、日志位置、当前差分和允许的下一改动；不要只粘贴冗长日志。
7. **执行有界重试**：为修改—测试循环和相同错误设置上限。没有新增证据、重复同一错误、测试不稳定或预算耗尽时停止，不反复运行直到偶然通过。
8. **独立 Review**：让未参与实现的审查上下文依据原任务、差分和证据寻找遗漏。若未实际安排独立审查，明确标注缺失，不把主 Agent 自检改名。
9. **人工 Accept**：由人批准架构、接口、数据语义、风险操作、最终验收和对外表述。多个模型相互同意不能替代工具或人工验收。
10. **交接与收束**：保存完成项、证据、未完成项、失败假设、版本、清理状态和下一步；只结束自己启动且确认归属的任务。

## Permission Gate

| Agent 可在授权内执行 | 必须人工决定 | 不得作为完成证据 |
|---|---|---|
| 只读检索、候选方案、局部差分、测试草案、证据整理 | 需求、接口、阈值、数据语义、约束、安装删除、高风险上板和发布 | 模型自述正确、代码存在、多个模型同意 |
| 白名单静态检查、单元测试和仿真 | 合并、最终指标接受、Skill 对外通用化声明 | lint／综合／布线单独证明上板正确 |

## Stop Conditions

- 所需文件或接口缺失，继续执行必须猜测。
- 修改超出授权范围或需要改变验收语义。
- 相同错误达到重试上限，或新失败超出原合同。
- 需要删除测试、放宽容差／时序或隐瞒失败才能通过。
- 原始协作记录不存在；此时只能标记缺口并复盘，不能倒填。

## Handoff Output

```text
task / objective / scope
baseline and artifact identity
changes and rationale
verification stage + commands + evidence refs
failed or superseded hypotheses
human decisions and unresolved questions
cleanup / remaining risks / next owner action
```

本 Skill 的形成历史和证据边界见 [references.md](references.md)，当前应用见 [validation.md](validation.md)。
