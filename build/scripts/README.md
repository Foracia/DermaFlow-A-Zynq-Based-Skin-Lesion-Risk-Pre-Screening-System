# 构建脚本

本文件夹为皮肤图像采集与风险预筛系统的构建与打包脚本部分，分别用于目录检查、部署副本刷新、Vivado 工程创建和硬件综合实现。

所有命令从发布根目录执行。

```text
scripts/
├── check_layout.py                          # 目录名称、Python 语法及文件清单检查
├── prepare_runtime.py                       # UI 源码和配套运行文件
├── deploy_build.py                          # 重建位流部署、接口核对及清单刷新
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

完整构建后执行 `python build/scripts/deploy_build.py`，把 `build/output/` 的 BIT、HWH 接入板端运行目录。仅更新界面源码或启动配置时，执行 `prepare_runtime.py` 刷新配套文件；`check_layout.py` 同时检查启动配置的 SHA256 绑定。
