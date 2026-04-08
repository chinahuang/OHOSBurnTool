# ── 用户配置（复制此文件为 config.py 并按实际情况修改） ────────────────────────

# 串口
SERIAL_PORT = 'COM1'       # Windows: 'COM1'~'COM9' / Linux: '/dev/ttyUSB0'
BAUD        = 115200

# 网络（PC 与板子直连，PC 网卡配置静态 IP）
PC_IP       = '192.168.1.2'
BOARD_IP    = '192.168.1.0'
BOARD_MAC   = '00:b1:32:e8:23:b3'   # U-Boot setenv ethaddr，避免随机 MAC 导致 ARP 失效
GATEWAY_IP  = '192.168.1.1'

# 镜像目录（含 flash_d.xml 及所有 .img/.bin 文件）
IMAGES_DIR  = r'C:\work\hitools\images'
FLASH_XML   = r'C:\work\hitools\images\flash_d.xml'
