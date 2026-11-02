---
name: pynq-overlay-bringup
description: Use when a PYNQ Overlay, MMIO, DMA, video pipeline, or first board test fails, hangs, resets, reports No Devices Found, or exhausts CMA.
---

# PYNQ Overlay 启动与板端排障

## Overview

把“板端不工作”拆成可停止、可记录的证据层。先证明运行环境、硬件身份、复位和控制接口，再启动 DMA 或完整视频；不要用重复加载代替定位。

## When to Use

适用于首次加载 Overlay、HWH 地址不符、MMIO 无响应、DMA 卡住、CMA 不足，以及 sudo 后设备不可见。若只是纯算法误差且控制与传输已证明正常，应转用数值验证 Skill。

## Quick Reference

| 层 | 必查内容 | 通过后才可进入 |
|---|---|---|
| 0 环境 | 用户／组、设备节点、`XILINX_XRT`、Python ABI、既有内核 | 元数据检查 |
| 1 身份 | BIT／HWH／manifest、IP VLNV、地址、时钟、缓冲和复位合同 | 下载位流 |
| 2 元数据 | `Overlay(..., download=False)`、`ip_dict`、`register_map` | 实际加载 |
| 3 加载 | 只执行 download，不做 CNN／DMA MMIO | 首次控制读 |
| 4 控制 | ABI、状态、复位、时钟、DMA 状态 | 小规模 DMA |
| 5 传输 | 固定输入、参考输出、缓存所有权、有界清理 | 连续业务流 |

## Procedure

1. **冻结身份与旧现场**：记录 BIT／HWH 哈希、工具版本、当前进程和既有日志；保留旧候选，不在故障中同时改模型、接口和视频配置。
2. **分层检查运行环境**：分别检查普通用户、sudo 和 Jupyter 的 UID、组与环境变量。`No Devices Found` 先按权限／环境处理，不直接判定摄像头或 XRT 故障。
3. **解析而不下载**：核对 HWH 中目标 IP、物理地址、寄存器和时钟。地址或版本身份不符时停止。
4. **检查真实系统复位**：读取实际生成 BD／VHDL／复位 IP，核对每个复位的有效电平、常量、PLL lock 和外部来源。独立核测试台主动给对 reset 不覆盖本层。
5. **一次只跑一个硬件阶段**：metadata → load → control → DMA。每个阶段使用独立命令和 trace；危险调用前写 BEGIN，返回后写 COMPLETE。
6. **先控制后传输**：读取 ABI、输入规模、时钟、busy／reset 和 DMA 状态。未通过时不得用 DMA 继续“试试看”。
7. **检查 CMA 与缓存**：记录 before／during／after，区分可回收缓存、未释放缓冲和真正持续下降；单次低空闲值不等于泄漏。
8. **固定输入验证并清理**：比较参考输出，停止 DMA、禁用门控、释放缓冲和自有内核。短测通过不外推长期无泄漏。

## Common Mistakes

- 综合、布线或独立核仿真通过后就直接启动完整业务流。
- sudo 丢失环境变量后，反复重装运行时。
- 用 Python 计时器宣称 AXI 总线不会死锁；超时只有在轮询函数返回控制权后才有效。
- 故障恢复时同时修改多个层，导致修复无法归因。
- 看到 `session_clean=false` 就认定残留任务，或清掉不属于自己的 Jupyter 内核。

## Validation

成功证据必须与目标层一致：控制阶段至少得到预期 ABI／状态，DMA 阶段还需固定输入输出、事务计数和清理记录。任何阶段卡住，都报告最后一个 `BEGIN` 而非笼统“板端失败”。

参考实现与真实案例见 [references.md](references.md)；历史失败基线和应用检查见 [validation.md](validation.md)。
