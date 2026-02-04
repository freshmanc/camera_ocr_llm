# Agent B：OCR 提准（EasyOCR vs PaddleOCR）

## 1. EasyOCR vs PaddleOCR 对比

| 维度 | EasyOCR | PaddleOCR |
|------|---------|-----------|
| **实时性** | 单帧 200–800ms（GPU），适合 1–3 fps 抽帧 | 单帧 100–400ms（GPU），略快，适合 2–5 fps |
| **CPU/GPU** | 支持 GPU（CUDA），CPU 较慢 | 支持 GPU（CUDA），CPU 优化更好 |
| **模型大小** | 中英约 100–200MB（按语言包），首次下载慢 | 中英约 100MB+，按需下载检测/识别/方向分类 |
| **语言** | 80+ 语言，`ch_sim`+`en` 常用；法语 `fr` 需单独加 | 80+ 语言，中英法均支持，配置类似 |
| **中文效果** | 印刷体/清晰屏摄好，手写一般 | 中文场景优化多，表格/长文本往往更好 |
| **依赖** | PyTorch，安装简单 | PaddlePaddle，需对应 CUDA 版本 |
| **接口** | `readtext(image)` 直接返回框+文本+置信度 | `ocr(image, cls=True)` 返回按行结果，需解析 |
| **适用场景** | 快速接入、多语言、中英混合 | 中文为主、对准确率要求高、可接受复杂环境 |

**建议**：实时摄像头中英场景下，**默认 EasyOCR**（易集成、GPU 友好）；若中文准确率不足或需法语，可切 **PaddleOCR** 或启用 **EasyOCR 失败时 PaddleOCR 兜底**（`USE_PADDLE_OCR=True`）。

---

## 2. 提准策略与可落地参数

| 策略 | 说明 | 可落地参数建议 |
|------|------|----------------|
| **ROI** | 只对画面中央/指定区域做 OCR，减少干扰与算力 | 中心 60%–80% 宽高，或可配置 `(x, y, w, h)` |
| **去抖动** | 连续多帧结果一致或多数一致才输出，避免单帧误识 | 最近 N=3 帧投票，或“同一文本出现 ≥2 次”才更新显示 |
| **置信度阈值** | 低于阈值的框丢弃或单独标记 | 单框 `min_confidence=0.3`，整体平均 <0.2 视为无有效文本 |
| **去噪** | 预处理降噪提升可读性 | 高斯模糊 + 二值化（Otsu）或自适应阈值；弱光下可 CLAHE |
| **倾斜校正** | 轻微倾斜时先纠偏再识别 | 检测主要直线角度或用 Paddle/Easy 自带方向分类；OpenCV 旋转裁剪 |
| **文本行合并** | 多行按顺序合并为一段，避免顺序错乱 | 按 bbox 的 y 中心排序后再拼接；同行按 x 排序 |

---

## 3. 预处理流水线（推荐顺序）

1. **ROI 裁剪** → 只保留关注区域  
2. **缩放（可选）** → 短边 320–640 平衡速度与精度  
3. **去噪** → 高斯 + 二值化 或 自适应阈值  
4. **倾斜校正（可选）** → 小角度旋转  
5. **送入引擎** → EasyOCR / PaddleOCR  

---

## 4. 预处理代码片段（OpenCV）

以下已接入 `preprocess.py`，在 `run_ocr()` 前自动按 config 调用。

```python
# ROI：只保留中心 ratio 区域
def crop_roi_center(image, ratio=0.7):
    h, w = image.shape[:2]
    x = int(w * (1 - ratio) / 2)
    y = int(h * (1 - ratio) / 2)
    rw, rh = int(w * ratio), int(h * ratio)
    return image[y:y+rh, x:x+rw].copy()

# 去噪 + 二值化（自适应阈值 或 Otsu）
def denoise_and_binarize(image, blur_ksize=(3,3), use_adaptive=True):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, blur_ksize, 0)
    if use_adaptive:
        binary = cv2.adaptiveThreshold(blurred, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
    else:
        _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)

# 轻微倾斜校正（霍夫直线估计角度后旋转）
def correct_skew_small(image, max_angle_deg=5.0):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi/180, 80, minLineLength=50, maxLineGap=10)
    # ... 取角度中值，getRotationMatrix2D + warpAffine
```

**可落地参数**（见 `config.py`）：`OCR_USE_ROI=True`、`OCR_ROI_CENTER_RATIO=0.7`、`OCR_USE_PREPROCESS=True`、`OCR_PREPROCESS_BLUR_KSIZE=(3,3)`、`OCR_PREPROCESS_USE_ADAPTIVE_THRESH=True`、`OCR_USE_SKEW_CORRECTION=False`、`OCR_RESIZE_SHORT_EDGE=0`（320~640 可加速）。

---

## 5. 失败兜底策略

- **单次 OCR 异常**：返回 `OCRResult(success=False, error_msg=...)`，上游显示“OCR 异常”并保留上一帧显示结果。  
- **EasyOCR 失败且启用兜底**：自动重试一次 PaddleOCR（`USE_PADDLE_OCR=True`）。  
- **置信度极低或空文本**：单框低于 `OCR_MIN_BOX_CONFIDENCE` 丢弃；平均低于 `OCR_MIN_AVG_CONFIDENCE` 视为无有效文字，不触发 LLM。  
- **去抖动**：最近 `OCR_DEBOUNCE_HISTORY_LEN` 次中至少 `OCR_DEBOUNCE_MIN_VOTES` 次相同才作为稳定结果展示并送 LLM，减少闪烁与误识。  
- **预处理异常**：任一步失败则返回上一步或原图，不抛异常，保证引擎仍可运行。
