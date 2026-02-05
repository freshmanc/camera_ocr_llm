# -*- coding: utf-8 -*-
"""
语音助手 Agent：用本地 LLM 做对话式助手，识别用户意图（朗读/翻译/读音/例句等），
回复中带 [ACTION:xxx] 时由主流程触发对应操作；对话在「语音助手」窗口显示。
"""
from __future__ import annotations

import os
import re
from typing import Callable, List, Optional, Tuple

import config


def _get_client_and_model():
    """与 llm_correct 一致，使用本地/云端 LLM。"""
    from openai import OpenAI
    use_openai = getattr(config, "LLM_USE_OPENAI", False)
    api_key = getattr(config, "OPENAI_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
    if use_openai and api_key:
        client = OpenAI(api_key=api_key)
        model = (getattr(config, "LLM_MODEL", "") or "gpt-4o-mini").strip()
        return client, model
    base_url = getattr(config, "LLM_BASE_URL", "http://127.0.0.1:1234/v1")
    client = OpenAI(base_url=base_url, api_key="lm-studio")
    model = getattr(config, "LLM_MODEL", "") or ""
    if not model:
        try:
            models = client.models.list(timeout=3)
            if models.data and len(models.data) > 0:
                model = models.data[0].id
        except Exception:
            pass
    return client, model or "default"


def _get_voice_client_and_model():
    """语音助手专用：若配置了 VOICE_ASSISTANT_BASE_URL / VOICE_ASSISTANT_MODEL 则用更快模型，否则同 _get_client_and_model。"""
    from openai import OpenAI
    use_openai = getattr(config, "LLM_USE_OPENAI", False)
    api_key = getattr(config, "OPENAI_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
    if use_openai and api_key:
        client = OpenAI(api_key=api_key)
        model = (getattr(config, "VOICE_ASSISTANT_MODEL", "") or getattr(config, "LLM_MODEL", "") or "gpt-4o-mini").strip()
        return client, model
    base_url = (getattr(config, "VOICE_ASSISTANT_BASE_URL", "") or "").strip() or getattr(config, "LLM_BASE_URL", "http://127.0.0.1:1234/v1")
    client = OpenAI(base_url=base_url, api_key="lm-studio")
    model = (getattr(config, "VOICE_ASSISTANT_MODEL", "") or "").strip() or getattr(config, "LLM_MODEL", "") or ""
    if not model:
        try:
            models = client.models.list(timeout=3)
            if models.data and len(models.data) > 0:
                model = models.data[0].id
        except Exception:
            pass
    return client, model or "default"


def _parse_action(reply: str) -> Optional[str]:
    """从助手回复中解析 [ACTION:read] / [ACTION:translate] 等，返回 action 或 None。"""
    if not reply:
        return None
    m = re.search(r"\[ACTION:\s*(\w+)\]", reply, re.IGNORECASE)
    if m:
        return m.group(1).lower()
    return None


def _parse_action_from_tail(reply: str, tail_chars: int = 280) -> Optional[str]:
    """仅从回复末尾一段解析 [ACTION:xxx]，避免把 thinking 中间「规则示例」当成已执行。"""
    if not reply or len(reply) <= tail_chars:
        return _parse_action(reply)
    tail = reply[-tail_chars:]
    return _parse_action(tail)


def _strip_action_tag(reply: str) -> str:
    """去掉回复中的 [ACTION:xxx] 行，便于界面只显示自然语言。"""
    if not reply:
        return reply
    return re.sub(r"\s*\[ACTION:\s*\w+\]\s*", "\n", reply).strip()


def _extract_conclusion_for_display(reply: str, max_chars: int = 80) -> str:
    """
    从 thinking 模型的长回复中只提取「结论」用于界面展示，过滤掉推理过程。
    优先：最后几行中像结论的短句（以。结尾或含 好的/正在/已）。
    """
    s = _strip_action_tag(reply)
    if not s or len(s) <= max_chars:
        return s.strip()
    lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
    if not lines:
        return s[-max_chars:].strip()
    # 结论样式的短句：以。/. 结尾，或含 好的/正在/已
    conclusion_markers = ("好的", "正在", "已", "。", ".")
    def looks_like_conclusion(ln: str) -> bool:
        if len(ln) > max_chars:
            return False
        return ln.rstrip().endswith(("。", ".")) or any(m in ln for m in conclusion_markers)
    candidates = [ln for ln in lines if looks_like_conclusion(ln)]
    if candidates:
        return candidates[-1].strip()
    short = [ln for ln in lines if len(ln) <= max_chars]
    if short:
        return short[-1].strip()
    # 按句号拆，取最后一句
    for sep in ("。", "."):
        parts = s.split(sep)
        if len(parts) >= 2:
            last = (parts[-1] or parts[-2]).strip()
            if 0 < len(last) <= max_chars:
                return last + ("。" if sep == "。" else "")
    return s[-max_chars:].strip()


def _is_thinking_truncated(reply: str) -> bool:
    """判断是否为被截断的长推理（超时导致），应替换为简短提示。"""
    if not reply or len(reply) < 100:
        return False
    lower = reply.strip().lower()
    if lower.startswith(("首先", "we are given", "okay,", "let's", "let me", "the user")):
        return True
    if "根据系统提示" in reply or "回顾指令" in reply:
        return True
    return False


def chat_direct_llm(
    user_message: str,
    recent_history: Optional[List[Tuple[str, str]]] = None,
    current_ocr_content: str = "",
) -> str:
    """
    直接对接 LLM：把用户消息和对话历史发给模型，附带当前画面文字供参考，返回模型回复原文。
    不做 [ACTION:xxx] 解析，对话窗口只做中转。
    """
    user_message = (user_message or "").strip()
    if not user_message:
        return "（请说点什么）"
    sys_prompt = (
        "你是摄像头 OCR 应用的对话助手。用户可能让你翻译当前画面文字、读读音、举例句或随便聊天。"
        "下面会提供「当前画面识别的文字」供参考（若无则显示暂无）。请直接、自然地回复，不要输出任何 [ACTION:xxx] 标签。"
    )
    memory = (getattr(config, "VOICE_ASSISTANT_MEMORY", "") or "").strip()
    if memory:
        sys_prompt = sys_prompt.rstrip() + "\n\n【长期记忆】\n" + memory
    timeout = getattr(config, "VOICE_ASSISTANT_TIMEOUT_SEC", 90)
    model = getattr(config, "LLM_MODEL", "") or ""
    if "thinking" in model.lower():
        timeout = max(timeout, 120)
    max_tokens = getattr(config, "VOICE_ASSISTANT_MAX_TOKENS", 950)
    context_n = getattr(config, "VOICE_ASSISTANT_CONTEXT_MESSAGES", 24)
    messages: List[dict] = [{"role": "system", "content": sys_prompt}]
    if recent_history:
        for role, text in recent_history[-context_n:]:
            messages.append({"role": role, "content": text})
    ctx = (current_ocr_content or "").strip() or "（暂无）"
    user_with_ctx = f"【当前画面文字】\n{ctx}\n\n用户说：{user_message}"
    messages.append({"role": "user", "content": user_with_ctx})
    try:
        client, model_id = _get_voice_client_and_model()
        resp = client.chat.completions.create(
            model=model_id,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.5,
            timeout=timeout,
        )
        reply = (resp.choices[0].message.content or "").strip()
        return reply or "（未收到回复，请重试）"
    except Exception as e:
        err = str(e).strip()[:80]
        if "timeout" in err.lower() or "timed out" in err.lower():
            return "（请求超时或连接断开，请重试）"
        return f"（助手暂时无法回复: {err}）"


def chat_direct_llm_stream(
    user_message: str,
    recent_history: Optional[List[Tuple[str, str]]] = None,
    current_ocr_content: str = "",
    on_chunk: Optional[Callable[[str], None]] = None,
) -> str:
    """
    直接对接 LLM 并流式返回：每收到一块内容就调用 on_chunk(delta)，主线程可据此刷新对话窗口。
    返回完整回复；异常时返回错误信息字符串。
    """
    user_message = (user_message or "").strip()
    if not user_message:
        return "（请说点什么）"
    sys_prompt = (
        "你是摄像头 OCR 应用的对话助手。用户可能让你翻译当前画面文字、读读音、举例句或随便聊天。"
        "下面会提供「当前画面识别的文字」供参考（若无则显示暂无）。请直接、自然地回复，不要输出任何 [ACTION:xxx] 标签。"
    )
    memory = (getattr(config, "VOICE_ASSISTANT_MEMORY", "") or "").strip()
    if memory:
        sys_prompt = sys_prompt.rstrip() + "\n\n【长期记忆】\n" + memory
    timeout = getattr(config, "VOICE_ASSISTANT_TIMEOUT_SEC", 90)
    model = getattr(config, "LLM_MODEL", "") or ""
    if "thinking" in model.lower():
        timeout = max(timeout, 120)
    max_tokens = getattr(config, "VOICE_ASSISTANT_MAX_TOKENS", 950)
    context_n = getattr(config, "VOICE_ASSISTANT_CONTEXT_MESSAGES", 24)
    messages: List[dict] = [{"role": "system", "content": sys_prompt}]
    if recent_history:
        for role, text in recent_history[-context_n:]:
            messages.append({"role": role, "content": text})
    ctx = (current_ocr_content or "").strip() or "（暂无）"
    user_with_ctx = f"【当前画面文字】\n{ctx}\n\n用户说：{user_message}"
    messages.append({"role": "user", "content": user_with_ctx})
    try:
        client, model_id = _get_voice_client_and_model()
        stream = client.chat.completions.create(
            model=model_id,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.5,
            timeout=timeout,
            stream=True,
        )
        full: List[str] = []
        for chunk in stream:
            if not chunk.choices or len(chunk.choices) == 0:
                continue
            delta = getattr(chunk.choices[0].delta, "content", None) or ""
            if isinstance(delta, str) and delta:
                full.append(delta)
                if on_chunk:
                    try:
                        on_chunk(delta)
                    except Exception:
                        pass
        reply = "".join(full).strip()
        return reply or "（未收到回复，请重试）"
    except Exception as e:
        err = str(e).strip()[:80]
        if "timeout" in err.lower() or "timed out" in err.lower():
            return "（请求超时或连接断开，请重试）"
        return f"（助手暂时无法回复: {err}）"


def chat_with_assistant(
    user_message: str,
    recent_history: Optional[List[Tuple[str, str]]] = None,
) -> Tuple[str, Optional[str]]:
    """
    用户说一句话，调用本地 LLM 得到助手回复，并解析是否带 [ACTION:xxx]。
    返回 (助手回复文本（已去掉 ACTION 行）, action 或 None)。
    """
    user_message = (user_message or "").strip()
    if not user_message:
        return "(请说点什么)", None

    sys_prompt = getattr(config, "VOICE_ASSISTANT_SYSTEM", "") or "You are a helpful assistant."
    memory = (getattr(config, "VOICE_ASSISTANT_MEMORY", "") or "").strip()
    if memory:
        sys_prompt = sys_prompt.rstrip() + "\n\n【长期记忆】\n" + memory
    timeout = getattr(config, "VOICE_ASSISTANT_TIMEOUT_SEC", 90)
    # thinking 类模型输出慢，容易触发 Client disconnected，单独加长超时
    model = getattr(config, "LLM_MODEL", "") or ""
    if "thinking" in model.lower():
        timeout = max(timeout, 120)
    max_tokens = getattr(config, "VOICE_ASSISTANT_MAX_TOKENS", 400)

    messages: List[dict] = [{"role": "system", "content": sys_prompt}]
    context_n = getattr(config, "VOICE_ASSISTANT_CONTEXT_MESSAGES", 24)
    if recent_history:
        for role, text in recent_history[-context_n:]:  # 短期记忆：最近 N 条传给 LLM
            messages.append({"role": role, "content": text})
    messages.append({"role": "user", "content": user_message})

    try:
        client, model = _get_voice_client_and_model()
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.5,
            timeout=timeout,
        )
        reply = (resp.choices[0].message.content or "").strip()
        if not reply:
            return "（未收到回复，可能超时断连，请重试）", None
        action = _parse_action(reply)
        raw_display = _strip_action_tag(reply)
        if _is_thinking_truncated(raw_display):
            # 仅当 [ACTION:xxx] 出现在回复末尾时才视为「已执行」，避免规则示例被误判
            action_from_tail = _parse_action_from_tail(reply)
            display_reply = "（回复被截断，已根据意图执行）" if action_from_tail else "（回复被截断，请简短重问或打字输入）"
            if not action_from_tail:
                action = None
        else:
            # thinking 模型输出过长时只展示结论，不展示推理过程
            max_display = getattr(config, "VOICE_ASSISTANT_DISPLAY_MAX_CHARS", 80)
            display_reply = _extract_conclusion_for_display(reply, max_chars=max_display)
            if not display_reply.strip():
                display_reply = "（已执行）" if action else "（无有效回复，请重试）"
        return display_reply or "（无回复）", action
    except Exception as e:
        err = str(e).strip()[:80]
        if "timeout" in err.lower() or "timed out" in err.lower():
            return "（请求超时或连接断开，请重试。若经常出现可调大 config 中 VOICE_ASSISTANT_TIMEOUT_SEC）", None
        return f"（助手暂时无法回复: {err}）", None
