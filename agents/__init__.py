# -*- coding: utf-8 -*-
"""Agents：OCR 去抖、LLM 纠错与缓存节流、朗读等逻辑。"""
from agents.debounce import OCRDebouncer, text_similarity
from agents.agent_e import LLMCache, LLMThrottler, normalize_text
from agents.llm_correct import correct_with_llm, LLMResult
from agents.tts_agent import speak

__all__ = [
    "OCRDebouncer",
    "text_similarity",
    "LLMCache",
    "LLMThrottler",
    "normalize_text",
    "correct_with_llm",
    "LLMResult",
    "speak",
]
