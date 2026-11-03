# 仿真材料

本文件夹为本项目开发阶段的仿真验证部分，包含 CNN、图像质量门的测试台，以及输入和预期输出。

```text
sim/
├── cnn/                                     # CNN RTL 测试台、输入、参考及原仿真日志
├── cnn/hls/                                 # C 测试台及普通／边界二进制向量
├── quality_gate/                            # AXI 质量门与视频叠加测试台
├── tests/test_deploy_build.py               # 重建部署脚本的文件检查与恢复测试
├── tests/test_batch_paths.py                # 批量评估辅助路径测试
├── scripts/run_rtl.tcl                      # CNN RTL 编译、展开与仿真入口
└── scripts/run_csim.tcl                     # HLS C 仿真入口
```

在 Vivado／Vitis 2025.2 环境，从发布根目录执行：

```bash
vivado -mode batch -source sim/scripts/run_rtl.tcl
vitis-run --mode hls --tcl sim/scripts/run_csim.tcl
```

RTL 输出位于 `build/work/rtl/`，包含编译、展开与仿真日志；C 仿真输出位于 `build/work/csim/`。验证内容包括输出比较、多帧、握手、周期和超时。

上述入口覆盖 CNN，质量门测试台独立提供。测试台、输入、参考和仿真日志按各模块保存。

部署脚本的本地测试使用临时文件，可在 PC 上执行：

```bash
python -B -m unittest discover -s sim/tests -p test_deploy_build.py -v
```
