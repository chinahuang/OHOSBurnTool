# OHOSBurnTool

全自动烧录工具，通过串口 UART 控制 U-Boot，将完整固件包烧录至 Hi3796CV300 STB 开发板。无需 HiTool，支持 29 分区一键烧录。

## 环境要求

- Python 3.8+，安装依赖：`pip install pyserial`
- Windows（串口名 `COM*`）或 Linux（`/dev/ttyUSB*`）
- PC 网卡配置静态 IP `192.168.1.2`，与板子直连
- 固件镜像包（含 `flash_d.xml`）

## 快速开始

```bash
git clone https://github.com/chinahuang/OHOSBurnTool.git
cd OHOSBurnTool

# 1. 创建本地配置
cp config.example.py config.py
# 编辑 config.py，填写 SERIAL_PORT 和 IMAGES_DIR

# 2. 将板子连接串口和网线，上电

# 3. 运行烧录
python auto_flash.py
```

## 配置说明（config.py）

| 参数 | 说明 | 示例 |
|------|------|------|
| `SERIAL_PORT` | 串口号 | `'COM1'` / `'/dev/ttyUSB0'` |
| `PC_IP` | PC 网卡静态 IP | `'192.168.1.2'` |
| `IMAGES_DIR` | 固件镜像目录 | `r'D:\images'` |
| `FLASH_XML` | 分区表 XML 路径 | `r'D:\images\flash_d.xml'` |

其余参数（`BOARD_IP`、`BOARD_MAC`、`GATEWAY_IP`）通常无需修改。

## 烧录方式

| 文件大小 | 方式 |
|----------|------|
| > 15MB   | 原始分块 TFTP（672MB/块）→ mmc write，**绕过 U-Boot unzip** |
| ≤ 15MB   | mw.b 预填 0xFF → TFTP → mmc write |
| 无镜像   | mw.b 0xFF → mmc write（擦除） |

> U-Boot `unzip` 在此板存在内存损坏 bug（解压后数据 CRC 不匹配），
> 本工具完全绕过 unzip，直接传输原始镜像切片。详见 [docs/uboot_quirks.md](docs/uboot_quirks.md)。

## Claude Code Skill

本项目内置 `/flash` skill，在 Claude Code 中打开此目录后可直接使用：

```
/flash
```

自动完成：检查串口占用 → 验证镜像 → 运行烧录 → 汇报结果。

## 文档

- [docs/board_info.md](docs/board_info.md) — 硬件规格、内存布局、分区表
- [docs/flash_flow.md](docs/flash_flow.md) — 烧录流程与关键常量
- [docs/uboot_quirks.md](docs/uboot_quirks.md) — U-Boot 串口 quirks 及 unzip bug
- [docs/hitool_flash_method.md](docs/hitool_flash_method.md) — HiTool 原始方案参考

## 性能（实测）

- TFTP：~6.9 MiB/s（千兆直连，blksize=1468）
- MMC write：~139 MB/s
- 29 分区全量烧录：约 60–90 分钟
