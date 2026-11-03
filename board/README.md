# 板端部署与完整系统运行

本文件夹为皮肤图像采集与风险预筛系统的板端部署部分，提供当前整机位流、常驻应用、服务安装程序和开发测试入口。

## 运行平台

开发板为 PYNQ-Z2，芯片为 AMD/Xilinx Zynq-7000 XC7Z020（工程器件型号 `xc7z020clg400-1`）。软件环境为项目 PYNQ 3.1.1、Python 3.10.4。ARM 负责控制、界面和保存，PL 完成视频处理、质量统计及 CNN 加速。启动前连接相机和显示器。

## 文件结构

```text
board/
├── boot/                         # PYNQ 启动配置及安装说明
├── run_ui.py                     # 完整系统统一入口
├── run_batch.py                  # 固定输入开发测试入口
├── stage_batch_inputs.py         # 外部评估载荷复制及校验
│
├── hardware/                     # 当前整机位流及接口
│   ├── cnn_system.bit            # FPGA 配置
│   ├── cnn_system.hwh            # IP 地址及连接元数据
│   └── board_stage_probe.py       # 解析、加载和控制检查
│
├── system_ui/                    # 当前常驻应用
│   ├── board_terminal_service.py  # 启动、独占、应用生命周期与关机
│   ├── terminal_deploy.py         # 自启服务安装工具
│   ├── derm-terminal.service      # 服务配置示例
│   ├── system_app.py              # 优化后的采集、处理及显示
│   ├── board_system_ui.py         # 菜单和设备操作基础实现
│   └── system_result_store.py     # 图像、JSON、CSV 和导出保存
│
├── cpu/                          # CPU 对照模型及测试程序
├── batch/                        # 批量评估工具
└── results/                      # 模块测试与整机运行记录
```

## 前台运行

将完整工程放到板端并进入工程根目录。首次部署先按 [启动配置说明](boot/README.md)安装 `board/boot/boot.py` 并重启。随后停止已运行的同设备程序；已有服务使用以下命令停止并等待清理完成：

```bash
sudo systemctl stop derm-terminal.service
sudo systemctl stop derm-ui.service
```

依次核对文件并启动当前系统：

```bash
python3 board/run_ui.py
sudo env XILINX_XRT=/usr /usr/local/share/pynq-venv/bin/python3 board/run_ui.py --load --run
```

第一条仅检查文件，成功标记为 `SYSTEM_PACKAGE_VERIFIED_NO_HARDWARE_ACCESSED`。第二条执行独占和启动环境检查，下载一次位流并进入界面。启动时在 DMA 缓冲分配前执行一次缓存回收，运行期间不循环清缓存。

默认常驻运行，添加 `--seconds 120` 可执行限时运行。`--load` 表示本次加载配套位流；位流已正确加载时可省略该项，仅使用 `--run`。

## 操作与输出

KEY0／KEY1 切换菜单，KEY2 确认。功能页 KEY3 返回首页；首页 KEY3 进入关机确认，KEY2 确认，KEY3 取消。确认关机后，应用核对视频与 CNN DMA 清理、缓冲释放及记录保存，再请求系统关机。

默认结果目录为 `board/system_ui/runs/`，可用 `--output` 指定其他目录。运行回执、采集 PNG、`result.json` 及 `index.csv` 记录于该目录。

## 常驻服务安装

安装工具根据实际工程路径生成服务，并校验当前包的成功前台运行记录。先执行一次 `--seconds 120` 的前台运行，完成正常与三帧模式保存并安全退出，取得打印的 `system_session_*.json` 路径。

```bash
sudo env XILINX_XRT=/usr /usr/local/share/pynq-venv/bin/python3 board/system_ui/terminal_deploy.py --root "$PWD/board/hardware" --install --validated-run /path/to/system_session_record.json
sudo systemctl enable --now derm-terminal.service
sudo journalctl -u derm-terminal.service -n 30 --no-pager
```

将示例记录路径替换为当前包生成的成功记录。服务不依赖 PC、网络在线或 Jupyter 顺序启动；发生异常时不自动反复重启。安装器会保存原服务配置，`derm-terminal.service` 以 `/home/xilinx/dermaflow/` 为示例安装目录；安装器按工程实际位置生成服务。

安装器使用当前工程的成功前台会话记录生成服务配置。随包启动钩子位于 `board/boot/`，由终端程序统一加载整机位流。
