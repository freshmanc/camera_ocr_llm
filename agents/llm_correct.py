# -*- coding: utf-8 -*-
"""
LLM 严格纠错（Agent C）：仅拼写/错别字/标点/大小写/空格/法语缩合；
输出协议为 JSON：original, corrected, changes, confidence, language_hint。
支持截断、重试、温度与解析兜底。
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import config


@dataclass
class LLMResult:
    corrected_text: str
    success: bool
    time_ms: float
    error_msg: Optional[str] = None
    # Agent C 协议扩展（解析成功时填充）
    original: Optional[str] = None
    changes: Optional[List[Dict[str, str]]] = None
    confidence: Optional[float] = None
    language_hint: Optional[str] = None


# JSON 输出 schema 约束（用于校验）
def _parse_strict_json(content: str) -> Optional[Dict[str, Any]]:
    """从模型输出中提取 JSON 对象；允许前后有空白或少量杂文。"""
    content = (content or "").strip()
    if not content:
        return None
    # 尝试直接解析
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    # 尝试从 ```json ... ``` 或 { ... } 中抽取
    for pattern in (r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", r"(\{[\s\S]*\})"):
        m = re.search(pattern, content)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                continue
    # 找第一个 { 到最后一个 }
    start = content.find("{")
    end = content.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(content[start : end + 1])
        except json.JSONDecodeError:
            pass
    return None


def _validate_and_extract(data: Dict[str, Any], input_text: str) -> tuple[str, Optional[float], Optional[str], Optional[List]]:
    """校验必填字段并返回 (corrected, confidence, language_hint, changes)。"""
    corrected = data.get("corrected")
    if corrected is None or not isinstance(corrected, str):
        return input_text, None, None, None
    confidence = data.get("confidence")
    if isinstance(confidence, (int, float)):
        confidence = float(confidence)
    else:
        confidence = None
    language_hint = data.get("language_hint")
    if not isinstance(language_hint, str):
        language_hint = None
    changes = data.get("changes")
    if not isinstance(changes, list):
        changes = None
    return corrected.strip(), confidence, language_hint, changes


def _get_client_and_model() -> tuple[Any, str]:
    """返回 (OpenAI client, model_id)。根据 config 选择 OpenAI 或 LM Studio。"""
    from openai import OpenAI
    use_openai = getattr(config, "LLM_USE_OPENAI", False)
    api_key = getattr(config, "OPENAI_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
    if use_openai and api_key:
        client = OpenAI(api_key=api_key)  # 默认 base_url 为 OpenAI 官方
        model = (getattr(config, "LLM_MODEL", None) or "").strip() or "gpt-4o-mini"
        return client, model
    base_url = getattr(config, "LLM_BASE_URL", "http://127.0.0.1:1234/v1")
    client = OpenAI(base_url=base_url, api_key="lm-studio")
    model = getattr(config, "LLM_MODEL", None) or ""
    if not model:
        try:
            models = client.models.list(timeout=3)
            if models.data and len(models.data) > 0:
                model = models.data[0].id
        except Exception:
            pass
    return client, model or "default"


def _truncate_input(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[: max_chars].rstrip() + "..."


def _call_once(
    client: Any,
    model: str,
    user_content: str,
) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    """单次调用，返回 (parsed_json, error_msg)。"""
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": config.STRICT_CORRECTION_SYSTEM},
            {"role": "user", "content": user_content},
        ],
        max_tokens=getattr(config, "LLM_MAX_TOKENS", 512),
        temperature=getattr(config, "LLM_TEMPERATURE", 0.2),
        timeout=config.LLM_TIMEOUT_SEC,
    )
    content = (resp.choices[0].message.content or "").strip()
    parsed = _parse_strict_json(content)
    if parsed is None:
        return None, "JSON parse failed: no valid object in response"
    return parsed, None


def correct_with_llm(raw_text: str) -> LLMResult:
    """
    严格纠错：只允许拼写/错别字/标点/大小写/空格/法语缩合；
    要求模型返回 JSON，解析得到 corrected；失败则降级返回原文。
    """
    text = (raw_text or "").strip()
    if not text:
        return LLMResult(corrected_text=raw_text or "", success=True, time_ms=0.0)

    max_chars = getattr(config, "LLM_INPUT_MAX_CHARS", 800)
    truncated = _truncate_input(text, max_chars)
    user_content = getattr(
        config,
        "STRICT_CORRECTION_USER_TEMPLATE",
        "请对以下文本做严格纠错，并只输出 JSON，不要解释：\n\n{text}",
    ).format(text=truncated)

    t0 = time.perf_counter()
    retries = getattr(config, "LLM_RETRY_COUNT", 2)
    last_error: Optional[str] = None
    parsed: Optional[Dict[str, Any]] = None

    try:
        client, model = _get_client_and_model()

        for attempt in range(retries + 1):
            try:
                parsed, parse_err = _call_once(client, model, user_content)
                if parsed is not None:
                    corrected, confidence, language_hint, changes = _validate_and_extract(parsed, text)
                    elapsed_ms = (time.perf_counter() - t0) * 1000
                    return LLMResult(
                        corrected_text=corrected,
                        success=True,
                        time_ms=elapsed_ms,
                        original=text if text != truncated else None,
                        changes=changes,
                        confidence=confidence,
                        language_hint=language_hint,
                    )
                last_error = parse_err
            except Exception as e:
                last_error = str(e)
            if attempt < retries:
                time.sleep(0.3 * (attempt + 1))

        # 所有尝试后仍无合法 JSON：兜底返回原文
        elapsed_ms = (time.perf_counter() - t0) * 1000
        return LLMResult(
            corrected_text=text,
            success=False,
            time_ms=elapsed_ms,
            error_msg=last_error or "JSON parse failed after retries",
        )
    except Exception as e:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        return LLMResult(
            corrected_text=text,
            success=False,
            time_ms=elapsed_ms,
            error_msg=str(e),
        )
