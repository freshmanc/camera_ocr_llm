# -*- coding: utf-8 -*-
"""
视觉 LLM Agent：将摄像头截图送给视觉大模型，提取图中文字。
与 OCR 结果交叉验证（show_both / prefer_ocr / prefer_vision / merge_llm）。
"""
from __future__ import annotations

import base64
import io
import os
import time
from typing import Optional

import cv2  # type: ignore[import-untyped]
import numpy as np

import config


def _get_client_and_model():
    """与 llm_correct 一致；视觉模型名可用 VISION_LLM_MODEL 覆盖。"""
    from openai import OpenAI
    use_openai = getattr(config, "LLM_USE_OPENAI", False)
    api_key = getattr(config, "OPENAI_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
    if use_openai and api_key:
        client = OpenAI(api_key=api_key)
        model = (getattr(config, "VISION_LLM_MODEL", None) or getattr(config, "LLM_MODEL", "") or "gpt-4o").strip()
        return client, model
    base_url = getattr(config, "LLM_BASE_URL", "http://127.0.0.1:1234/v1")
    client = OpenAI(base_url=base_url, api_key="lm-studio")
    model = getattr(config, "VISION_LLM_MODEL", None) or getattr(config, "LLM_MODEL", "") or ""
    if not model:
        try:
            models = client.models.list(timeout=3)
            if models.data and len(models.data) > 0:
                model = models.data[0].id
        except Exception:
            pass
    return client, model or "default"


def _resize_if_needed(img_bgr: np.ndarray, max_long_edge: int) -> np.ndarray:
    h, w = img_bgr.shape[:2]
    if max_long_edge <= 0 or max(h, w) <= max_long_edge:
        return img_bgr
    scale = max_long_edge / max(h, w)
    nw, nh = int(w * scale), int(h * scale)
    return cv2.resize(img_bgr, (nw, nh), interpolation=cv2.INTER_LINEAR)


def _encode_image_to_base64_jpeg(img_bgr: np.ndarray, quality: int = 85) -> str:
    _, buf = cv2.imencode(".jpg", img_bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return base64.b64encode(buf.tobytes()).decode("ascii")


def extract_text_from_image(img_bgr: np.ndarray) -> str:
    """
    将 BGR 截图送给视觉 LLM，只输出图中可见文字，不解释。
    需要模型支持 vision（如 gpt-4o、Qwen-VL、LLaVA）。
    """
    if img_bgr is None or img_bgr.size == 0:
        return ""
    max_edge = getattr(config, "VISION_LLM_MAX_LONG_EDGE", 1024)
    img = _resize_if_needed(img_bgr, max_edge)
    b64 = _encode_image_to_base64_jpeg(img)
    data_uri = f"data:image/jpeg;base64,{b64}"

    prompt = "Extract all text visible in this image. Output only the raw text, preserving line breaks. No explanation, no translation."
    try:
        client, model = _get_client_and_model()
        timeout = getattr(config, "VISION_LLM_TIMEOUT_SEC", 20)
        t0 = time.perf_counter()
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_uri}},
                    ],
                }
            ],
            max_tokens=getattr(config, "VISION_LLM_MAX_TOKENS", 500),
            temperature=0.1,
            timeout=timeout,
        )
        out = (resp.choices[0].message.content or "").strip()
        return out or "(视觉模型未返回文字)"
    except Exception as e:
        return f"(视觉模型错误: {str(e)[:100]})"


def merge_ocr_and_vision_with_llm(ocr_text: str, vision_text: str) -> str:
    """
    用 LLM 将 OCR 与视觉模型的两段文字合并为一段最可信的文本（纠错、去重、补漏）。
    """
    if not ocr_text and not vision_text:
        return ""
    if not vision_text:
        return ocr_text.strip()
    if not ocr_text:
        return vision_text.strip()
    try:
        from openai import OpenAI
        use_openai = getattr(config, "LLM_USE_OPENAI", False)
        api_key = getattr(config, "OPENAI_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
        if use_openai and api_key:
            client = OpenAI(api_key=api_key)
            base_url = None
        else:
            base_url = getattr(config, "LLM_BASE_URL", "http://127.0.0.1:1234/v1")
            client = OpenAI(base_url=base_url, api_key="lm-studio")
        model = getattr(config, "LLM_MODEL", "") or ""
        sys_msg = "You are a text merger. Given two versions of text extracted from the same image (OCR and vision model), output a single best version: fix obvious errors, remove duplicates, keep all meaningful content. Output only the merged text, no explanation."
        user_msg = f"OCR result:\n{ocr_text}\n\nVision result:\n{vision_text}"
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": sys_msg}, {"role": "user", "content": user_msg}],
            max_tokens=getattr(config, "USER_CMD_MAX_TOKENS", 400),
            temperature=0.2,
            timeout=getattr(config, "USER_CMD_LLM_TIMEOUT_SEC", 20),
        )
        out = (resp.choices[0].message.content or "").strip()
        return out or ocr_text.strip()
    except Exception as e:
        return ocr_text.strip()  # 合并失败则退回 OCR
