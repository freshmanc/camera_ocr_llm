# 修法 2：Paddle 2.6.x + PaddleOCR 2.7.x 稳定环境（推荐长期使用）

Windows 上这套组合最稳，不易出现 executor/oneDNN/PIR、PDX 重复初始化等兼容性问题。**务必新建干净环境，不要用 base。**

---

## 推荐环境（Windows 最稳）

| 组件         | 版本              | 说明 |
|--------------|-------------------|------|
| **Python**   | **3.10**          | conda 创建时指定 |
| **PaddlePaddle** | **2.6.2**     | 先 CPU 跑通，避免 oneDNN 坑 |
| **PaddleOCR**    | **2.7.0.3**   | **经典版，不走 paddlex/PDX 那套** |

使用新版本 PaddleOCR（走 paddlex/PDX 链路）会带来「PDX has already been initialized」、modelscope/torch/shm.dll 等问题，请务必使用 **paddleocr==2.7.0.3**。

---

## 1. 新建干净 conda 环境

在 **Anaconda Prompt** 里执行：

```bash
conda create -n ocr310 python=3.10 -y
conda activate ocr310
```

---

## 2. 安装 Paddle 2.6.x（先 CPU 跑通）

```bash
pip install "paddlepaddle==2.6.2"
```

- 若 2.6.2 不可用，可试：`pip install "paddlepaddle>=2.6.0,<2.7"`
- 先 CPU 跑通最重要，GPU 以后再上（避免 CUDA/依赖折腾）。

---

## 3. 安装经典版 PaddleOCR 2.7.x（不依赖 PaddleX/modelscope/torch）

```bash
pip install "paddleocr==2.7.0.3"
```

此版本为「经典链路」，不依赖 paddlex，避免 Windows 上被 modelscope/torch 拖死。

---

## 4. 处理 numpy 兼容（若报 ABI 相关错）

Paddle 2.6 与 numpy 2.x 可能不兼容，若运行时报 numpy ABI 错误，执行：

```bash
pip install "numpy>=1.23,<2"
```

例如固定：`pip install numpy==1.26.4`

---

## 5. 安装本项目其余依赖

在项目根目录执行：

```bash
cd "c:\Users\Lenovo\Desktop\testing cursor\camera_ocr_llm"
pip install -r requirements-paddle26.txt
```

或手动安装：

```bash
pip install opencv-python Pillow numpy openai edge-tts langdetect
```

（numpy 若已在步骤 4 安装则不必重复；版本以步骤 4 为准。）

---

## 6. 验证

```bash
conda activate ocr310
python -c "from paddleocr import PaddleOCR; ocr=PaddleOCR(use_angle_cls=True, lang='ch'); print('OK')"
```

首次运行会下载模型，稍等片刻。只要打印 `OK`，说明环境正常。

---

## 7. 运行本项目

```bash
conda activate ocr310
cd "c:\Users\Lenovo\Desktop\testing cursor\camera_ocr_llm"
python main.py
```

---

## 版本对照（便于排查）

| 组件        | 建议版本           | 说明                    |
|-------------|--------------------|-------------------------|
| Python      | 3.10               | conda 创建时指定        |
| PaddlePaddle| 2.6.2（或 2.6.x）  | 先 CPU，避免 oneDNN 坑   |
| PaddleOCR   | 2.7.0.3            | 经典版，无 PaddleX 依赖  |
| numpy       | 1.26.x 或 &lt;2    | 与 Paddle 2.6 ABI 兼容  |

若之后要上 GPU，再在**同一环境**安装与 CUDA 匹配的 `paddlepaddle-gpu`，并把配置里 `PADDLE_OCR_FORCE_CPU` 改为 `False`。
