@echo off
REM =================================================================
REM Windows批处理脚本: 激活专用环境并执行 cal.py
REM =================================================================

REM 环境激活
call conda activate comfyui_env
echo Batch: 虚拟环境已激活。

REM 执行cal.py
REM %~dp0cal.py 指的是与本.bat文件同目录下的cal.py
REM %* 是一个特殊变量，代表所有传递给此批处理文件的命令行参数
echo Batch: 准备执行 Python 脚本: %~dp0cal.py
python "%~dp0cal.py" %*

REM 停用环境
call conda deactivate
