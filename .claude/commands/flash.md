执行 Hi3796CV300 全自动烧录流程。

## 前置检查

首先确认 `config.py` 存在于项目根目录。若不存在，提示用户：
```
cp config.example.py config.py
# 然后编辑 config.py 填写 SERIAL_PORT、IMAGES_DIR 等
```

## 步骤

1. **检查串口占用**
   终止已知会占用串口的进程：
   ```bash
   taskkill /F /IM MoTTY.exe /IM putty.exe /IM Xshell.exe /IM HiTool.exe 2>/dev/null || true
   ```

2. **确认镜像目录**
   读取 `config.py` 中的 `IMAGES_DIR`，检查目录是否存在、`flash_d.xml` 是否存在。
   若缺失则终止并提示。

3. **运行烧录脚本**
   ```bash
   python auto_flash.py
   ```

4. **结果汇报**
   脚本完成后报告：成功/失败分区数、exit code、板子是否已 reset。
   若有失败分区，列出名称和错误信息。

$ARGUMENTS
