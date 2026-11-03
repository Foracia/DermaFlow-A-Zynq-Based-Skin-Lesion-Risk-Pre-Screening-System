# DermaFlow: A Zynq-Based Skin Lesion Risk Pre-Screening System

本项目是一个面向皮肤图像风险预筛的嵌入式采集与推理系统，基于 PYNQ-Z2 开发板实现，核心器件为 AMD/Xilinx Zynq-7000 XC7Z020（工程器件型号 `xc7z020clg400-1`）。ARM 处理器负责系统控制、按键界面和结果管理，FPGA 可编程逻辑负责视频处理、图像质量统计与 CNN 加速计算。

系统包含视频采集、质量门控、CNN 推理、交互显示和结果保存五个部分。采集图像通过质量检查后送入 CNN，系统显示风险判定并保存图像及结果。支持单帧判定，以及对三张合格图像分别推理后融合结果的三帧模式。

本 README 所在目录为工程根目录。模型与数据放在 `data/`，设计源码放在 `src/`，板端可运行文件放在 `board/`；仿真、构建、Skill 和报告材料分别放在同名目录。

## 目录规划

工程采用选题指南推荐的 `src/`、`sim/`、`build/`、`board/`、`data/`、`skill/`、`report/` 七个一级目录。各目录下按 CNN、视频、质量门和系统软件划分模块。其中，`src/` 保存源码，`board/` 保存可直接部署的程序与硬件配置；开发测试结果分别归入 `sim/`、`build/reports/` 和 `board/results/`。

## 项目结构

下图标出各模块、主要文件及其作用。CNN 生成的计算子模块和 ROM 数据集中保存在 `src/cnn/rtl/`。

```text
dermaflow/
├── README.md                              # 项目说明、模块位置及运行入口
├── requirements.txt                       # Python 依赖
├── LICENSE                                # 团队原创内容的 MIT 许可
├── third_party_notices.md                  # 第三方内容、位置与许可

├── src/                                   # 设计源码
│   ├── cnn/                               # CNN 模型定义与硬件实现
│   │   ├── training/                      # 模型定义及 ONNX 导出代码
│   │   │   ├── model_hybrid.py             # HybridDermCNN 模型结构
│   │   │   ├── model_derm.py               # CNN 基础结构及模型构造函数
│   │   │   ├── export_onnx.py              # 检查点加载、ONNX 导出与数值核对
│   │   │   └── prob_utils.py               # 概率计算辅助
│   │   ├── quantization/                  # 最终 PL 定点参数的量化与导出
│   │   │   ├── fixed_model.py              # 从训练模型生成固定点整数参数
│   │   │   ├── fixed_arithmetic.py         # 舍入、饱和及整数运算规则
│   │   │   └── export_parameters.py        # 导出参数并核对 HLS 权重
│   │   ├── hls/                           # CNN 的 HLS 实现
│   │   │   ├── core.cpp、core.h            # grouped_network 顶层及声明
│   │   │   ├── grouped.h、stem16.h         # 分组计算及首层并行计算
│   │   │   ├── weights.h                  # 固定权重常量
│   │   │   └── debug.h                    # 调试辅助定义
│   │   └── rtl/                           # 当前整机使用的 CNN RTL
│   │       ├── cnn_accel_axi.v             # AXI 寄存器与流接口包装
│   │       ├── grouped_network.v           # CNN 计算顶层
│   │       └── grouped_network_*           # 计算子模块及配套 ROM 初始化数据
│   ├── quality_gate/                      # 图像质量门
│   │   ├── rtl/                           # 统计核心、AXI 包装与整机连接
│   │   └── python/                        # 驱动、整数参考、采集与标定辅助
│   ├── video/                             # 视频通路
│   │   ├── rtl/axis_frame_overlay.v        # 视频流叠加逻辑
│   │   └── ip/                            # 视频自定义 IP 及 component.xml
│   ├── system/                            # 整机硬件工程
│   │   ├── system_bd.tcl                   # PS、视频、质量门、CNN 和 DMA 连接
│   │   └── constraints.xdc                 # 实现约束
│   └── system_ui/                         # 常驻系统应用、关机及服务安装源码

├── sim/                                   # 仿真与固定测试向量
│   ├── cnn/
│   │   ├── real_core_tb.sv                 # CNN RTL 与 AXI 包装测试台
│   │   ├── input.hex、expected.hex         # 四帧输入及输出原码参考
│   │   ├── simulate.log                    # 已有 RTL 仿真日志
│   │   └── hls/                           # C 测试台、普通与边界二进制向量
│   ├── quality_gate/                      # 质量门及视频叠加测试台
│   ├── tests/                             # 本地部署及路径衔接测试
│   │   ├── test_deploy_build.py            # 重建部署脚本测试
│   │   └── test_batch_paths.py             # 批量评估辅助路径测试
│   └── scripts/
│       ├── run_rtl.tcl                     # CNN RTL 仿真入口
│       └── run_csim.tcl                    # HLS C 仿真入口

├── build/                                 # 工程构建与实现报告
│   ├── scripts/
│   │   ├── create_project.tcl              # 创建 Vivado 工程
│   │   ├── build_system.tcl                # 整机综合、实现与位流生成
│   │   ├── synthesize_cnn.tcl              # 独立 CNN HLS 综合
│   │   ├── prepare_runtime.py              # 刷新系统软件部署副本及文件清单
│   │   ├── deploy_build.py                  # 重建位流部署、接口核对及清单刷新
│   │   └── check_layout.py                 # 发布目录、语法和清单检查
│   └── reports/
│       ├── cnn/                           # 独立 CNN 核的资源／时序报告
│       ├── system/                        # 当前整机的资源／时序／DRC／CDC 报告
│       └── pending/                       # 报告扩展目录

├── board/                                 # 板端部署与运行
│   ├── boot/                              # PYNQ 启动配置与安装说明
│   │   ├── boot.py                        # 项目统一管理 FPGA 配置加载
│   │   └── README.md                      # 首次安装、核对及重启步骤
│   ├── run_ui.py                          # 完整系统界面入口
│   ├── run_batch.py                       # CPU／PL 固定输入评估入口
│   ├── stage_batch_inputs.py              # 校验并复制外部评估载荷
│   ├── hardware/
│   │   ├── cnn_system.bit、cnn_system.hwh  # 配套位流与硬件接口元数据
│   │   ├── board_stage_probe.py            # metadata／load／control 分阶段检查
│   │   ├── board_accel.py                  # 四帧黄金事务检查
│   │   ├── input.hex、expected.hex         # 板端固定输入及输出参考
│   │   ├── working_point.json             # CNN 温度及判定阈值
│   │   ├── reset_contract.json             # 复位接口定义
│   │   └── manifest.json                   # 部署文件 SHA 清单
│   ├── system_ui/                         # 默认系统软件部署副本
│   │   ├── board_terminal_service.py       # 常驻入口、独占、启动和安全关机
│   │   ├── terminal_deploy.py              # 生成并安装自启服务
│   │   ├── derm-terminal.service           # systemd 服务配置
│   │   ├── system_app.py                   # 优化的采集、输入处理与结果页
│   │   ├── board_system_ui.py              # 菜单、采集与设备生命周期基础实现
│   │   ├── ui_menu.py、ui_live.py           # 菜单与结果显示
│   │   ├── ui_buttons.py                   # 按键处理
│   │   ├── camera_input.py                 # RGB 图像预处理与 PL 打包
│   │   ├── board_session.py                # CNN 事务与缓冲管理
│   │   ├── system_risk_core.py             # 单帧／三帧融合判定
│   │   └── system_result_store.py          # 图像、JSON、CSV 保存与导出
│   ├── cpu/                               # CPU baseline
│   │   ├── models/fp32/                    # FP32 的 model.param 与 model.bin
│   │   ├── models/kl/                      # KL INT8 的 model.param 与 model.bin
│   │   ├── models/eq/                      # EQ INT8 的 model.param 与 model.bin
│   │   ├── verify_ncnn.py                  # ncnn 推理与参考核对
│   │   ├── benchmark_pc.py                 # PC 单线程计时
│   │   ├── benchmark_ncnn.py               # ARM／Linux 计时
│   │   ├── golden/                        # 六张输入张量及图像
│   │   ├── references/                    # 各候选的参考 logits
│   │   └── interface/working_points.json   # FP32／KL／EQ 各自的工作点
│   ├── batch/                             # 固定划分遍历、指标计算与分阶段计时
│   └── results/                           # 原提交保留的验证资料
│       ├── golden/                        # 启动检查与黄金事务结果
│       ├── batch/                         # 343 张 PL 评估、预测与计时
│       ├── timing/                        # 独立计时原件及汇总
│       └── system_ui/                     # 实际采图、推理、保存和导出记录

├── data/                                  # 模型、输入定义与评估数据
│   ├── models/                            # CNN 模型本体及配套定义
│   │   ├── model.onnx                      # 已训练 CNN 的 ONNX 网络与权重
│   │   ├── checkpoint.pt                   # PyTorch 模型检查点
│   │   ├── training_config.json            # 模型结构及训练配置
│   │   ├── contract.json                   # 模型输入输出接口
│   │   ├── preprocess.json                 # 缩放、通道与归一化参数
│   │   ├── split.json                      # train／val／test 固定划分
│   │   ├── calibration_list.txt            # 298 张量化校准样本名单
│   │   └── pl_quantized/                   # 最终加速电路采用的定点模型参数
│   │       ├── parameters/                 # 11 份整数权重／偏置 NPY
│   │       ├── recipe.json                 # 各层精度与量化规则
│   │       └── quantization.json           # 参数格式、误差及累加范围
│   ├── golden/model/                      # PyTorch／ONNX 黄金输入与输出
│   ├── evaluation/cpu/                    # CPU 各候选指标及 PC／ARM 计时
│   ├── dataset/                           # 外部完整数据集目录
│   │   └── README.md                      # 数据来源、许可、划分及预处理
│   └── calibration/                       # 外部校准张量占位

├── skill/                                 # Agent Skill
│   ├── pynq-overlay-bringup/               # PYNQ 启动与排障
│   ├── hls-numerical-validation/           # HLS 数值验证
│   ├── fpga-resource-timing-optimization/  # FPGA 资源与时序优化
│   ├── heterogeneous-performance-evaluation/ # 异构性能测量
│   ├── quantized-model-evaluation/         # 量化模型评估
│   ├── engineering-experience-distillation/ # 工程经验整理
│   ├── agent-engineering-handoff/          # 智能体协作与交接
│   └── evidence_index.md                   # Skill 与工程证据的对应关系

└── report/                                 # 正式报告、复现说明与实测结果
    ├── technical_report.pdf               # 正式项目技术报告
    ├── reproduction.md                    # 完整系统的部署、操作与功能检查
    ├── measurements.md                    # 模型、CPU、PL 与整机测试结果
    ├── images/                            # 正式报告中的相关插图及表格
    └── collaboration/
        ├── workflow.md                    # 智能体工作流设计
        ├── task-packet.md                 # 任务包模板
        ├── evidence-scope.md              # 记录来源与验证范围
        └── cases/                         # 四个协作与纠错案例
```

## 正式报告与复现资料

| 内容 | 文件 |
|---|---|
| 完整项目设计、优化过程与结论 | [正式技术报告](report/technical_report.pdf) |
| 完整系统的环境准备、部署启动、按键操作与输出检查 | [系统复现说明](report/reproduction.md) |
| 模型评估、CPU 基线、PL 计时、资源时序及整机连续运行 | [测试与实测结果](report/measurements.md) |

## CNN 模型、量化与硬件实现

训练完成的 CNN 以两种形式提供：`checkpoint.pt` 保存 PyTorch 模型参数，供模型代码加载；`model.onnx` 保存导出的网络和权重，供转换与数值核对使用。模型结构代码位于 `src/cnn/training/`。

加速电路使用由该训练模型生成的固定点整数参数。量化规则、逐层参数及导出脚本现已一并提供，HLS 使用的打包权重保存在 `src/cnn/hls/weights.h`，综合后的计算逻辑保存在 `src/cnn/rtl/`。最终通过配套位流和 HWH 部署到板卡。

CPU baseline 单独提供 FP32、KL INT8、EQ INT8 三套 ncnn 模型，用于软件推理与性能对照；它们与 PL 固定点参数分别保存。

| 内容 | 文件位置 | 作用 |
|---|---|---|
| 模型定义与导出 | `src/cnn/training/` | 定义网络，并从检查点导出 ONNX |
| 已训练 CNN | `data/models/checkpoint.pt`、`model.onnx` | 保存训练结果及可转换的网络 |
| PL 定点模型参数 | `data/models/pl_quantized/` | 保存最终硬件采用的整数权重、偏置与精度规则 |
| PL 量化与导出脚本 | `src/cnn/quantization/` | 根据固定精度规则量化参数，导出并核对 HLS 权重 |
| CPU 对照模型 | `board/cpu/models/{fp32,kl,eq}/` | 每套包含 ncnn 结构文件和权重文件 |
| CNN 硬件源码 | `src/cnn/hls/`、`src/cnn/rtl/` | 实现固定点计算和 AXI 接口 |
| 整机硬件配置 | `board/hardware/cnn_system.bit`、`cnn_system.hwh` | 配置 FPGA 并向 PS 提供接口信息 |

## 完整系统的部署与启动

首次部署时，先按 [PYNQ 启动配置](board/boot/README.md)安装随包 `boot.py` 并重启，再执行以下系统启动命令。

运行平台为 PYNQ-Z2，芯片为 Zynq-7000 XC7Z020（`xc7z020clg400-1`），使用项目 PYNQ 3.1.1、Python 3.10.4 环境。相机和显示器需在启动前连接。将完整工程复制到板端并进入工程根目录，先停止占用视频及 DMA 的其他应用。

1. **检查部署文件**：

   ```bash
   python3 board/run_ui.py
   ```

2. **加载硬件并启动完整系统**：

   ```bash
   sudo env XILINX_XRT=/usr /usr/local/share/pynq-venv/bin/python3 board/run_ui.py --load --run
   ```

`board/run_ui.py` 调用 `board/system_ui/board_terminal_service.py`，完成文件核对、设备独占检查、一次位流加载及系统应用启动。省略 `--seconds` 时持续运行；可用 `--seconds 120` 执行限时前台运行。Python 路径对应项目镜像。

KEY0／KEY1 切换菜单，KEY2 确认。在功能页按 KEY3 返回；在首页按 KEY3 进入关机确认，KEY2 确认关机，KEY3 取消。确认关机后，应用先停止 DMA、释放缓冲并保存记录，再请求系统关机。

图像和运行记录默认写入 `board/system_ui/runs/`。常驻服务配置和显式安装步骤见 `board/README.md`；服务由安装程序根据实际路径生成。

## 开发测试与结果资料

以下为模型及电路开发阶段的验证工具，按各自目的独立执行。

| 测试任务 | 程序／材料 | 结果 |
|---|---|---|
| CPU 模型核对与计时 | `board/cpu/verify_ncnn.py`、`benchmark_pc.py`、`benchmark_ncnn.py` | 预测、参考误差、PC／ARM 计时 |
| PL 参数重建与核对 | `src/cnn/quantization/export_parameters.py` | 定点整数参数及 HLS 权重一致性 |
| 板端固定输入检查 | `board/hardware/board_stage_probe.py`、`board_accel.py` | 启动阶段及四帧黄金事务 |
| CPU／PL 固定划分评估 | `board/run_batch.py` | 逐样本指标及分阶段计时 |
| C／RTL 仿真 | `sim/scripts/run_csim.tcl`、`run_rtl.tcl` | 算法、输出与协议验证日志 |
| 硬件构建 | `build/scripts/build_system.tcl` | 整机位流、HWH 和实现报告 |
| 重建产物部署 | `build/scripts/deploy_build.py` | BIT／HWH 接入板端目录并刷新关联清单 |

验证资料位于 `board/results/` 和 `data/evaluation/`，综合与实现报告位于 `build/reports/`。完整数据集、校准张量和批量输入载荷由外部提供。

提交目录保留当前部署实现。第三方 IP、ncnn、模型及数据保留原有来源与许可证。

## 许可证

项目团队原创内容采用 [MIT License](LICENSE)。第三方代码、IP、模型依赖与数据保留原许可，具体范围见 [第三方内容与许可](third_party_notices.md)。
