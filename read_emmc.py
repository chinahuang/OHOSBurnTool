"""
从好板子（OHOS shell）读取 eMMC 关键分区原始数据，
base64 编码后传回 PC，用于修复坏板子

读取: fastboot(0M,1M) + bootargs(1M,1M) + sbl(3M,4M)
"""
import serial, time, sys, base64, hashlib, os

SERIAL_PORT = 'COM1'
BAUD = 115200

PARTITIONS_TO_READ = [
    # (name, device_path, size_bytes)
    ('fastboot',   '/dev/block/by-name/fastboot',   1*1024*1024),
    ('bootargs',   '/dev/block/by-name/bootargs',   1*1024*1024),
    ('sbl',        '/dev/block/by-name/sbl',        4*1024*1024),
    ('sblbak',     '/dev/block/by-name/sblbak',     4*1024*1024),
]
OUT_DIR = r'C:\work\hitools\images_from_board'
os.makedirs(OUT_DIR, exist_ok=True)

s = serial.Serial(SERIAL_PORT, BAUD, timeout=0.5)
s.read(s.in_waiting)

def cmd(c, wait=5):
    s.read(s.in_waiting)
    s.write((c + '\r\n').encode())
    time.sleep(0.3)
    out = b''
    deadline = time.time() + wait
    while time.time() < deadline:
        chunk = s.read(s.in_waiting or 256)
        if chunk:
            out += chunk
            if b'OHOS#' in out or b'fastboot#' in out:
                break
        time.sleep(0.1)
    return out.decode('utf-8', errors='replace')

# 确认 shell
s.write(b'\r\n')
time.sleep(1)
out = s.read(s.in_waiting or 512).decode('utf-8', errors='replace')
print(f'Board: {repr(out[-100:])}', flush=True)

if 'OHOS#' not in out and 'fastboot#' not in out:
    # 尝试 Ctrl+C
    for _ in range(3):
        s.write(b'\x03')
        time.sleep(0.3)
    s.write(b'\r\n')
    time.sleep(1)
    out = s.read(s.in_waiting or 512).decode('utf-8', errors='replace')
    print(f'After Ctrl+C: {repr(out[-100:])}', flush=True)

# 用 dd + base64 读分区
for name, dev, size in PARTITIONS_TO_READ:
    out_path = os.path.join(OUT_DIR, f'{name}.bin')
    print(f'\n读取 {name} ({size//1024}KB) from {dev}...', flush=True)

    # 先检查设备是否存在
    r = cmd(f'ls {dev}', wait=3)
    if 'No such' in r or dev not in r:
        # 尝试 by-name 路径
        r2 = cmd(f'ls /dev/block/mmcblk0* | head', wait=3)
        print(f'  设备检查: {r.strip()[:100]}', flush=True)
        print(f'  mmcblk: {r2.strip()[:100]}', flush=True)

    # dd 读取，输出到临时文件
    tmp = f'/tmp/{name}.bin'
    bs = 65536
    count = size // bs
    r = cmd(f'dd if={dev} of={tmp} bs={bs} count={count} 2>&1', wait=30)
    print(f'  dd: {r.strip()[-200:]}', flush=True)

    # base64 编码传输
    print(f'  传输中（base64）...', flush=True)
    r = cmd(f'wc -c {tmp}', wait=5)
    print(f'  文件大小: {r.strip()[:80]}', flush=True)

    # 用 base64 命令编码
    s.read(s.in_waiting)
    s.write(f'base64 {tmp}\r\n'.encode())
    time.sleep(0.5)

    b64_data = b''
    deadline = time.time() + 120
    while time.time() < deadline:
        chunk = s.read(s.in_waiting or 4096)
        if chunk:
            b64_data += chunk
            if b'OHOS#' in b64_data:
                break
        else:
            time.sleep(0.1)

    # 提取 base64 内容（去掉第一行命令回显和最后的提示符）
    lines = b64_data.decode('utf-8', errors='replace').split('\n')
    b64_lines = [l.strip() for l in lines if l.strip() and
                 all(c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=' for c in l.strip())]
    b64_str = ''.join(b64_lines)

    if b64_str:
        try:
            bin_data = base64.b64decode(b64_str)
            with open(out_path, 'wb') as f:
                f.write(bin_data)
            md5 = hashlib.md5(bin_data).hexdigest()
            print(f'  [OK] 保存到 {out_path} ({len(bin_data)} bytes, MD5={md5})', flush=True)
        except Exception as e:
            print(f'  [ERR] base64 解码失败: {e}', flush=True)
            print(f'  收到 {len(b64_data)} 字节', flush=True)
    else:
        print(f'  [ERR] 未收到有效 base64 数据', flush=True)

    # 清理临时文件
    cmd(f'rm -f {tmp}', wait=3)

print('\n完成！', flush=True)
s.close()
