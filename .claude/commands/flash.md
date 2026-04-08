执行 Hi3796CV300 全自动烧录流程。

## 步骤

1. **检查 COM1 占用**
   运行以下命令查找占用 COM1 的进程并终止：
   ```powershell
   Get-Process | Where-Object { $_.MainWindowTitle -match 'COM1|HiTool|MobaXterm' } | Stop-Process -Force
   ```
   同时用 taskkill 终止已知串口工具：MoTTY.exe、putty.exe、Xshell.exe、HiTool.exe。

2. **确认镜像目录**
   检查 `C:\work\hitools\images\` 是否存在 `flash_d.xml` 及各分区镜像文件。
   列出缺失的文件并提示用户，若 flash_d.xml 不存在则终止。

3. **运行烧录脚本**
   ```bash
   /c/ProgramData/anaconda3/python.exe c:/work/hitools/auto_flash.py
   ```
   在后台运行，持续输出进度。

4. **结果汇报**
   脚本完成后报告：成功/失败分区数、exit code、板子是否已 reset。
   若有失败分区，列出名称和错误信息。

$ARGUMENTS
