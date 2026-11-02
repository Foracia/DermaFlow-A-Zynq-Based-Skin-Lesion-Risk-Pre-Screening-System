# HLS 数值等价与分层验证：来源与演进

## 起源：转换可行不等于数值正确

早期候选材料把 ONNX→HLS 拆成工具／器件、源图、parser、C 仿真、综合和板端等层，避免 parser 能导入就宣布部署可行。后续真实工作进一步把定点类型、逐层整数参考、RTL 原码和板端批处理纳入同一证据链。

## 应用与修订

### 六样本不能替代完整候选评估

Round27 的旧 minmax8 六样本误差为 0.6223282814，但缺少完整定点 validation。团队没有凭这个小样本误差直接淘汰，而是重建 6 golden＋342 validation，并比较 legacy8、refined8、stem16 的完整指标。结果显示数值误差更小不保证所有分类指标更好，因此 Skill 增加“smoke 与完整评估分开”的门。

### 类型保护不能一删了之

新 refined 候选曾被旧 GAP16 位断言拦截。最终只新增明确的 GAP8/4→8/3 配对，保留几何、48 位累加和固定乘法规则，原生逐层验证后接纳。由此形成“先解释保护条件，再做最小扩展”的修订。

### 多帧、边界和物理排列进入验证

Round39 不只比较单帧 logits，还验证 4 帧、9 个边界帧、首层 padding 极值、ROM 逐值还原、输出通道连续序和 RTL 周期。由此把“数值正确”扩展为包括帧间状态、背压和物理排列的完整合同。

### 板端闭环

最终 343 张开发评估集 PL 批处理使用冻结温度和阈值，不重拟合；与定点参考的 max／mean logits 误差、argmax 分歧、阈值决策分歧和 raw mismatch 均为 0。这是当前最高层数值证据，但 `test_scope` 明确为开发评估集，不是未见盲测，且未应用质量门。

## 发布包证据

- [模型 golden 元数据](../../data/golden/model/meta.json)：输入 shape、dtype、布局、预处理、温度和阈值。
- [HLS／RTL 固定输入与参考](../../sim/cnn)：用于仿真层复核。
- [PL 批处理汇总](../../board/results/batch/summary.json)：343 张数值比较、计时、清理和测试范围。
- [PL 完整结果](../../board/results/batch/test_pl_result.json)：冻结工作点、逐次计时和详细输出。

研发档案：`quantization/experience/PL_优化历程续账_Round27_2026-10-24.md`、`PL_优化历程续账_Round39_2026-10-26.md`、`Agent_Skill候选材料.md`。

## 外部归属

hls4ml、AMD `ap_fixed`／`ap_int`、生成固件和运行时保持各自来源。团队贡献是整数参考、输入与布局核对、受控候选实验、完整链验证和证据组织，不声称发明 INT8、CNN 或 HLS 验证的基本概念。
