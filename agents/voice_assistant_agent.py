# -*- coding: utf-8 -*-
"""
语音助手 Agent：用本地 LLM 做对话式助手，识别用户意图（朗读/翻译/读音/例句等），
回复中带 [ACTION:xxx] 时由主流程触发对应操作；对话在「语音助手」窗口显示。
"""
from __future__ import annotations

import os
import re
from typing import List, Optional, Tuple

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


def _parse_action(reply: str) -> Optional[str]:
    """从助手回复中解析 [ACTION:read] / [ACTION:translate] 等，返回 action 或 None。"""
    if not reply:
        return None
    m = re.search(r"\[ACTION:\s*(\w+)\]", reply, re.IGNORECASE)
    if m:
        return m.group(1).lower()
    return None


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
    timeout = getattr(config, "VOICE_ASSISTANT_TIMEOUT_SEC", 90)
    # thinking 类模型输出慢，容易触发 Client disconnected，单独加长超时
    model = getattr(config, "LLM_MODEL", "") or ""
    if "thinking" in model.lower():
        timeout = max(timeout, 120)
    max_tokens = getattr(config, "VOICE_ASSISTANT_MAX_TOKENS", 400)

    messages: List[dict] = [{"role": "system", "content": sys_prompt}]
    if recent_history:
        for role, text in recent_history[-10:]:  # 最近 5 轮
            messages.append({"role": role, "content": text})
    messages.append({"role": "user", "content": user_message})

    try:
        client, model = _get_client_and_model()
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
            display_reply = "（回复被截断，已根据意图执行）" if action else "（回复被截断，请重试）"
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
