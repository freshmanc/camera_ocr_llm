@echo off
chcp 65001 >nul
echo ========== 摄像头 OCR + 语音助手 环境安装 ==========
echo.

call conda create -n ocr310 python=3.10 -y
if errorlevel 1 (
    echo [提示] 若 ocr310 已存在可忽略上句报错，继续执行下面步骤。
    echo.
)

echo.
echo 使用 ocr310 环境安装 Paddle 与 PaddleOCR（固定版本，禁止升级）...
call conda run -n ocr310 pip uninstall -y paddleocr paddlex 2>nul
call conda run -n ocr310 pip install "paddlepaddle==2.6.2" --no-cache-dir
call conda run -n ocr310 pip install "paddleocr==2.7.0.3" --no-cache-dir
call conda run -n ocr310 pip install "numpy>=1.23,<2"

echo.
echo 安装项目依赖（opencv, openai, edge-tts 等）...
cd /d "%~dp0"
call conda run -n ocr310 pip install -r requirements-paddle26.txt

echo.
echo 可选：语音助手 V 键语音输入（SpeechRecognition + pyaudio）...
call conda run -n ocr310 pip install SpeechRecognition
call conda run -n ocr310 pip install pyaudio 2>nul
if errorlevel 1 (
    echo [可选] pyaudio 安装失败时，可用 I 键文字输入；或从 https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio 下载 whl 安装
)

echo.
echo ========== 安装完成 ==========
echo 运行方式：conda activate ocr310 后执行 python main.py
echo 或：conda run -n ocr310 python main.py
echo.
pause
