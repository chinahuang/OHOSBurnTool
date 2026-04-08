# HiTool Flash Method (Hi3796CV300, U-Boot TFTP)

Observed from HiBurn.log during a reference flash session.

## U-Boot Network Setup (sent via serial COM1@115200)
```
setenv serverip 192.168.1.2      # PC IP
setenv ethaddr 00:b1:32:e8:23:b3 # Fixed MAC (avoids random MAC issues)
setenv ipaddr 192.168.1.0        # Board IP (uses .0, the network address)
setenv netmask 255.255.255.0
setenv gatewayip 192.168.1.1
setenv tftpdstp 69
```

## TFTP Load Address
- **0x2c000000** (DDR free region base)
- DDR free region: base=0x2C000000, size=0x80000000 (2GB)

## Small File Flash Sequence
```
mw.b 0x2c000000 0xFF <file_size_rounded>  # pre-fill with 0xFF
tftp 0x2c000000 <filename>
mmc write 0x0 0x2c000000 <start_block_hex> <block_count_hex>
```

## Large File Flash Sequence (HiTool original — uses unzip)
HiTool pre-splits large images into gzip-compressed parts:
- system.img (2048MB) → 4 parts: `system.img.part0.gz` ... `part3.gz`
- userdata.img (1400MB) → 3 parts

Each part flashed as:
```
tftp 0x2c000000 <partN.gz>
unzip 0x2c000000 0x56000000
mmc write 0x0 0x56000000 <start_blk> <blk_count>
```

> **Note:** HiSilicon U-Boot `unzip` has a memory corruption bug on this board
> (reported decompressed size varies per run; eMMC readback CRC mismatch).
> `auto_flash.py` bypasses this entirely — see [uboot_quirks.md](uboot_quirks.md).

## Transfer Speed (reference)
- TFTP: ~6.9 MiB/s (raw large file) / ~11 MiB/s (gzip, smaller transfer)
- MMC write: ~130-140 MB/s
