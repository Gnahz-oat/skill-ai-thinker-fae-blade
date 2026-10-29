---
name: ai-wb2-uart-ota
description: 用 `make ota` 给 Ai-WB2（BL602）做有线 UART 串口升级 —— 免按键、免 BOOT 引脚：PC 通过 UART0 把 FW 分区镜像写进**非活动 bank**，整包 MD5 校验通过后切 bank 复位。含运行条件逐条核对、命令与可配置项、成功判据与反例自证、以及实测踩过的坑（串口被抢、`-jN`、共享镜像缓存、失败后 5 s 归还窗口）。Use when 用户要 `make ota` / 串口升级 / UART OTA / 有线升级固件 / 排查 OTA 握手失败或升级后异常。
---

# `make ota` —— Ai-WB2 有线 UART OTA 使用方法

## 什么时候用

- 板子**已经在跑带 OTA 宿主的固件**，想不按 BOOT/RST 就换固件 → `make ota`
- 首次把 OTA 能力装进板子（或板子跑的是没有宿主的固件）→ 只能用 **`make flash`**（ISP，需要按 BOOT+RST）
- 无线 OTA（HTTP/云端下发）是另一套东西，见 `ota-generator`

三条最容易搞混的边界：

| 目标 | 走什么 | 要不要按键 |
|---|---|---|
| `make ota` | UART0 数据帧（宿主已就位） | **不用** |
| `make flash` | ISP/ROM 下载协议 | **要**：按住 BOOT → 点 RST → 先松 RST 再松 BOOT |
| `make ota-image` | 只生成镜像（离线） | 不碰板子 |

## 运行条件（缺一条就不工作，逐条核）

| # | 条件 | 判据 / 怎么核 |
|---|---|---|
| 1 | 芯片 **Ai-WB2(BL602)**，实测 flash **4 MB** | 4M 表下 `--query-only` 报 `inactive_capacity=1146880` |
| 2 | USB-TTL 接 **UART0**：GPIO16=TX、GPIO7=RX、共地 | `--query-only` 能读到 `chip_id` |
| 3 | 板子固件**含 OTA 宿主**（`CONFIG_UART_OTA_ENABLE=1`） | 启动日志有 `[OTA] host ready: active_bank=.. inactive_capacity=..`；没有就先用 `make flash` |
| 4 | 分区表 **双 bank 等长**（`partition_cfg_4M_uart_ota.toml`，各 `0x118000`=1120 KB） | `--query-only` 在 bank 0 与 1 下 `inactive_capacity` **相同** |
| 5 | 控制台波特率 **115200**（`bfl_main.c` 里的 2000000 在本 SDK 工程不生效） | 115200 下启动日志可读；2000000 下是乱码 |
| 6 | 上位机有 `python3` + `pyserial`，且串口节点在本机可见 | `ls /dev/ttyUSB*`（Windows 侧是 `COMx`） |
| 7 | 串口**同一时刻只有一个主动读者** | 报 `multiple access on port` 或 `SET_BAUD 无应答` = 被抢了。**升级前先在串口助手里停止监控** |
| 8 | CLI **不是**必需条件 | `CONFIG_SYS_AOS_CLI_ENABLE=0` 也能升级（宿主自己注册 ttyS0，实测通过） |

## 最快路径

```bash
cd applications/system/<你的工程>        # 例：uart_ota / hello_ota
export BL60X_SDK_PATH=<repo 根目录>

make                                     # 1) 编译（默认目标=只构建，不下发）
make ota-test                            # 2) 可选：x86 离线协议单测，不接板
make ota                                 # 3) 生成镜像 + 串口下发 + 切 bank + 复位
```

**成功判据（三件都要）**：

1. `make ota` **退出码 0**
2. 日志末尾出现 `✔ 升级成功 · 端到端 … s · 平均 … KB/s · 链路 921600 bps`
   （这行意味着**设备侧整包 MD5 比对通过**；不等就回 `NACK(MD5)`，且**不切 bank**）
3. 复位后设备能再次握手，且 `active_bank` **翻转**（0↔1）

> 交替升级两个工程时，第 i+1 次握手成功本身就证明第 i 次的固件真的启动起来了 ——
> 这是"来回压测"最强的自证手段，不需要额外仪器。
> 实测（2026-09-22，4M 板）：50 次交替 `hello_ota ↔ uart_ota` **50/50 通过**、
> 每轮 bank 都翻转、零重传/零握手重试，单次端到端 2.74–4.75 s（平均 4.63 s，含 make 与复位）。

## 命令与可覆盖变量

```bash
make ota                 # = ota-image + 串口下发（唯一会走串口升级的入口）
make ota-image           # 只生成 FW 分区镜像（离线，不接板）
make ota-check           # 只校验镜像，不开串口
make ota-test            # x86 上跑协议单测（不接板；项数随样本镜像块数变化）
make ota-doctor          # 接入自检：配置/接线/常驻性 + 板子分区表比对（退出码 2 = 只有提醒）
make flash               # ISP 烧录（4M 等长双 bank 表），需要按 BOOT+RST
make flash-2m            # 回到 SDK 原始的 2M 行为
make ota-help

make ota SERIAL_PORT=/dev/ttyUSB0        # 选串口（Windows 侧：COM10）
make ota CONFIG_UART_OTA_FAST_BAUD=0     # 本次不升速，全程 115200
make flash CONFIG_UART_OTA_PARTITION=2M  # 按 2M 表烧
make ota RETRIES=5 BAUD=115200           # 工具层的重传/基准速率
```

工具目录 `tools/axk_uart_ota/` 也有一套同名目标（`make image / check / upload / test / clean`）——
注意**没有** `make ota-upload` 这个目标，需要单跑下发就用工具层的 `make upload`。

可配置项（写在应用的 `proj_config.mk`，标"固件"的改完要重新 `make`）：

| 配置项 | 默认 | 影响 |
|---|---|---|
| `CONFIG_UART_OTA_ENABLE` | `1` | 固件；置 `0` = 完全不编入宿主（省约 10 KB），项目退化成普通应用 |
| `CONFIG_UART_OTA_AUTO_RESET` | `1` | 固件；切 bank 后是否自动复位。置 `0` 由 app 收尾，且库**上锁**拒绝下一次 OTA |
| `CONFIG_UART_OTA_SUSPEND_OTHERS` | `1` | 固件；升级期间挂起其余任务（保证 flash 互斥，推荐） |
| `CONFIG_UART_OTA_PARTITION` | `4M` | 工具；`4M` / `2M` 分区表 |
| `CONFIG_UART_OTA_FAST_BAUD` | `921600` | 工具；升速协商目标，`0` = 全程 115200（**控制台始终 115200**，只升数据段） |

## 判据要能自证，别只看"跑完了"

- **正例**：`make ota` 退出码 0 + `✔ 升级成功` + `active_bank` 翻转 + 下一轮握手成功
- **反例自证（证明判据不是橡皮图章）**：把 **host 声明的整包 MD5 故意改坏一位**（数据保持完好）
  → 设备必须在 END 阶段回 `NACK(MD5)` 且**不切 bank**。
  ⚠️ 注意：**改镜像文件本身测不出来** —— host 会把改坏后的数据重新算一遍 MD5 发过去，
  设备算出来一样，反而"匹配成功"并把坏镜像写进去。只有"数据/声明不一致"才测得到这道门。

## 常见坑（都是实测踩过的）

| 现象 | 原因 / 处理 |
|---|---|
| `设备未应答 SET_BAUD` / `BEGIN 超时` / `multiple access on port` | 有别的进程在**主动读**同一个 tty（串口助手监控 / 另一个上行工具实例）。升级前停掉监控 |
| 失败（NACK/超时）后**立刻**重试握手，报"设备没有回应 HELLO" | ✅ 不是板子卡死：宿主在 FAIL 态仍持有 UART0，要**连续 ≥5 s 收不到任何字节**才归还（`AXK_UOTA_IDLE_RELEASE_MS=5000`）。实测：拒绝后立刻握手无应答，停手约 4–8 s 即恢复。**停 5–10 s 再跑一次即可，别急着按 RST** |
| 每次第一次握手失败、第二次成功 | 接管瞬间帧首字节的历史问题（已修）；工具本身有 3 次重试，可自愈 |
| `make -jN` 报大量汇编错误（`.l` / CFI / `.size expression`） | `-save-temps=obj` 中间文件被并发写坏。`make clean` 后**串行** `make`，别加 `-j` |
| `make ota` 报成功，但板子跑的还是上一个工程 | 历史坑：镜像曾是**所有工程共享**的 `build/ota_image.bin`，make 按时间戳跳过重建。现已用 `FORCE` 强制重建（<1 s）。自查：日志里 `app :` 的固件名与镜像字节数必须对得上 |
| 升级后无线不通 | 下发的是裸 `app.bin` 而不是 `whole_img.bin` / `ota_image.bin`（`BLRFPARA` 区为空）。镜像开头必须是 `BFNP`，工具会挡 |
| 镜像写不进非活动 bank | FW 双 bank **不等长**（用了 SDK 默认 2M 表），换 `partition_cfg_*_uart_ota.toml` |
| 升级耗时在 5.4 / 6.4 s 两档跳 | 不是故障：2M 表双 bank 不等长，`BEGIN` 擦的是"非活动"那一半。4M 等长表 + 只擦镜像覆盖后恒为约 0.7 s |
| 日志里混进乱码 / 串口助手读到 OTA 帧字节 | 两者共读同一个 tty，属预期 |
| 脚本里报"串口被另一个监控者占着" | 工具会自己扫 `/proc` 找持有者并给 5 s 退出窗口；注意**串口助手的 WSL 分栏是按需开/读/关**，它不在 `/proc` 扫描范围内，但同样会抢应答帧 |

## 串口在 WSL / Windows 之间怎么摆

- 工具要打开的节点必须**在当前这一侧**：WSL 侧是 `/dev/ttyUSBx`，Windows 侧是 `COMx`
- 用 usbipd 搬家：`usbipd attach --wsl --busid <BUSID>` 给 WSL，`usbipd detach --busid <BUSID>` 给 Windows
- 被别的程序占着时 attach 会失败（`Device busy (exported)`）：先关掉那个程序；`usbipd bind --force` 需要管理员
- 抓启动日志用串口助手（SeaHi）；**升级期间两者不能同时读**

## 相关文件

- 例程与完整背景：`applications/system/uart_ota/README.md`（运行条件/协议/测量/排障）
- 组件接入与 API：`components/sys/axk_uart_ota/README.md`（一行 include + 一行 `host_start`）
- PC 侧工具与测试台：`tools/axk_uart_ota/`（`axk_ota_uploader.py`、`host_test/`、`axk_ota_doctor.py`）
