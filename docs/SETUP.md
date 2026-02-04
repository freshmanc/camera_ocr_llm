# 安装与运行准备

按下面顺序做即可跑通：**摄像头 OCR + 本地 LLM 纠错 + 语音朗读 + 解释窗口 + 语音助手**。

---

## 一、推荐环境：conda + Python 3.10（ocr310）

在 **Anaconda Prompt** 或 PowerShell 中执行。

### 1. 创建并激活环境

```bash
conda create -n ocr310 python=3.10 -y
conda activate ocr310
```

若在 PowerShell 中 `conda activate` 报错，可跳过激活，后面用完整路径：  
`C:\Users\Lenovo\anaconda3\envs\ocr310\python.exe`。

### 2. 安装 Paddle 2.6 + PaddleOCR 2.7（OCR 稳定组合）

```bash
pip install "paddlepaddle==2.6.2"
pip install "paddleocr==2.7.0.3"
```

若出现 numpy 版本冲突，再执行：

```bash
pip install "numpy>=1.23,<2"
```

### 3. 安装本项目其余依赖

进入项目目录后安装：

```bash
cd "c:\Users\Lenovo\Desktop\testing cursor\camera_ocr_llm"
pip install -r requirements-paddle26.txt
```

### 4. 语音助手「语音输入」可选依赖（按 I 键可不装）

需要 **V 键语音输入**时再装：

```bash
pip install SpeechRecognition>=3.10.0
pip install pyaudio
```

Windows 上 `pyaudio` 若安装失败，可到 [这里](https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio) 下载对应 Python 版本的 whl 后：

```bash
pip install 下载的 PyAudio‑xxx.whl
```

---

## 二、验证

在项目目录下，用 ocr310 的 Python 执行：

```bash
C:\Users\Lenovo\anaconda3\envs\ocr310\python.exe -c "from paddleocr import PaddleOCR; ocr=PaddleOCR(use_angle_cls=True, lang='ch'); print('OCR OK')"
```

应看到 `OCR OK`（首次会下载模型，稍等）。

---

## 三、运行

```bash
cd "c:\Users\Lenovo\Desktop\testing cursor\camera_ocr_llm"
C:\Users\Lenovo\anaconda3\envs\ocr310\python.exe main.py
```

或先 `conda activate ocr310` 再：

```bash
cd "c:\Users\Lenovo\Desktop\testing cursor\camera_ocr_llm"
python main.py
```

---

## 四、运行前检查

| 项目 | 说明 |
|------|------|
| 摄像头 | 设备可用，且 `config/__init__.py` 里 `CAMERA_INDEX` 正确（默认 0） |
| LM Studio | 若用本地 LLM（纠错 + 语音助手），先打开 LM Studio，加载模型（如 qwen3-VL-8b-thinking），并开启「Local Server」 |
| 模型 id | `config/__init__.py` 中 `LLM_MODEL` 与 LM Studio 里显示的模型 id 一致 |

---

## 五、一键安装脚本（可选）

可将下面内容存为 `install_ocr310.bat`，在项目根目录双击或在命令行执行：

```batch
@echo off
call conda create -n ocr310 python=3.10 -y
call conda activate ocr310
pip install "paddlepaddle==2.6.2"
pip install "paddleocr==2.7.0.3"
pip install "numpy>=1.23,<2"
pip install -r requirements-paddle26.txt
echo 可选：pip install SpeechRecognition pyaudio
pause
```

（若 conda 未加入 PATH，需用 Anaconda Prompt 运行或改写成 conda 完整路径。）
