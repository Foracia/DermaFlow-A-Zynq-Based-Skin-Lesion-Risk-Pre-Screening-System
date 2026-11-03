# PYNQ 启动配置

本文件夹提供 DermaFlow 皮肤病变智能预筛终端的 PYNQ 启动钩子 `boot.py`。它记录系统启动信息，将 FPGA 配置加载统一交给项目的板端启动程序。

运行平台为 PYNQ-Z2，使用项目 PYNQ 3.1.1 镜像及 Python 3.10.4。首次部署工程时，在板端工程根目录执行：

```bash
# 备份板端原有启动配置，已有备份保持原样
sudo cp -n /boot/boot.py /boot/boot.py.backup

# 安装随包配置
sudo cp board/boot/boot.py /boot/boot.py

# 两行 SHA256 应相同
sha256sum board/boot/boot.py /boot/boot.py

# 重启使启动配置生效
sudo reboot
```

启动程序通过 `board/system_ui/terminal_binding.json` 核对此文件的 SHA256，因此安装时直接复制随包文件。完成重启后，按[板端部署说明](../README.md)运行 `board/run_ui.py --load --run`。

需要恢复原镜像启动行为时，可将 `/boot/boot.py.backup` 复制回 `/boot/boot.py` 后重启。系统日常启动与常驻服务由 `board/system_ui/` 中的程序管理。
