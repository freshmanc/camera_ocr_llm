# 视觉 LLM 与 OCR 交叉验证

用**本地/云端视觉大模型**对摄像头截图做“看图识字”，与 **OCR 结果**做交叉验证，提高识别可信度或补全漏检。

## 流程

1. 每轮做 OCR 时保存当前帧。
2. 当本轮得到**纠错后文本**（缓存命中或 LLM 纠错完成）时，若开启视觉 LLM：
   - 用保存的帧调用视觉模型，得到 **Vision 文本**。
   - 按 `CROSS_VALIDATE_MODE` 得到**交叉验证/合并结果**。
3. 主界面显示：`[纠错后]`、`[Vision LLM]`（若有）、`[交叉验证]`（若与纠错后不同）。

## 配置（config/__init__.py）

```python
ENABLE_VISION_LLM = False   # 改为 True 启用；需视觉模型（如 gpt-4o、Qwen-VL、LLaVA）
VISION_LLM_MODEL = ""       # 空则用 LLM_MODEL；OpenAI 可填 gpt-4o
VISION_LLM_TIMEOUT_SEC = 20
VISION_LLM_MAX_TOKENS = 500
VISION_LLM_MAX_LONG_EDGE = 1024   # 图长边上限，超则缩放

# 交叉验证模式
CROSS_VALIDATE_MODE = "show_both"   # show_both | prefer_ocr | prefer_vision | merge_llm
```

| 模式 | 含义 |
|------|------|
| **show_both** | 同时显示 OCR 纠错结果与 Vision 结果，不做合并 |
| **prefer_ocr** | 交叉结果采用 OCR 纠错文本 |
| **prefer_vision** | 交叉结果采用 Vision 文本 |
| **merge_llm** | 再调一次 LLM，把 OCR 与 Vision 两段合并成一段最佳文本 |

## 模型要求

- **OpenAI**：`VISION_LLM_MODEL` 或 `LLM_MODEL` 填支持图像的模型（如 `gpt-4o`）。
- **LM Studio**：需加载**视觉模型**（如 Qwen-VL、LLaVA 等），且 API 支持 multimodal（image + text）。若仅文本模型，调用会报错，可关闭 `ENABLE_VISION_LLM`。

## 实现位置

- **agents/vision_llm_agent.py**：`extract_text_from_image(img_bgr)`、`merge_ocr_and_vision_with_llm(ocr_text, vision_text)`。
- **worker.py**：存帧 `set_last_ocr_frame`；在缓存命中与 LLM 完成分支调用 `_run_vision_and_cross_validate`。
- **shared_state.py**：`_last_ocr_frame`、`_vision_llm_text`、`_cross_validated_text`；`DisplayResult` 增加对应字段。
- **overlay**：`build_display_lines` 增加 `[Vision LLM]`、`[交叉验证]` 行。
