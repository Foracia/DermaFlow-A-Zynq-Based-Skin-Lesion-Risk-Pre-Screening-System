# CPU baseline

本文件夹为皮肤图像采集与风险预筛系统的 CPU baseline 部分，提供在 PC 或 Zynq ARM 处理器上运行的 CNN 模型，以及预测核对和计时程序。

提供 FP32、INT8 KL 和 INT8 EQ 三套 ncnn 模型。各 `models/<候选>/` 包含网络结构 `model.param` 和权重 `model.bin`。

运行环境为对应平台的 ncnn `1.0.20260526`与 NumPy；图片处理使用 Pillow，PC 计时使用 psutil。ARM 运行使用板端 Python 环境及匹配架构的 ncnn。

```text
cpu/
├── models/                                 # ncnn 模型结构与权重
│   ├── fp32/                               # FP32：model.param、model.bin
│   ├── kl/                                 # KL INT8：model.param、model.bin
│   └── eq/                                 # EQ INT8：model.param、model.bin
├── verify_ncnn.py                           # 对已预处理 NCHW NPY 或图片执行推理、输出 logits 与判定；可与参考比较
├── benchmark_pc.py                          # PC 单线程、预备 Mat 的 API 计时
├── benchmark_ncnn.py                        # Linux／ARM 计时，支持额外图片管线阶段
├── golden/input.npy                         # 六张黄金输入与对应图片
├── golden/images/                           # 六张黄金输入与对应图片
├── references/*_logits.npy                  # FP32／KL／EQ 各自的参考 logits
├── interface/working_points.json            # 三种候选的温度与阈值权威入口；同目录其他 JSON 是来源记录
├── manifest.json                            # 发布文件哈希
├── sha256sums                               # 发布文件哈希
└── licenses/                                # ncnn 许可
```

## 功能核对

从发布根目录执行，以下使用 KL 模型与其冻结工作点：

```bash
python board/cpu/verify_ncnn.py --model-param board/cpu/models/kl/model.param --model-bin board/cpu/models/kl/model.bin --inputs board/cpu/golden/input.npy --reference board/cpu/references/kl_logits.npy --temperature 0.8904876816537481 --threshold 0.6976737641875307 --output-json kl_golden_result.json
```

输出六张样本的 logits、概率、预测及参考差异。FP32／EQ 使用各自的模型、参考和 `working_points.json` 参数。

## 计时

```bash
# PC：
python board/cpu/benchmark_pc.py --candidate kl --warmup 30 --runs 300 --output-json pc_kl_timing.json
# Linux／ARM（在板端匹配的 ncnn 环境中运行）：
python3 board/cpu/benchmark_ncnn.py --candidate kl --threads 1 --warmup 30 --runs 300 --output-json arm_kl_timing.json
```

`--candidate` 可选 fp32／kl／eq。结果 JSON 保存模型 SHA、环境、参考差异及计时分布。prepared-Mat API 阶段排除预处理、模型加载和 Mat 构造。已有结果见 [CPU 评估](../../data/evaluation/README.md)，完整划分入口见 [batch](../batch/README.md)。
