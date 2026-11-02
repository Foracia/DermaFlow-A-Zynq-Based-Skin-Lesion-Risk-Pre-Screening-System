# 视频逻辑与本地 IP

本文件夹为皮肤图像采集与风险预筛系统的视频处理模块，包含视频叠加逻辑和整机依赖的自定义 IP。

`rtl/axis_frame_overlay.v` 为视频流叠加逻辑。`ip/` 保存整机依赖的自定义 IP，各目录包含 `component.xml`、实现文件及打包资料。

构建脚本将 `ip/` 注册到 Vivado IP Catalog。整机连接见 [system](../system/README.md)，采集及显示程序见 [board/system_ui](../../board/system_ui/README.md)。
