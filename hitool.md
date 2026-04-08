# auto_flash.py 设计说明

## 核心问题：U-Boot readline 行重绘

U-Boot readline 接收命令字符时会整行重绘，发送：
```
\rfastboot# c
\rfastboot# cm
\rfastboot# mmc
...
```
因此 `fastboot#` 会在命令**执行前**就出现在串口输出中，不能作为命令完成的信号。

## 解决方案：命令特有的完成信号（sentinel）

`fb()` 函数放弃等待 `fastboot#`，改为等待每种命令特有的输出关键词：

| 命令       | sentinel              | 原因 |
|------------|-----------------------|------|
| `tftp`     | `'Bytes transferred'` | TFTP完成固定打印 |
| `mmc write`| `'blocks written:'`   | 写入完成固定打印 |
| `unzip`    | `'Uncompressed size:'`| 解压完成固定打印 |
| `crc32`    | `'==>'`               | CRC完成固定打印 |
| `ping`     | `'alive'`             | 成功/失败都含此词 |
| `mw.b`     | `None`（固定等待）    | 无特有输出 |
| `setenv`   | `None`（固定等待）    | 无特有输出 |
| `reset`    | `None`（固定等待）    | 板子重启无输出 |

`sentinel=None` 时：`time.sleep(wait)` 后 flush 串口缓冲区。

## 关键串口发送规则

**必须只发 `\r`，不发 `\r\n`：**

```python
s.write((cmd + '\r').encode())   # 正确
s.write((cmd + '\r\n').encode()) # 错误！会导致命令双重执行
```

**原因：** U-Boot readline 在收到 `\r` 时立即执行命令。若命令执行时间较长（unzip、mmc write 大分区等），`\n` 会积压在 U-Boot 的 UART 输入缓冲区；命令完成回到 `fastboot#` 后，U-Boot 将 `\n` 当作第二次 Enter，重新执行上条命令。表现为同一命令输出两次（crc32 两次 `==>`、unzip 两次 `Uncompressed size:`），第二次输出在 drain_serial 0.5s 窗口之后到达，干扰下一条命令。

## fb() 函数签名

```python
def fb(cmd, wait=15, sentinel=None):
    ...
```

- `wait`：sentinel 模式下为超时秒数；None 模式下为固定等待秒数
- `drain_serial()`：每次发命令前先等 0.5s 并丢弃缓冲区，避免上一条命令残留干扰

## 烧录流程

### 小文件（≤15MB）
```
mw.b 0x2c000000 0xFF <fill>   # sentinel=None, 预填 0xFF
tftp 0x2c000000 <file>         # sentinel='Bytes transferred'
crc32 2c000000 <size>          # sentinel='==>'
mmc write 0x0 0x2c000000 ...  # sentinel='blocks written:'
```

### 大文件（>15MB，gz 流程）
```
tftp 0x2c000000 <file.gz>      # sentinel='Bytes transferred'
crc32 2c000000 <gz_size>       # sentinel='==>'
unzip 0x2c000000 0x46000000   # sentinel='Uncompressed size:'
mmc write 0x0 0x46000000 ...  # sentinel='blocks written:'
```
解压目标地址 `0x46000000`（非 `0x56000000`，避免 672MB 块溢出 RAM）。

### 擦除分区（无镜像文件）
```
mw.b 0x2c000000 0xFF <fill>   # sentinel=None
mmc write 0x0 0x2c000000 ...  # sentinel='blocks written:'
```

## 关键常量

| 常量 | 值 | 说明 |
|------|----|------|
| `LOAD_ADDR` | `0x2c000000` | TFTP/mw.b 加载地址 |
| `DECOMP_ADDR` | `0x46000000` | gz 解压目标地址 |
| `CHUNK_SIZE` | `0x2A000000`（672MB） | gz 分块大小 |
| `GZ_THRESHOLD` | 15MB | 大文件判断阈值 |
| `ERASE_CHUNK` | `0x10000`（32MB） | 擦除单次块数 |

## 成功判断逻辑

- `tftp`：检查 `'Bytes transferred' in out`
- `mmc write`：检查 `'written: ok' in out.lower()`
- `unzip`：用 `re.search(r'Uncompressed size:\s*(\d+)', out)` 取解压大小

## 网络初始化

```python
setenv serverip 192.168.1.2      # PC IP
setenv ethaddr 00:b1:32:e8:23:b3 # 固定 MAC（避免随机 MAC 导致 ARP 失效）
setenv ipaddr  192.168.1.0       # 板子 IP
setenv netmask 255.255.255.0
setenv gatewayip 192.168.1.1
setenv tftpdstp 69
```
每个 setenv 用 `wait=0.5`（无输出，sentinel=None）。

`fastboot` 分区烧录完成后需重新执行网络初始化（U-Boot 环境变量被覆盖）。
