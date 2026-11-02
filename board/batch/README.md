# 固定输入评估

本文件夹为本项目开发阶段的 CPU／PL 批量测试部分，用固定划分检查预测结果并测量各处理阶段耗时。

本目录执行 CPU／PL 样本遍历及独立计时，固定划分为 val 342 张、test 343 张。

```text
batch/
├── payload_manifest.json                    # 样本顺序、标签、输入 SHA、模型及工作点
├── board_batch.py                           # 精度遍历、预热与计时
├── batch_metrics.py                         # 概率、混淆矩阵、召回、特异度及 AUC
├── camera_input.py                          # 输入适配及打包
├── board_session.py                         # CNN 会话、设备检查和日志
├── board_accel.py                           # CNN 会话、设备检查和日志
├── board_trace.py                           # CNN 会话、设备检查和日志
└── batch_tools_manifest.json                # 脚本及载荷清单身份
```

`val_inputs.npz`、`test_inputs.npz` 由外部提供，需与清单 SHA 匹配。从发布根目录执行：

```bash
python3 board/stage_batch_inputs.py --source /path/to/prepared_inputs --split all
python3 board/run_batch.py --split all --verify-only
# CPU，需对应平台 ncnn：
python3 board/run_batch.py --backends fp32 kl eq --split test --warmup 30 --runs 300
# PL，需先加载位流并停止视频 DMA：
sudo env XILINX_XRT=/usr /usr/local/share/pynq-venv/bin/python3 board/run_batch.py --backends pl --split test --warmup 30 --runs 300
```

结果写入 `batch_run_<标识>/`，包含 `summary.json`、各后端结果 JSON、逐样本 CSV 和 logits。精度遍历与计时分开；计时从归一化 FP32 输入开始，分列适配、后端和后处理。test 为开发评估集。已有结果见 [results](../results/README.md)。
