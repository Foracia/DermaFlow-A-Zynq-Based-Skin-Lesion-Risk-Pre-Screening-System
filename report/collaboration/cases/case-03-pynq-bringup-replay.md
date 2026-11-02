# 案例 03：PYNQ 首次上板历史案例回放

**记录类型**：`NEW_COLLABORATION_RECORD`＋`HISTORICAL_ARTIFACT`  
**对应 Skill**：[PYNQ Overlay 启动与板端排障](../../../skill/pynq-overlay-bringup/SKILL.md)

## 1. 回放任务提示

> 依据 Round40／41 材料，解释为什么位流存在、整机 setup 为正且独立 CNN 测试正确，首次板端控制访问仍可能无响应。给出可停止的分阶段诊断，不得直接归因 DMA 或重复下载位流。随后用权限／CMA 材料检查第 0 层边界。

这是最终收束材料时的人机协同记录中的桌面回放任务，不是开发期逐字提示词。

## 2. 输入证据

- Round40 整机 setup WNS 为 `+0.045 ns`，独立 CNN 测试已有正确输出。
- HWH、实际生成 VHDL 和 BD 一致表明低有效 `aux_reset_in` 接常量 0，长期处于有效复位。
- 修复后使用 metadata、load、control 分阶段入口；控制阶段实际读取 ABI、输入词数、时钟和 DMA 状态并达到 `PHASE_PASS`。
- 另一视频联调材料包含普通 SSH 权限、sudo 环境、Jupyter 内核和 CMA 问题。

参考资料：[PYNQ 案例与证据](../../../skill/pynq-overlay-bringup/references.md)。

## 3. 模型输出摘要

**以下为最终收束材料时的人机协同记录中的模型输出摘要，不是开发期原始回答。**

位流、时序和独立核测试分别证明产物存在、物理约束和测试台激励下的功能，均未覆盖真实系统复位生成与连接。应先检查实际 BD／VHDL 中复位极性和常量，再按 metadata → load → control → DMA 分阶段推进。控制读未通过时不能启动 DMA。权限／CMA 案例还应先检查 UID、组、sudo 环境和既有内核；单次 CMA 空闲值不能证明泄漏。

## 4. 工具反馈与修正

真实系统 HWH／VHDL／BD 将问题定位到 `aux_reset_in`，替代了笼统“板卡失联”或“DMA 卡死”的猜测。修复后的分阶段控制读提供系统层验证。

最终收束材料时的人机协同应用进一步把权限、运行环境和既有内核前置为第 0 层，并补充“短测通过不外推长期无泄漏”。

## 5. 验证

[validation.md](../../../skill/pynq-overlay-bringup/validation.md) 记录：

- 历史 RED：独立核测试未覆盖真实系统 reset；
- 当前 GREEN：权限／CMA 材料应用为 `PASS_WITH_NOTES`；
- REFACTOR：环境先于 Overlay 下载，危险调用前后持久记录。

本检查由同一位在最终收束材料时参与人机协同的执行 Agent 完成，不是独立 Agent、新上板或跨 PYNQ 版本验证。

## 6. 最终可交付结论

可写“通过实际系统复位合同和分阶段板端入口定位并验证首次启动问题”。不可写“只要 setup 和独立 CNN 仿真通过，整机板端就必然正常”，也不以 Python 超时宣称 AXI 防死锁。
