# -*- coding: utf-8 -*-
"""
用户指令 Agent：根据用户按键对当前识别内容执行「翻译 / 读音 / 例句」，
结果写入解释窗口；「朗读」由 worker 直接调 TTS。
使用与纠错相同的 LLM 端点（LM Studio / OpenAI），不同 prompt。
"""
from __future__ import annotations

import os
import time
from typing import Optional

import config


def _get_client_and_model():
    """与 llm_correct 一致的 client/model。"""
    from openai import OpenAI
    use_openai = getattr(config, "LLM_USE_OPENAI", False)
    api_key = getattr(config, "OPENAI_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
    if use_openai and api_key:
        client = OpenAI(api_key=api_key)
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


def _truncate(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


def translate_with_llm(text: str) -> str:
    """将当前识别内容翻译为目标语言（config.USER_CMD_TRANSLATE_TARGET）。"""
    text = _truncate((text or "").strip(), getattr(config, "USER_CMD_INPUT_MAX_CHARS", 400))
    if not text:
        return "(无内容)"
    target = getattr(config, "USER_CMD_TRANSLATE_TARGET", "zh")
    target_name = "简体中文" if target == "zh" else "英文"
    sys_msg = f"你只做翻译。把用户给的一段文字翻译成{target_name}，只输出译文，不要解释、不要序号。"
    user_msg = f"请将以下内容翻译成{target_name}：\n\n{text}"
    try:
        client, model = _get_client_and_model()
        t0 = time.perf_counter()
        timeout = getattr(config, "USER_CMD_LLM_TIMEOUT_SEC", 20)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": sys_msg}, {"role": "user", "content": user_msg}],
            max_tokens=getattr(config, "USER_CMD_MAX_TOKENS", 350),
            temperature=0.2,
            timeout=timeout,
        )
        out = (resp.choices[0].message.content or "").strip()
        return out or "(翻译无输出)"
    except Exception as e:
        return f"(翻译失败: {str(e)[:80]})"


def pronunciation_with_llm(text: str) -> str:
    """给出读音：中文给拼音，英文/法文给音标或发音说明。只输出读音，不解释。"""
    text = _truncate((text or "").strip(), getattr(config, "USER_CMD_INPUT_MAX_CHARS", 400))
    if not text:
        return "(无内容)"
    sys_msg = "你只输出读音。规则：中文用拼音标注（可带声调）；英文/法文用音标或简明发音说明。只输出读音本身，不要解释、不要例句。多词/多字用空格分隔。"
    user_msg = f"请给出以下内容的读音：\n\n{text}"
    try:
        client, model = _get_client_and_model()
        timeout = getattr(config, "USER_CMD_LLM_TIMEOUT_SEC", 20)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": sys_msg}, {"role": "user", "content": user_msg}],
            max_tokens=getattr(config, "USER_CMD_MAX_TOKENS", 350),
            temperature=0.1,
            timeout=timeout,
        )
        out = (resp.choices[0].message.content or "").strip()
        return out or "(读音无输出)"
    except Exception as e:
        return f"(读音失败: {str(e)[:80]})"


def examples_with_llm(text: str) -> str:
    """给出 1～2 个例句，使用当前词/短语。只输出例句，可带简短中文释义。"""
    text = _truncate((text or "").strip(), getattr(config, "USER_CMD_INPUT_MAX_CHARS", 400))
    if not text:
        return "(无内容)"
    sys_msg = "你只输出例句。根据用户给的词或短语，给出 1～2 个简短例句（可中英混合）。每句一行，不要编号外的解释。"
    user_msg = f"请为以下内容给出 1～2 个例句：\n\n{text}"
    try:
        client, model = _get_client_and_model()
        timeout = getattr(config, "USER_CMD_LLM_TIMEOUT_SEC", 20)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": sys_msg}, {"role": "user", "content": user_msg}],
            max_tokens=getattr(config, "USER_CMD_MAX_TOKENS", 350),
            temperature=0.3,
            timeout=timeout,
        )
        out = (resp.choices[0].message.content or "").strip()
        return out or "(例句无输出)"
    except Exception as e:
        return f"(例句失败: {str(e)[:80]})"
