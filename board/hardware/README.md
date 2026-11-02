# 配套硬件与黄金事务

本文件夹为皮肤图像采集与风险预筛系统的 FPGA 硬件部署部分，提供整机位流、硬件接口描述、控制检查和固定输入验证程序。

`cnn_system.bit` 为 PL 配置，`cnn_system.hwh` 为配套接口元数据，`manifest.json` 记录文件 SHA。

```text
hardware/
├── cnn_system.bit                         # 当前整机 PL 配置
├── cnn_system.hwh                         # 配套 IP 地址与连接元数据
├── board_stage_probe.py                     # 把启动拆成 metadata（解析）、load（下载）、control（读寄存器）三阶段
├── board_accel.py                           # 文件检查或实际四帧黄金事务；用于功能诊断
├── board_trace.py                           # 在可能阻塞的调用前后记录 trace
├── input.hex                                # 四帧固定输入与低 16 位输出参考
├── expected.hex                             # 四帧固定输入与低 16 位输出参考
├── working_point.json                       # 冻结温度、阈值、正类索引及比较方式
├── preprocess_source.json                   # 预处理与模型接口来源
├── model_handoff_contract_source.json       # 预处理与模型接口来源
├── reset_contract.json                      # 复位和系统接口核对资料
├── hp1_init_reference.json                  # 复位和系统接口核对资料
└── manifest.json                            # 部署文件 SHA 清单
```

## 验证步骤

从发布根目录执行。文件检查：

```bash
python3 board/hardware/board_accel.py --root board/hardware
```

板端依次完成元数据解析、位流加载、控制检查和四帧事务：

```bash
sudo env XILINX_XRT=/usr /usr/local/share/pynq-venv/bin/python3 board/hardware/board_stage_probe.py --root board/hardware --phase metadata
sudo env XILINX_XRT=/usr /usr/local/share/pynq-venv/bin/python3 board/hardware/board_stage_probe.py --root board/hardware --phase load
sudo env XILINX_XRT=/usr /usr/local/share/pynq-venv/bin/python3 board/hardware/board_stage_probe.py --root board/hardware --phase control
sudo env XILINX_XRT=/usr /usr/local/share/pynq-venv/bin/python3 board/hardware/board_accel.py --root board/hardware --use-loaded --timeout 3
```

控制接口：CNN `0x43c90000`、DMA `0x40400000`、ABI `0x434e4e01`；CNN 80 MHz、PS FCLK0 100 MHz。一帧输入 16384 个 uint32，输出低 16 位为两个 signed INT8／5 位小数 logits。

阶段通过标记为 `PHASE_PASS`；四帧输出依次为 `1ce3 / ff00 / d12f / 1ce3`，完成状态为 `FOUR_FRAME_BOARD_GOLDEN_PASS`。结果及 trace 路径由程序打印。性能测量使用 [批处理入口](../batch/README.md)。
