# -*- coding: utf-8 -*-
"""工具：OCR 引擎、预处理、覆盖层、日志、指标、TTS 兼容层。"""
from tools.ocr_engine import run_ocr, OCRResult
from tools.preprocess import preprocess_for_ocr
from tools.overlay import build_display_lines, draw_text_block
from tools.logger_util import log, log_result, log_metrics, save_debug_frame
from tools.metrics import Metrics
from tools.tts_util import request_speak

__all__ = [
    "run_ocr",
    "OCRResult",
    "preprocess_for_ocr",
    "build_display_lines",
    "draw_text_block",
    "log",
    "log_result",
    "log_metrics",
    "save_debug_frame",
    "Metrics",
    "request_speak",
]
