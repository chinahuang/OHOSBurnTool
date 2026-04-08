"""
全自动烧录脚本 v3 - 原始分块 TFTP（绕过 U-Boot unzip）
流程：
  1. 检测板子状态（OHOS shell / fastboot# / 无响应）
  2. 若在 OHOS：reboot，等待 U-Boot
  3. Ctrl+C 进入 fastboot#
  4. 配置网络（固定 MAC，IP=192.168.1.0）
  5. 按文件大小选择烧录方式：
     - 大文件（>15MB）: 按 672MB 分块，原始 TFTP → mmc write（无 unzip）
     - 小文件（≤15MB）: mw.b 预填 → tftp → mmc write
     - 无文件分区: mw.b 0xFF → mmc write（擦除）
  6. 烧录完成 reset

关键参数（来自 HiBurn.log 实测）：
  - TFTP 加载地址：0x2c000000（DDR free region 起始）
  - 原始分块上限：672MB（0x2A000000），加载后最高地址 0x56000000 < RAM_END=0x72000000
  - 板子 IP：192.168.1.0
  - 固定 MAC：避免 U-Boot 随机 MAC 导致 ARP 失效
  - 绕过 U-Boot unzip：此板 U-Boot unzip 存在内存损坏 bug（报告大小随机偏差，
    eMMC 回读 CRC 不匹配），改用直接传输原始镜像切片。
"""
import serial, time, sys, os, threading, socket, struct
import xml.etree.ElementTree as ET, subprocess

# ── 配置 ──────────────────────────────────────────────────────────────────────
SERIAL_PORT  = 'COM1'
BAUD         = 115200
PC_IP        = '192.168.1.2'
BOARD_IP     = '192.168.1.0'           # HiTool 使用的板子 IP
BOARD_MAC    = '00:b1:32:e8:23:b3'    # 固定 MAC，避免随机 MAC 问题
GATEWAY_IP   = '192.168.1.1'
IMAGES_DIR   = r'C:\work\hitools\images'
FLASH_XML    = r'C:\work\hitools\images\flash_d.xml'

LOAD_ADDR    = 0x2c000000   # TFTP 下载到此地址（DDR free region 起始）
RAW_THRESHOLD = 15 * 1024 * 1024   # 超过此大小的文件使用原始分块流程
CHUNK_SIZE   = 0x2A000000           # 672MB，原始分块大小（加载后最高 0x56000000 < RAM_END=0x72000000）
ERASE_CHUNK  = 0x10000              # 擦除时单次 mmc write 块数（32MB）

# ── 解析分区表（含所有 Sel=1 分区，空 SelectFile = 待擦除） ────────────────────
def parse_flash_xml(xmlfile):
    tree = ET.parse(xmlfile)
    root = tree.getroot()
    parts = []
    for p in root.findall('Part'):
        if p.get('Sel', '0') != '1':
            continue
        name     = p.get('PartitionName', '')
        imgfile  = p.get('SelectFile', '').strip()
        start_mb = int(p.get('Start',  '0M').replace('M', ''))
        len_mb   = int(p.get('Length', '0M').replace('M', ''))
        parts.append({
            'name':   name,
            'img':    imgfile,
            'start':  start_mb * 2048,  # 512 字节块编号
            'length': len_mb  * 2048,
        })
    return parts

PARTITIONS = parse_flash_xml(FLASH_XML)

# ── 显示分区摘要 ───────────────────────────────────────────────────────────────
print('分区烧录计划:')
for p in PARTITIONS:
    img = p['img']
    if img and os.path.exists(os.path.join(IMAGES_DIR, img)):
        sz = os.path.getsize(os.path.join(IMAGES_DIR, img))
        if sz > RAW_THRESHOLD:
            n = (sz + CHUNK_SIZE - 1) // CHUNK_SIZE
            mode = f'原始分块({n}部分, {sz/1024/1024:.0f}MB)'
        else:
            mode = f'直接({sz/1024/1024:.1f}MB)'
    elif img:
        mode = '擦除(无文件)'
    else:
        mode = '擦除'
    print(f"  {p['name']:20s} {p['start']//2048:5d}MB  [{mode}]")
print()

# ── TFTP 服务器 ───────────────────────────────────────────────────────────────
_tftp_files = {}   # filename → (filepath, offset, length)  length=None 表示到文件末尾
_tftp_stop  = threading.Event()

def reg(filename, filepath, offset=0, length=None):
    """注册 TFTP 文件。offset/length 支持只传输文件的一个切片。"""
    _tftp_files[filename] = (filepath, offset, length)

def _handle_get(filepath, offset, length, client_addr, blksize, send_oack):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(30.0)
    sock.bind(('', 0))
    try:
        if send_oack:
            oack = b'\x00\x06' + b'blksize\x00' + str(blksize).encode() + b'\x00'
            sock.sendto(oack, client_addr)
            try:
                ack, _ = sock.recvfrom(512)
                op, bn = struct.unpack('!HH', ack[:4])
                if not (op == 4 and bn == 0):
                    return
            except socket.timeout:
                return
        blocknum = 1
        remain = length   # None = unlimited
        with open(filepath, 'rb') as f:
            f.seek(offset)
            while True:
                to_read = blksize if remain is None else min(blksize, remain)
                chunk = f.read(to_read)
                if remain is not None:
                    remain -= len(chunk)
                pkt = struct.pack('!HH', 3, blocknum & 0xFFFF) + chunk
                for retry in range(15):
                    sock.sendto(pkt, client_addr)
                    try:
                        ack, _ = sock.recvfrom(512)
                        op, bn = struct.unpack('!HH', ack[:4])
                        if op == 4 and bn == (blocknum & 0xFFFF):
                            break
                        if op == 5:
                            return
                    except socket.timeout:
                        pass
                else:
                    print(f'\n[TFTP] block {blocknum} 超时 15 次，放弃', flush=True)
                    return
                blocknum += 1
                if len(chunk) < blksize:
                    break
    except Exception as e:
        print(f'\n[TFTP] 错误: {e}', flush=True)
    finally:
        sock.close()

def _tftp_loop():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((PC_IP, 69))
    sock.settimeout(1.0)
    print(f'[TFTP] 服务器 {PC_IP}:69  就绪', flush=True)
    while not _tftp_stop.is_set():
        try:
            data, addr = sock.recvfrom(4096)
        except socket.timeout:
            continue
        if len(data) < 4 or struct.unpack('!H', data[:2])[0] != 1:
            continue
        parts    = data[2:].split(b'\x00')
        filename = parts[0].decode('utf-8', errors='replace')
        blksize  = 512
        send_oack = False
        for idx in range(2, len(parts)-1, 2):
            if parts[idx].decode('ascii', errors='').lower() == 'blksize':
                try:
                    blksize   = int(parts[idx+1])
                    send_oack = True
                except ValueError:
                    pass
        entry = _tftp_files.get(filename)
        if entry:
            filepath, offset, length = entry
            sz = length if length is not None else (os.path.getsize(filepath) - offset)
            print(f'\n[TFTP] << {filename}  {sz/1024/1024:.1f}MB  blksize={blksize}', flush=True)
            threading.Thread(target=_handle_get,
                             args=(filepath, offset, length, addr, blksize, send_oack),
                             daemon=True).start()
        else:
            sock.sendto(struct.pack('!HH', 5, 1) + b'File not found\x00', addr)
            print(f'\n[TFTP] 未找到: {filename}', flush=True)
    sock.close()

# ── 串口工具 ──────────────────────────────────────────────────────────────────
for proc in ['MoTTY.exe', 'putty.exe', 'Xshell.exe']:
    subprocess.run(['taskkill', '/F', '/IM', proc], capture_output=True)
time.sleep(0.3)

s = serial.Serial(SERIAL_PORT, BAUD, timeout=0.1)
s.read(s.in_waiting)

def drain_serial():
    """等待 500ms 让所有上一条命令的 UART 数据到达，然后一次性丢弃缓冲区。
    不打印丢弃的内容（它已经由上一个 fb() 打印过了）。
    500ms >> 任何 UART 帧在 115200bps 下的传输时间，足以确保所有数据就位。"""
    time.sleep(0.5)
    s.read(s.in_waiting)   # 丢弃，不打印

def ensure_prompt(timeout=30):
    """持续发 Ctrl+C + 回车直到看到 fastboot# 提示符。返回 True/False。"""
    buf      = b''
    deadline = time.time() + timeout
    while time.time() < deadline:
        s.write(b'\x03')       # Ctrl+C  中断正在进行的操作
        time.sleep(0.4)
        s.write(b'\r\n')
        time.sleep(0.2)
        d = s.read(s.in_waiting)
        if d:
            buf += d
            sys.stdout.buffer.write(d)
            sys.stdout.buffer.flush()
        if b'fastboot#' in buf:
            drain_serial()
            return True
    return False

def fb(cmd, wait=15, sentinel=None):
    """发送命令，等待命令特有的完成标志（sentinel）出现后返回。

    U-Boot readline 在接收命令字符时会做整行重绘（发送 \\rfastboot# <已输入字符>），
    因此不能用 fastboot# 作为完成信号——它会在命令执行前就出现。
    每种命令等待其特有的输出关键词：
      tftp      → 'Bytes transferred'
      mmc write → 'blocks written:'
      unzip     → 'Uncompressed size:'
      crc32     → '==>'
      ping      → 'alive'
    sentinel=None：命令无特有输出（mw.b / setenv / reset），固定等 wait 秒后 flush。
    """
    drain_serial()
    s.write((cmd + '\r').encode())

    if sentinel is None:
        time.sleep(wait)
        out = s.read(s.in_waiting)
        if out:
            sys.stdout.buffer.write(out)
            sys.stdout.buffer.flush()
        return out.decode('utf-8', errors='replace') if out else ''

    sentinel_b = sentinel.encode()
    out           = b''
    deadline      = time.time() + wait
    sentinel_pos  = -1   # sentinel 在 out 中首次出现的位置

    while time.time() < deadline:
        chunk = s.read(s.in_waiting or 256)
        if chunk:
            out += chunk
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()

        if sentinel_pos < 0 and sentinel_b in out:
            sentinel_pos = out.index(sentinel_b)
            # sentinel 触发后继续等待 fastboot# 出现，确认命令真正完成。
            # 将截止时间延伸最多 5s，足以覆盖速度行 + 提示符到达的时间。
            deadline = min(deadline, time.time() + 5)

        # 在 sentinel 出现之后的内容里找 fastboot#，说明命令已完成
        if sentinel_pos >= 0 and b'fastboot#' in out[sentinel_pos:]:
            break

        time.sleep(0.05)
    return out.decode('utf-8', errors='replace')

def setup_network():
    """配置 U-Boot 网络环境（模拟 HiTool）"""
    fb(f'setenv serverip {PC_IP}',        wait=0.5)
    fb(f'setenv ethaddr {BOARD_MAC}',     wait=0.5)
    fb(f'setenv ipaddr {BOARD_IP}',       wait=0.5)
    fb(f'setenv netmask 255.255.255.0',   wait=0.5)
    fb(f'setenv gatewayip {GATEWAY_IP}',  wait=0.5)
    fb(f'setenv tftpdstp 69',             wait=0.5)

def warmup_phy():
    """发送 ping 预热以太网 PHY，避免首次 TFTP 在 PHY 协商期间以极低速运行。
    即使 ping 失败，PHY 初始化也已完成，后续 TFTP 可立即以千兆速度传输。"""
    print('  [PHY预热] ping 192.168.1.2...', flush=True)
    out = fb('ping 192.168.1.2', wait=15, sentinel='alive')
    if 'is alive' in out and 'not alive' not in out:
        print('  [PHY预热] ping 成功', flush=True)
    else:
        print('  [PHY预热] ping 超时/失败（正常，PHY已初始化）', flush=True)

# ── 第一步：检测当前状态 ──────────────────────────────────────────────────────
print('=' * 60)
print('检测板子当前状态...')
s.write(b'\r\n')
time.sleep(1.5)
out = s.read(s.in_waiting or 512)
sys.stdout.buffer.write(out); sys.stdout.buffer.flush()

in_fastboot = False

if b'fastboot#' in out:
    print('\n[状态] 已在 fastboot# 模式', flush=True)
    in_fastboot = True
elif b'OHOS#' in out or b'/ #' in out:
    print('\n[状态] 在 OHOS shell，发送 reboot...', flush=True)
    s.read(s.in_waiting)
    s.write(b'reboot\r\n')
    time.sleep(1)
else:
    print('\n[状态] 不明，发送 Ctrl+C 尝试...', flush=True)
    for _ in range(5):
        s.write(b'\x03')
        time.sleep(0.2)
    s.write(b'\r\n')
    time.sleep(1)
    out2 = s.read(s.in_waiting or 512)
    sys.stdout.buffer.write(out2); sys.stdout.buffer.flush()
    if b'fastboot#' in out2:
        in_fastboot = True
    elif b'OHOS#' in out2 or b'/ #' in out2:
        print('\n[状态] OHOS shell，发送 reboot...', flush=True)
        s.read(s.in_waiting)
        s.write(b'reboot\r\n')
        time.sleep(1)
    else:
        print('\n[状态] 无响应，等待板子启动...', flush=True)

# ── 第二步：等待 U-Boot 并 Ctrl+C 进入 fastboot# ─────────────────────────────
if not in_fastboot:
    print('\n监听 U-Boot 启动序列（最多 120 秒）...', flush=True)
    buf = b''
    ctrlc = False
    deadline = time.time() + 120
    triggers = [b'miniboot', b'U-Boot', b'Autoboot', b'autoboot',
                b'Relocate', b'Hit any key', b'fastboot#']

    while time.time() < deadline:
        chunk = s.read(s.in_waiting or 64)
        if chunk:
            buf += chunk
            sys.stdout.buffer.write(chunk); sys.stdout.buffer.flush()
            buf = buf[-8192:]

        if not ctrlc and any(t in buf for t in triggers):
            print(f'\n[检测到启动序列] 开始发送 Ctrl+C...', flush=True)
            ctrlc = True

        if ctrlc:
            s.write(b'\x03')
            time.sleep(0.015)

        if b'fastboot#' in buf:
            print('\n[OK] 进入 fastboot# 模式！', flush=True)
            in_fastboot = True
            time.sleep(0.3)
            s.read(s.in_waiting)
            break
        time.sleep(0.005)

    if not in_fastboot:
        for _ in range(15):
            s.write(b'\r\n')
            time.sleep(0.5)
            out = s.read(s.in_waiting or 256)
            if b'fastboot#' in out:
                in_fastboot = True
                break
            if b'OHOS#' in out or b'/ #' in out:
                print('\n[状态] 检测到 OHOS shell，发 reboot 并重新等待...', flush=True)
                s.write(b'reboot\r\n')
                time.sleep(5)
                break

if not in_fastboot:
    print('\n[ERROR] 无法进入 fastboot# 模式，退出', flush=True)
    s.close()
    sys.exit(1)

print('\n[OK] 在 fastboot# 模式，开始烧录', flush=True)
print('=' * 60, flush=True)

# ── 第三步：启动 TFTP 服务器 ──────────────────────────────────────────────────
threading.Thread(target=_tftp_loop, daemon=True).start()
time.sleep(0.5)

# ── 第四步：配置网络 + PHY预热 ────────────────────────────────────────────────
print('\n配置网络...', flush=True)
setup_network()
warmup_phy()   # 初始化 PHY，使首次 TFTP 以千兆速度运行

# ── 烧录辅助函数 ──────────────────────────────────────────────────────────────
def tftp_wait(size_bytes):
    """TFTP 超时：按 5MB/s 保守估算"""
    return max(90, size_bytes // (5 * 1024 * 1024) + 60)

def mmc_wait(blk_count):
    """mmc write 超时：按 50MB/s 保守估算（保留余量）"""
    return max(30, blk_count * 512 // (50 * 1024 * 1024) + 30)

def do_plain(part, imgpath):
    """直接 TFTP 烧录（小文件）: mw.b 预填 → tftp → mmc write"""
    imgfile = os.path.basename(imgpath)
    imgsize = os.path.getsize(imgpath)
    blk_cnt = (imgsize + 511) // 512
    reg(imgfile, imgpath)

    # mw.b 预填 0xFF（大小对齐到 2KB）
    fill = (imgsize + 2047) & ~2047
    fb(f'mw.b {LOAD_ADDR:#x} 0xFF {fill:#x}', wait=max(10, fill // 50_000_000 + 5))

    print(f'  TFTP {imgfile}  ({imgsize/1024/1024:.2f}MB)...', flush=True)
    out = fb(f'tftp {LOAD_ADDR:#x} {imgfile}', wait=tftp_wait(imgsize),
             sentinel='Bytes transferred')
    if 'Bytes transferred' not in out:
        return False, 'TFTP 失败'

    out = fb(f'mmc write 0x0 {LOAD_ADDR:#x} {part["start"]:#x} {blk_cnt:#x}',
             wait=mmc_wait(blk_cnt), sentinel='blocks written:')
    if 'written: ok' not in out.lower():
        return False, 'mmc write 失败'
    return True, None

def do_raw_parts(part, imgpath):
    """原始分块烧录（大文件）：按 CHUNK_SIZE 切片 → tftp → mmc write（无 unzip）

    绕过 U-Boot unzip：此板 U-Boot unzip 存在内存损坏 bug，解压后数据 CRC 与源文件
    不符，且报告大小每次运行不同。改为直接 TFTP 传输原始镜像切片，消除 unzip 引入
    的数据损坏风险。
    """
    imgfile = os.path.basename(imgpath)
    imgsize = os.path.getsize(imgpath)
    write_blk = part['start']
    offset = 0
    part_num = 0
    while offset < imgsize:
        chunk_len  = min(CHUNK_SIZE, imgsize - offset)
        chunk_blks = (chunk_len + 511) // 512
        slice_name = f'{imgfile}.part{part_num}.raw'
        reg(slice_name, imgpath, offset, chunk_len)

        mb_start = offset // 1024 // 1024
        mb_end   = (offset + chunk_len) // 1024 // 1024
        print(f'  TFTP {slice_name}  (part{part_num}, {mb_start}~{mb_end}MB, {chunk_len/1024/1024:.1f}MB)...', flush=True)
        out = fb(f'tftp {LOAD_ADDR:#x} {slice_name}', wait=tftp_wait(chunk_len),
                 sentinel='Bytes transferred')
        if 'Bytes transferred' not in out:
            return False, f'TFTP 失败: {slice_name}'

        out = fb(f'mmc write 0x0 {LOAD_ADDR:#x} {write_blk:#x} {chunk_blks:#x}',
                 wait=mmc_wait(chunk_blks), sentinel='blocks written:')
        if 'written: ok' not in out.lower():
            return False, f'mmc write 失败 at block {write_blk:#x}'

        write_blk += chunk_blks
        offset    += chunk_len
        part_num  += 1
    return True, None

def do_erase(part):
    """用 0xFF 擦除整个分区（无镜像文件的分区）"""
    total_blk = part['length']
    if total_blk == 0:
        return True, None

    fill_blks  = min(ERASE_CHUNK, total_blk)
    fill_bytes = fill_blks * 512
    fb(f'mw.b {LOAD_ADDR:#x} 0xFF {fill_bytes:#x}',
       wait=max(10, fill_bytes // 50_000_000 + 5))

    written = 0
    while written < total_blk:
        this_cnt = min(ERASE_CHUNK, total_blk - written)
        # 最后一块如果比 fill_blks 小，需要重新填充
        if this_cnt < fill_blks:
            last_bytes = this_cnt * 512
            fb(f'mw.b {LOAD_ADDR:#x} 0xFF {last_bytes:#x}',
               wait=max(5, last_bytes // 50_000_000 + 5))
        dst = part['start'] + written
        out = fb(f'mmc write 0x0 {LOAD_ADDR:#x} {dst:#x} {this_cnt:#x}',
                 wait=mmc_wait(this_cnt), sentinel='blocks written:')
        if 'written: ok' not in out.lower():
            return False, f'擦除 mmc write 失败 at {dst:#x}'
        written += this_cnt
    return True, None

MAX_RETRY = 3   # 每个分区最多重试次数

# ── 第五步：烧录所有分区 ──────────────────────────────────────────────────────
total = len(PARTITIONS)
ok = fail = skip = 0

for i, part in enumerate(PARTITIONS, 1):
    name    = part['name']
    imgfile = part['img']

    print(f'\n{"="*60}', flush=True)
    print(f'[{i}/{total}] {name}  (起始 {part["start"]//2048}MB)', flush=True)

    ok_flag, err = False, '未处理'

    for attempt in range(MAX_RETRY):
        if attempt > 0:
            print(f'  [重试 {attempt}/{MAX_RETRY-1}] 恢复 fastboot# 状态...', flush=True)
            if not ensure_prompt(timeout=30):
                err = '无法恢复 fastboot# 提示符'
                break
            print(f'  [重试 {attempt}/{MAX_RETRY-1}] 开始...', flush=True)

        if imgfile:
            imgpath = os.path.join(IMAGES_DIR, imgfile)
            if os.path.exists(imgpath):
                imgsize = os.path.getsize(imgpath)
                if imgsize > RAW_THRESHOLD:
                    # ── 大文件：原始分块 TFTP ───────────────────────────────
                    n = (imgsize + CHUNK_SIZE - 1) // CHUNK_SIZE
                    if attempt == 0:
                        print(f'  模式: 原始分块  {imgfile}  ({imgsize/1024/1024:.0f}MB, {n}部分)', flush=True)
                    ok_flag, err = do_raw_parts(part, imgpath)
                else:
                    # ── 小文件：直接 TFTP ───────────────────────────────────
                    if attempt == 0:
                        print(f'  模式: 直接TFTP  {imgfile}  ({imgsize/1024/1024:.2f}MB)', flush=True)
                    ok_flag, err = do_plain(part, imgpath)
            else:
                # ── 文件缺失：擦除 ──────────────────────────────────────────
                if attempt == 0:
                    print(f'  文件不存在: {imgfile}，改为擦除  ({part["length"]*512//1024//1024}MB)', flush=True)
                ok_flag, err = do_erase(part)

        else:
            # ── 无 SelectFile：擦除 ────────────────────────────────────────
            if part['length'] > 0:
                if attempt == 0:
                    print(f'  模式: 擦除  ({part["length"]*512//1024//1024}MB)', flush=True)
                ok_flag, err = do_erase(part)
            else:
                print(f'  [SKIP] 分区大小为 0', flush=True)
                skip += 1
                break

        if ok_flag:
            break
        if attempt < MAX_RETRY - 1:
            print(f'  [失败] {err}，将重试...', flush=True)

    if ok_flag:
        print(f'  [OK] {name} 烧录/擦除完成', flush=True)
        ok += 1
    elif err != '未处理':
        print(f'  [FAIL] {name}: {err}', flush=True)
        fail += 1

    # fastboot 分区烧录后重新初始化网络（模拟 HiTool）
    if name == 'fastboot' and ok_flag:
        print('  [fastboot] 重新初始化网络...', flush=True)
        setup_network()
        warmup_phy()
        fb('getinfo ddrfree', wait=5, sentinel=None)

# ── 结果 ──────────────────────────────────────────────────────────────────────
print(f'\n{"="*60}')
print(f'烧录结果: 成功 {ok}  失败 {fail}  跳过 {skip}')

if fail == 0:
    print('\n所有分区烧录完成，执行 reset...', flush=True)
    fb('reset', wait=5)
else:
    print(f'\n[WARN] {fail} 个分区失败，请检查后手动处理', flush=True)

_tftp_stop.set()
s.close()
