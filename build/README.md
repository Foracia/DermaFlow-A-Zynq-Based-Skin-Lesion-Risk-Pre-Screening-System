# 构建工程

本文件夹为皮肤图像采集与风险预筛系统的硬件工程构建部分，包含工程创建、综合实现、部署文件生成及已有资源和时序报告。

工具环境：Vivado／Vitis 2025.2；目标器件：`xc7z020clg400-1`。

```text
build/
├── scripts/                                 # 检查、部署副本刷新、工程创建与构建脚本
├── reports/                                 # 当前 CNN 核与整机的资源和时序报告
├── work/                                    # 执行后生成的临时工程
└── output/                                  # 新整机位流、HWH 及实现报告
```

从发布根目录选择以下一种方式执行：

```bash
# 仅创建工程
vivado -mode batch -source build/scripts/create_project.tcl
# 完整构建（包含工程创建）
vivado -mode batch -source build/scripts/build_system.tcl
```

默认工程路径为 `build/work/system/`，已存在同名工程时创建脚本停止。完整输出包括 `system.bit`、`system.hwh` 和资源、时序、布线、DRC、CDC 报告。

## 将重建结果用于板端运行

构建结束后，在工程根目录执行：

```bash
python build/scripts/deploy_build.py
```

脚本核对目标器件、BIT 文件完整性及 HWH 中 CNN、DMA、质量门的接口地址，然后将 `build/output/system.bit` 和 `system.hwh` 分别部署为 `board/hardware/cnn_system.bit` 和 `cnn_system.hwh`，刷新硬件、界面与批处理清单，并执行部署文件检查。若刷新失败，恢复替换前的文件。

构建结果保存在其他目录时使用 `--source <构建输出目录>`。完成后将整个工程复制到板端，按[系统复现说明](../report/reproduction.md)配置启动钩子并运行系统。

`reports/` 保存综合与实现结果。仿真步骤见 [sim](../sim/README.md)。
