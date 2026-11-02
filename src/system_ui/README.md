# 系统软件源码

本文件夹为皮肤图像采集与风险预筛系统的系统软件源码部分，负责菜单交互、视频采集、质量检查、CNN 调用和结果保存。

本目录保存当前常驻应用源码，部署副本位于 [board/system_ui](../../board/system_ui/README.md)。模块职责见部署目录文件表。

源码更新后，从发布根目录执行：

```bash
python build/scripts/prepare_runtime.py
```

该操作复制 Python、字模、启动绑定和服务配置，并更新配套文件清单。`system_tools_manifest.json`、`video_tools_manifest.json` 记录程序和硬件绑定。
