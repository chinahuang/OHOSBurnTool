# auto_flash.py Flash Flow

## Overview

`auto_flash.py` fully automates flashing a Hi3796CV300 STB board via
serial UART to U-Boot, replicating HiTool behavior without requiring
HiTool to be running.

## Flash Modes

### Large file (>15MB) — `do_raw_parts()`
```
for each 672MB chunk of image:
    TFTP chunk → 0x2c000000
    mmc write 0x0 0x2c000000 <start_blk> <chunk_blks>
```
Bypasses U-Boot `unzip` entirely (see [uboot_quirks.md](uboot_quirks.md)).

### Small file (≤15MB) — `do_plain()`
```
mw.b 0x2c000000 0xFF <fill>      # pre-fill with 0xFF
tftp 0x2c000000 <file>
mmc write 0x0 0x2c000000 <start> <blks>
```

### No image file — `do_erase()`
```
mw.b 0x2c000000 0xFF <chunk>
mmc write 0x0 0x2c000000 <start> <chunk>   # repeated until full partition
```

## Key Constants

| Constant       | Value        | Purpose                          |
|----------------|--------------|----------------------------------|
| `LOAD_ADDR`    | 0x2c000000   | TFTP destination / mw.b base     |
| `CHUNK_SIZE`   | 0x2A000000   | 672MB raw chunk limit            |
| `RAW_THRESHOLD`| 15MB         | Size above which raw parts used  |
| `ERASE_CHUNK`  | 0x10000      | 32MB erase chunk (blocks)        |

## Network Setup
Sent before flashing (and re-sent after `fastboot` partition write):
```
setenv serverip 192.168.1.2
setenv ethaddr  00:b1:32:e8:23:b3
setenv ipaddr   192.168.1.0
setenv netmask  255.255.255.0
setenv gatewayip 192.168.1.1
setenv tftpdstp 69
```

## TFTP Server
Built-in UDP TFTP server in `auto_flash.py` (port 69).
Supports file slice registration: `reg(name, path, offset, length)`.
No external TFTP server required.

## Performance (measured)
- TFTP: ~6.9 MiB/s (raw 672MB chunk, blksize=1468)
- MMC write: ~139 MB/s
- Full 29-partition flash: ~60–90 minutes
