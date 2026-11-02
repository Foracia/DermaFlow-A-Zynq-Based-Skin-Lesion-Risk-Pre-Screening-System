# PYNQ Overlay 启动与板端排障：来源与演进

## 可复用来源

本 Skill 不是某一种复位接法或某块板卡的修复脚本，而是从以下问题类中抽象出的分层启动方法：

- 普通 SSH 用户缺少 video／render 权限，sudo 又丢失 `XILINX_XRT`，而 Jupyter 使用另一 UID／环境；
- CMA 空闲值受可回收缓存影响，不能凭单个数值判断泄漏；
- 完整位流和正时序已经存在，但真实系统辅助复位长期处于有效状态；
- 首次板测需要区分元数据解析、位流下载、首次控制读和 DMA，而不是一个不可拆分的“运行”。

## 起源—应用—修订

### 起源：早期视频与质量门联调

**观察**：设备错误、CMA 和帧率问题容易被混为硬件故障。  
**形成的规则**：先核对用户／环境／内核生命周期，再追踪 CMA before／during／after，并把视频转交、软件复核、PL 吞吐和推理延迟分开。  
**边界**：一次缓存回收实验不是通用启动修复。

### 应用：首个完整 CNN 系统

**新证据**：整机 10,454 Slice、82 BRAM Tile、70 DSP、4／4 MMCM，setup +0.045 ns，独立核和整机仿真均不能排除外围复位错误。  
**修订**：把“实际生成复位 IP、有效电平和驱动常量”加入启动合同，不能用独立核测试替代系统启动测试。

### 反例与再修订：首次板端无响应

**失败**：低有效 `aux_reset_in` 接常量 0，导致持续复位。  
**修正**：只把辅助复位常量改为非激活值，保留模型和其他接口；增加 BD／HWH 电平检查。  
**新增流程门**：metadata／load／control 独立执行，危险调用前后持久记录，控制通过后再允许 DMA。

### 当前有效版本

先环境和身份，后真实复位与控制，再 DMA 和业务流；每一层都有独立停止点。发布包中的 `board_stage_probe.py` 是该思想的可审查实现，不是适用于所有 Overlay 的固定地址表。

## 发布包证据

- [分阶段启动工具](../../board/hardware/board_stage_probe.py)：明确禁止 DMA，仅执行 metadata／load／control。
- [复位合同](../../board/hardware/reset_contract.json)：记录辅助复位和 debug 复位的非激活常量及证据哈希。
- [控制阶段真实记录](../../board/results/golden/stage_control_8694915ffcfb4ce38177ea2bf9782983.jsonl)：每个调用均有 BEGIN／COMPLETE，最后为 `PHASE_PASS`。
- [板端证据清单](../../board/results/golden/manifest.json)：包含 BIT／HWH 身份、目标器件、资源与时序；其中历史 `BUILT_NOT_BOARD_TESTED` 状态属于清单生成时，后续阶段记录需一并阅读。

研发档案：`quantization/experience/BOARD_VIDEO_质量门联调记录_2026-10-27.md`、`PL_优化历程续账_Round40_2026-10-27.md`、`PL_优化历程续账_Round41_2026-10-27.md`。

## 外部归属

PYNQ 提供 Overlay／MMIO 运行时，AMD 提供复位 IP、AXI DMA、工具和生成文件。团队贡献是系统集成、复位缺陷修复、分阶段验证与证据组织；不声称这些基础 IP 或协议为团队原创。
