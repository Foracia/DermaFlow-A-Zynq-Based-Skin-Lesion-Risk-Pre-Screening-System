# Agent Skill

本文件夹为皮肤图像采集与风险预筛系统的 Agent Skill 部分，将 FPGA 部署、模型验证和工程协作经验整理为七个可复用流程。

本目录包含七个工程流程 Skill，覆盖 FPGA 部署、数值验证、资源优化、性能测量、量化评估、经验整理和智能体协作。

## 内容

```text
skill/
├── pynq-overlay-bringup/                         # PYNQ 启动与排障
├── hls-numerical-validation/                     # HLS 数值验证
├── fpga-resource-timing-optimization/            # FPGA 资源与时序优化
├── heterogeneous-performance-evaluation/         # 异构性能测量
├── quantized-model-evaluation/                   # 量化模型评估
├── engineering-experience-distillation/          # 工程经验整理
├── agent-engineering-handoff/                    # 智能体协作与交接
└── evidence_index.md                             # 工程证据索引
```

## 文件结构

每个 Skill 目录包含三份文件：

```text
<skill_name>/
├── SKILL.md        # 触发条件、输入、步骤、验证和停止条件
├── references.md   # 工程来源、案例和原始证据
└── validation.md   # 历史问题、应用结果和修订范围
```

使用时，将相应 `SKILL.md` 与任务目标、接口文件和日志一并提供给 Agent。具体地址、模型参数及工作点由项目接口文件确定。

[证据索引](evidence_index.md)汇总工程产物与 Skill 的对应关系；[协作材料](../report/collaboration/README.md)包含工作流、任务包及案例。验证记录区分历史工程结果与收束阶段桌面回放。
