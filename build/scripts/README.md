# 构建脚本

本文件夹为皮肤图像采集与风险预筛系统的构建与打包脚本部分，分别用于目录检查、部署副本刷新、Vivado 工程创建和硬件综合实现。

所有命令从发布根目录执行。

```text
scripts/
├── check_layout.py                          # 目录名称、Python 语法及文件清单检查
├── prepare_runtime.py                       # UI 源码和配套运行文件
├── create_project.tcl                       # src/ 下源码、IP 与约束
├── build_system.tcl                         # 整机工程创建、综合及布局布线
└── synthesize_cnn.tcl                       # src/cnn/hls/ 的独立 HLS 综合
```

```bash
python build/scripts/check_layout.py
python build/scripts/prepare_runtime.py
vitis-run --mode hls --tcl build/scripts/synthesize_cnn.tcl
```

工程创建与整机构建命令见 [构建说明](../README.md)。各脚本按用途分别调用。
