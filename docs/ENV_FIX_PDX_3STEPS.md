# 3 步解决「PDX has already been initialized」报错

**原因**：当前环境里的 PaddleOCR 走的是 **paddlex/PDX 链路**，进程内只允许初始化一次，代码无法绕过，只能换环境。

**做法**：用**经典版 PaddleOCR 2.7.0.3**（不走 PDX），按下面 3 步做一次即可。

---

## 1. 新建并激活 conda 环境

```bash
conda create -n ocr310 python=3.10 -y
conda activate ocr310
```

## 2. 安装推荐版本（不要用 pip 默认最新）

```bash
pip install paddlepaddle==2.6.2
pip install paddleocr==2.7.0.3
pip install "numpy>=1.23,<2"
```

## 3. 安装项目依赖并运行

```bash
cd 项目根目录
pip install -r requirements-paddle26.txt
python main.py
```

---

或用项目里的 **install_ocr310.bat** 一键完成 1、2 和部分依赖，再 `conda activate ocr310` 后运行 `python main.py`。

**验证**：在 ocr310 里执行  
`python -c "import paddleocr; print(paddleocr.__version__)"`  
应输出 `2.7.0.3`。若为 3.x 或其它，说明仍装错了，需在 ocr310 里重新执行第 2 步。
