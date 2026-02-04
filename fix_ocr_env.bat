@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ========== 恢复可用的 PaddleOCR 2.7.0.3（解决 PDX 报错）==========
echo.
echo 正在使用 conda 环境 ocr310 执行...
call conda run -n ocr310 pip uninstall -y paddleocr paddlex 2>nul
call conda run -n ocr310 pip install paddleocr==2.7.0.3 --no-cache-dir
echo.
echo 完成。请运行：conda activate ocr310 后 python main.py
pause
