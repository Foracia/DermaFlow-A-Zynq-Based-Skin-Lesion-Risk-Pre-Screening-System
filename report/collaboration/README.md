# 大模型协作与智能体工作流

本文件夹为皮肤图像采集与风险预筛系统的大模型协作记录部分，包含智能体工作流、任务模板和反馈纠错案例。

本目录包含工作流设计、任务模板和四个协作案例，呈现任务定义、工具反馈、人工纠正及流程修订。

```text
collaboration/
├── workflow.md                              # Plan／Act、验证、审查、人工决策、有界重试与交接设计
├── task-packet.md                           # 目标、权限、接口、验收和交接模板
└── evidence-scope.md                        # 记录类型、来源及验证范围
```

```text
collaboration/cases/
├── case-01-skill-design-correction.md # Skill 设计原则的人工反馈与修订
├── case-02-resource-optimization-replay.md # 资源优化历史案例回放
├── case-03-pynq-bringup-replay.md # PYNQ 启动历史案例回放
└── case-04-performance-review-replay.md # 性能审查历史案例回放
```

模型输出摘要、人工引文和工程原件分别标注来源。工作流中的自动编排机制为设计内容，桌面回放的执行范围见各案例。相关可复用流程见 [Skill 目录](../../skill/README.md)。
