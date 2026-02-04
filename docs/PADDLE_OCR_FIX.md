# PaddleOCR AnalysisConfig / oneDNN 报错修复

**推荐长期方案**：按 **[修法 2：Paddle 2.6 + PaddleOCR 2.7 稳定环境](PADDLE_2.6_ENV.md)** 新建干净 conda 环境，可避免 AnalysisConfig、oneDNN/PIR、PaddleX 等坑。

---

约 90% 的 `'paddle.base.libpaddle.AnalysisConfig' object has no attribute...` 是 **版本不匹配** 导致。

## 一、先确认环境版本

在**运行本项目的同一个 conda 环境**里执行：

```bash
python -c "import paddle; import paddleocr; print('paddle', paddle.__version__); print('paddleocr', paddleocr.__version__)"
```

再执行：

```bash
python -c "import sys; print(sys.version)"
```

若 `import paddleocr` 就报错（例如出现 paddlex/modelscope/torch 或 shm.dll 等），说明是依赖或版本问题，需要按下面步骤干净重装。

---

## 二、最稳做法：干净重装（强烈推荐）

在该环境里依次执行：

```bash
pip uninstall -y paddlepaddle paddlepaddle-gpu paddleocr
pip cache purge
```

然后二选一：

### A) 先用 CPU 跑通（最快验证）

```bash
pip install -U paddlepaddle paddleocr
```

若安装的 PaddleOCR 较新、导入时出现 **paddlex / modelscope / torch** 或 **shm.dll** 报错，可改用不依赖 paddlex 的版本：

```bash
pip install -U paddlepaddle "paddleocr>=2.6,<2.8"
```

必要时指定具体版本（以 2.7 为例）：

```bash
pip install paddlepaddle==2.5.2 paddleocr==2.7.0
```

CPU 跑通后，界面就不会再「OCR异常」（至少能识别），先把系统跑通再考虑 GPU。

### B) 直接用 GPU 版（需与 CUDA 版本匹配）

到 [PaddlePaddle 安装页](https://www.paddlepaddle.org.cn/install/quick) 按你的 CUDA 版本选择对应安装命令，例如：

```bash
# 示例：CUDA 11.x
pip install paddlepaddle-gpu
pip install -U paddleocr
```

---

## 三、本项目配置

重装完成后，确保 `config/__init__.py` 中：

- `USE_EASYOCR = False`，`USE_PADDLE_OCR = True`（使用 PaddleOCR）
- `PADDLE_OCR_FORCE_CPU = True`（先用 CPU 可避免 AnalysisConfig 报错）

跑通后若想试 GPU，可改为 `PADDLE_OCR_FORCE_CPU = False`，再运行 `python main.py` 测试。
