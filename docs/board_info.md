# Hi3796CV300 STB Hardware Details

## Connection
- Serial: COM1, 115200 baud, 8N1
- Ethernet: direct cable to PC
- PC IP: 192.168.1.2 (static, on the Ethernet interface)
- Board IP: 192.168.1.0 (HiTool uses this)

## U-Boot
- Version: 2022.07
- Prompt: `fastboot#`
- Boot delay: 30 seconds
- Ctrl+C to interrupt boot
- Random MAC on gmac0 and gmac1 per boot (fix with setenv ethaddr)
- Fixed MAC used by HiTool: 00:b1:32:e8:23:b3
- Uses gmac1 (ETH1) for network in U-Boot

## Memory
- DRAM: 6GB total, 1.8GB visible to boot CPU
- DDR free region: base=0x2C000000, size=0x80000000 (2GB)
- TFTP load address: 0x2c000000
- RAM end: ~0x72000000

## eMMC
- Chip: ~29GB
- Speed: 196 MHz, HS400ES, 8-bit bus
- Write speed: ~130-140 MB/s from U-Boot

## Partition Table (from flash_d.xml)
| Partition   | Start Block | Offset  |
|-------------|-------------|---------|
| fastboot    | 0x0         | 0MB     |
| bootargs    | 0x800       | 1MB     |
| sbl         | 0x1800      | 3MB     |
| trustedcore | 0x11800     | 35MB    |
| boot        | 0x16800     | 45MB    |
| system      | 0x194000    | 808MB   |
| vendor      | 0x676000    | 3308MB  |
| userdata    | 0x770000    | 3808MB  |

## OHOS System
- Shell prompt: `OHOS#`
- Network: eth0 (not eth1 like U-Boot)
- Network config: `ifconfig eth0 192.168.1.1 netmask 255.255.255.0`

## PDM (Partition Definition Manager)
HiSilicon proprietary partition table. `mmc part` in U-Boot returns
"Unknown partition table type 0" — Linux uses PDM to locate partitions,
not GPT/MBR.
