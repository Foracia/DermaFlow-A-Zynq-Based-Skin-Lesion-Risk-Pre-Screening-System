# 固定输入评估

本文件夹为本项目开发阶段的 CPU／PL 批量测试部分，用固定划分检查预测结果并测量各处理阶段耗时。

本目录执行 CPU／PL 样本遍历及独立计时，固定划分为 val 342 张、test 343 张。

```text
batch/
├── payload_manifest.json                    # 样本顺序、标签、输入 SHA、模型及工作点
├── board_batch.py                           # 精度遍历、预热与计时
├── batch_metrics.py                         # 分类指标及 HLS 开发样本辅助命令
├── dataset_io.py                            # 外部图像读取、固定划分及预处理
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

HLS 开发样本准备使用随包黄金输入、`data/models/` 的划分与预处理，以及外部图像目录。在具备 NumPy、Pillow 和 ONNX Runtime 的开发环境中执行：

```bash
python board/batch/batch_metrics.py prepare --image-root /path/to/images
```

`/path/to/images` 应直接包含 `split.json` 中记录的相对图像路径；默认位置为 `data/dataset/`。生成文件写入 `build/output/native_evaluation/`，其中 `fixtures/` 保存 6 个黄金样本和 342 个验证样本的辅助输入与参考。CPU／PL 常规批量评估使用上面的 `board/run_batch.py` 命令。
