# -*- coding: utf-8 -*-
"""Agent D：轻量指标（帧率、OCR/LLM 耗时、pending 帧数），供日志与监控."""
from __future__ import annotations

import threading
import time
from typing import Optional


class Metrics:
    """线程安全：主线程更新 fps/frame_count，管道线程或主线程更新 ocr_ms/llm_ms，主线程可读 pending。"""
    def __init__(self):
        self._lock = threading.Lock()
        self._frame_count = 0
        self._fps_start = time.monotonic()
        self._last_ocr_ms: float = 0.0
        self._last_llm_ms: float = 0.0
        self._pending_frames = 0  # 由外部按 shared_state 快照写入

    def tick_frame(self) -> None:
        with self._lock:
            self._frame_count += 1

    def snapshot_fps(self) -> tuple[float, int]:
        """返回 (fps, frame_count)，并重置计数与时间窗口."""
        with self._lock:
            now = time.monotonic()
            elapsed = max(1e-6, now - self._fps_start)
            count = self._frame_count
            self._frame_count = 0
            self._fps_start = now
        return (count / elapsed, count)

    def set_ocr_llm_ms(self, ocr_ms: float, llm_ms: float) -> None:
        with self._lock:
            self._last_ocr_ms = ocr_ms
            self._last_llm_ms = llm_ms

    def set_pending(self, pending: int) -> None:
        with self._lock:
            self._pending_frames = pending

    def get_last_ocr_llm_ms(self) -> tuple[float, float]:
        with self._lock:
            return (self._last_ocr_ms, self._last_llm_ms)
