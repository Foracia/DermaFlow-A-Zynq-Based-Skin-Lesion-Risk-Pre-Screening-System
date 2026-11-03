# 当前系统应用

本文件夹为皮肤图像采集与风险预筛系统的常驻运行部分，包含采集、质量筛选、CNN 调用、菜单显示、结果保存和安全关机。

```text
system_ui/
├── board_terminal_service.py    # 统一生命周期、独占检查、加载及关机请求
├── terminal_deploy.py           # 校验当前包运行记录并安装服务
├── terminal_binding.json        # 启动环境检查信息
├── derm-terminal.service        # 服务配置示例（安装时按实际路径生成）
├── system_app.py                # 优化后的采集与结果页流程
├── runtime_options.py           # 当前应用的输入处理和界面策略
├── runtime_timing.py            # 分阶段运行统计
├── board_system_ui.py           # 菜单、采集、设备操作和保存基础实现
├── ui_menu.py、ui_live.py        # 菜单与结果显示
├── ui_buttons.py、ui_font_*.json # 按键与字模
├── quality_gate_driver.py       # 质量统计硬件驱动
├── quality_equivalent.py        # 等价质量统计计算
├── frame_quality.py、reference.py # 保留帧复核及整数参考
├── camera_input.py              # 预处理及 PL 打包
├── board_session.py             # CNN 事务和缓冲管理
├── system_risk_core.py          # 单帧／三帧融合判定
├── system_result_store.py       # PNG、JSON、CSV 和 ZIP
└── *_manifest.json              # 当前应用及硬件身份
```

由工程根目录的 `board/run_ui.py` 调用 `board_terminal_service.py`。默认检查文件；`--load --run` 加载一次硬件并常驻运行；`--seconds` 设置可选时限，`--output` 指定结果目录。操作、关机及服务安装见上级 `board/README.md`。

源码位于 `src/system_ui/`，启动配置位于 [board/boot](../boot/README.md)。应用将运行摘要、采集图像和结果保存到磁盘。首页关机确认通过后，先完成 DMA 和缓冲清理再向 Linux 请求关机。
