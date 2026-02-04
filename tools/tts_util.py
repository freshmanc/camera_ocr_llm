# -*- coding: utf-8 -*-
"""
语音朗读兼容层：所有逻辑在 agents.tts_agent，此处仅转发，避免代码分散。
业务请直接使用 agents.tts_agent.speak() 或 tools.tts_util.request_speak()。
"""
from __future__ import annotations

from agents.tts_agent import speak as request_speak

__all__ = ["request_speak"]
