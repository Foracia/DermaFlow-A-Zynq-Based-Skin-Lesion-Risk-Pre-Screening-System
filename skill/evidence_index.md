# Skill 与大模型协同证据索引

### 【建议】证据包内容较多，结构较复杂，可先阅读每个 Skill 的 `references.md`，再按上表抽查发布包内原始证据。

本索引把可复用 Skill、代表性协作案例和工程证据连起来。发布包内路径均相对于本仓库工程根目录；研发档案路径用于追溯原始材料，不表示这些档案全部随发布目录复制。

来源类别见 [协作证据范围](../report/collaboration/evidence-scope.md)。

## 七个 Skill

| Skill                                                                   | 发布包内可核查证据                                                                                          | 可复用结论摘要                                                              |
| ----------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| [PYNQ Overlay 启动与板端排障](pynq-overlay-bringup/SKILL.md)            | `board/hardware/board_stage_probe.py`；`board/results/golden/`；`board/hardware/reset_contract.json` | 先核对权限、环境和产物身份，再把 metadata、load、control、DMA 分阶段验证；正时序和独立核仿真不能排除系统复位错误 |
| [HLS 数值等价与分层验证](hls-numerical-validation/SKILL.md)               | `sim/cnn/`；`board/results/batch/`；`data/golden/model/`                                             | 模型图、布局、定点合同、C 仿真、RTL、实现和板端是不同证据层；端到端一致必须由同一输入与参考链证明                  |
| [FPGA 资源—时序—延迟协同优化](fpga-resource-timing-optimization/SKILL.md)  | `build/reports/system/`；`build/reports/cnn/`；`src/cnn/rtl/`               | 单项资源下降不等于优化成功；候选必须同时通过数值、真实 primitive、周期、时序和完整链回归                    |
| [异构系统性能测量与受控对照](heterogeneous-performance-evaluation/SKILL.md)   | `data/evaluation/cpu/`；`board/results/timing/`；`board/results/system_ui/`                          | 先统一计时边界和输入，再比较均值、中位数、P95 与原始行；典型改善不能替代尾部或整机吞吐结论                      |
| [量化模型参考锁定与候选评估](quantized-model-evaluation/SKILL.md)             | `data/models/`；`data/evaluation/cpu/`；`board/cpu/interface/`                                       | 先锁模型身份、预处理、split、参考输出和工作点，再比较 FP32／INT8；不同参考和不同阈值口径不得混排              |
| [工程经验蒸馏与 Skill 迭代](engineering-experience-distillation/SKILL.md) | 本目录各 Skill 的 `references.md`、`validation.md` 与协作案例                                                 | 保存可复用流程、失败和证据，不堆积聊天；REPORT／SKILL／BOTH／NONE 分流并保留来源与不确定性              |
| [智能体工程协作与交接](agent-engineering-handoff/SKILL.md)                 | `report/collaboration/task-packet.md`；`report/collaboration/cases/`；各 Skill 验证记录                                 | 用任务包限定目标、权限、接口和验收，以工具证据和人工门控制修改、重试、交接与停止                             |

## 协作案例

| 案例                                                                             | 记录类型                                             | 对应 Skill             | 主要证明                                       |
| ------------------------------------------------------------------------------ | ------------------------------------------------ | -------------------- | ------------------------------------------ |
| [Skill 设计中的成熟度误判与人工纠正](../report/collaboration/cases/case-01-skill-design-correction.md) | `NEW_COLLABORATION_RECORD`                       | 工程经验蒸馏；智能体工程协作与交接    | 展示真实提示词、模型初始判断、用户纠正和设计修订；成熟度不是 Skill 的存在门槛 |
| [资源优化历史案例回放](../report/collaboration/cases/case-02-resource-optimization-replay.md)      | `NEW_COLLABORATION_RECORD`＋`HISTORICAL_ARTIFACT` | FPGA 资源—时序—延迟协同优化    | 检查模型是否能识别资源迁移和单项指标误判，并用真实后续结果修订流程          |
| [PYNQ 首次上板历史案例回放](../report/collaboration/cases/case-03-pynq-bringup-replay.md)          | `NEW_COLLABORATION_RECORD`＋`HISTORICAL_ARTIFACT` | PYNQ Overlay 启动与板端排障 | 检查分阶段诊断是否比重复加载和笼统“板卡失联”更能定位问题              |
| [性能结果审查历史案例回放](../report/collaboration/cases/case-04-performance-review-replay.md)       | `NEW_COLLABORATION_RECORD`＋`HISTORICAL_ARTIFACT` | 异构系统性能测量与受控对照        | 检查模型能否发现非受控输入、计时边界和尾部指标问题                  |
