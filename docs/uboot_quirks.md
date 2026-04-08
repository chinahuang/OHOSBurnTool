# U-Boot Serial Quirks (Hi3796CV300)

## Quirk 1: `\r\n` causes double command execution

**Symptom:** Sending `cmd\r\n` causes U-Boot to execute the command twice.
The second execution's output arrives after drain_serial()'s 0.5s window,
contaminating the next command's sentinel detection.

**Root cause:** U-Boot readline executes immediately on `\r`. During long
commands (mmc write, unzip, crc32 on large files), the `\n` queues in the
UART input buffer. When the command finishes and the prompt returns,
U-Boot processes the queued `\n` as a second Enter, re-executing the
previous command.

**Fix:**
```python
s.write((cmd + '\r').encode())   # correct — \r only
s.write((cmd + '\r\n').encode()) # WRONG — causes double execution
```

**Scope:** Only affects long-running commands (>0.5s). Short commands
complete before `\n` is processed.

---

## Quirk 2: `fastboot#` cannot be used as command completion signal

**Symptom:** U-Boot readline redraws the whole line as characters are
received, sending `\rfastboot# <chars_typed_so_far>`. Waiting for
`fastboot#` fires before the command even executes.

**Fix:** Each command waits for its own unique output keyword (sentinel):

| Command    | Sentinel              |
|------------|-----------------------|
| `tftp`     | `'Bytes transferred'` |
| `mmc write`| `'blocks written:'`   |
| `unzip`    | `'Uncompressed size:'`|
| `ping`     | `'alive'`             |
| `mw.b` / `setenv` / `reset` | `None` (fixed sleep) |

After sentinel fires, continue reading until `fastboot#` appears at a
position after the sentinel — confirms the command truly completed.

---

## Quirk 3: U-Boot `unzip` memory corruption bug

**Symptom:** `unzip 0x2c000000 0x46000000` produces data that does not
match the source image. The reported decompressed size varies per run
(e.g., 704,643,072 actual vs 704,643,151 / 704,643,142 reported).
eMMC readback CRC mismatch confirmed. Results in ext4 directory block
checksum failures → `EXT4-fs error: checksumming directory block` →
`EBADMSG` in execve → kernel panic / boot loop.

**Root cause:** Board-specific U-Boot firmware bug; not fixable from
software.

**Fix:** Bypass `unzip` entirely. `auto_flash.py` uses `do_raw_parts()`:
- TFTP server serves raw file slices (offset + length)
- Files are split into 672MB (0x2A000000) chunks
- Each chunk: `tftp 0x2c000000 <slice>` → `mmc write` directly
- No decompression step

**Memory layout for raw chunks:**
```
LOAD_ADDR  = 0x2C000000
chunk size ≤ 0x2A000000 (672MB)
max address = 0x56000000 < RAM_END ≈ 0x72000000  ✓
```
