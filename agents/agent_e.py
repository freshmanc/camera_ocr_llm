# -*- coding: utf-8 -*-
"""Agent E：性能与体验（缓存 + 节流 + 文本归一化）"""
from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any, Dict, Optional


def normalize_text(text: str) -> str:
    """归一化文本：去首尾空白、多空格合一，用于缓存键与去抖一致。"""
    return " ".join((text or "").strip().split())


class LLMCache:
    """简单 LRU + TTL 缓存：避免对相同文本重复纠错。"""

    def __init__(self, max_size: int = 200, ttl_sec: float = 600.0) -> None:
        self._data: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self._max_size = max(1, max_size)
        self._ttl = max(1.0, float(ttl_sec))

    def _make_key(self, text: str, lang_hint: Optional[str] = None) -> str:
        base = normalize_text(text)
        return f"{base}||{lang_hint or 'auto'}"

    def get(self, text: str, lang_hint: Optional[str] = None) -> Optional[Dict[str, Any]]:
        key = self._make_key(text, lang_hint)
        if key not in self._data:
            return None
        entry = self._data.pop(key)
        # TTL 检查
        if time.monotonic() - entry.get("ts", 0.0) > self._ttl:
            return None
        # 重新放到尾部，维持 LRU
        self._data[key] = entry
        return entry

    def put(
        self,
        text: str,
        lang_hint: Optional[str],
        corrected: str,
        confidence: Optional[float],
        language_hint: Optional[str],
        llm_ms: float,
    ) -> None:
        key = self._make_key(text, lang_hint)
        entry = {
            "corrected": corrected,
            "confidence": confidence,
            "language_hint": language_hint,
            "llm_ms": llm_ms,
            "ts": time.monotonic(),
        }
        if key in self._data:
            self._data.pop(key)
        self._data[key] = entry
        while len(self._data) > self._max_size:
            self._data.popitem(last=False)  # 弹出最老


class LLMThrottler:
    """节流：限制真实 LLM 请求的最小时间间隔（毫秒）。"""

    def __init__(self, min_interval_ms: int = 1000) -> None:
        self._interval = max(0, int(min_interval_ms))
        self._last_call_ts_ms = 0.0

    def can_call(self) -> bool:
        """是否允许发起一次新的 LLM 请求（允许时会更新内部时间戳）。"""
        if self._interval <= 0:
            return True
        now_ms = time.monotonic() * 1000.0
        if now_ms - self._last_call_ts_ms >= self._interval:
            self._last_call_ts_ms = now_ms
            return True
        return False
