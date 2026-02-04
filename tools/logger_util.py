# -*- coding: utf-8 -*-
"""Agent D：滚动日志、可选 debug 存帧；不阻塞主流程."""
import os
import time
from typing import Optional

import config

def _ensure_log_dir() -> Optional[str]:
    if not getattr(config, "LOG_TO_FILE", True):
        return None
    try:
        log_dir = getattr(config, "LOG_DIR", None) or os.path.join(os.path.dirname(__file__), "..", "logs")
        os.makedirs(log_dir, exist_ok=True)
        return log_dir
    except Exception:
        return None


def _rotate_if_needed(path: str) -> None:
    max_bytes = getattr(config, "LOG_ROTATING_MAX_BYTES", 5 * 1024 * 1024)
    backup = getattr(config, "LOG_BACKUP_COUNT", 3)
    try:
        if not os.path.exists(path) or os.path.getsize(path) < max_bytes:
            return
        if os.path.exists(path + f".{backup}"):
            os.remove(path + f".{backup}")
        for i in range(backup - 1, 0, -1):
            p1, p2 = path + f".{i}", path + f".{i + 1}"
            if os.path.exists(p1):
                os.replace(p1, p2)
        os.replace(path, path + ".1")
    except Exception:
        pass


def log(msg: str, level: str = "INFO") -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    line = f"[{ts}] [{level}] {msg}"
    try:
        print(line, flush=True)
    except Exception:
        pass
    if getattr(config, "LOG_TO_FILE", True):
        log_dir = _ensure_log_dir()
        if log_dir:
            path = os.path.join(log_dir, "camera_ocr_llm.log")
            try:
                _rotate_if_needed(path)
                with open(path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception:
                pass


def log_result(raw: str, corrected: str, confidence: float, ocr_ms: float, llm_ms: float) -> None:
    raw_s = (raw[:80] + "..." if len(raw) > 80 else raw) or ""
    cor_s = (corrected[:80] + "..." if len(corrected) > 80 else corrected) or ""
    log(
        f"OCR(raw={raw_s} | conf={confidence:.2%} | {ocr_ms:.0f}ms) -> LLM(corrected={cor_s} | {llm_ms:.0f}ms)",
        level="RESULT",
    )
    # 当本地 LLM 确有修正时单独打一行，便于在 log 里看到“修正识别的文字”
    if corrected.strip() and raw.strip() and corrected.strip() != raw.strip():
        log(f"LLM 已修正: 「{raw_s}」 -> 「{cor_s}」", level="INFO")


def log_metrics(fps: float, ocr_ms: float, llm_ms: float, pending: int) -> None:
    log(
        f"METRICS fps={fps:.1f} ocr_ms={ocr_ms:.0f} llm_ms={llm_ms:.0f} pending={pending}",
        level="INFO",
    )


def save_debug_frame(frame, reason: str = "error") -> None:
    """可选：将当前帧写入 logs/frames/，仅当 LOG_DEBUG_SAVE_FRAMES > 0 且 frame 非空."""
    n = getattr(config, "LOG_DEBUG_SAVE_FRAMES", 0)
    if n <= 0 or frame is None:
        return
    try:
        import cv2  # type: ignore[import-untyped]
        log_dir = _ensure_log_dir()
        if not log_dir:
            return
        frames_dir = os.path.join(log_dir, "frames")
        os.makedirs(frames_dir, exist_ok=True)
        name = f"{reason}_{time.strftime('%H%M%S', time.localtime())}.jpg"
        path = os.path.join(frames_dir, name)
        cv2.imwrite(path, frame)
        # 只保留最近 N 个文件
        files = sorted([f for f in os.listdir(frames_dir) if f.endswith(".jpg")], key=lambda f: os.path.getmtime(os.path.join(frames_dir, f)))
        for f in files[:-n]:
            try:
                os.remove(os.path.join(frames_dir, f))
            except Exception:
                pass
    except Exception:
        pass
