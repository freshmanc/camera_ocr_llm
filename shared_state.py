# -*- coding: utf-8 -*-
"""线程安全共享状态：主线程只读，后台线程写入，保证画面不因 LLM 阻塞"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
import cv2  # type: ignore[import-untyped]


@dataclass
class DisplayResult:
    """供主线程显示的最近一次 OCR+LLM 结果"""
    raw_ocr: str = ""
    debounced_ocr: str = ""  # 去抖后的 OCR，用于显示并触发 LLM
    corrected: str = ""
    confidence: float = 0.0
    ocr_time_ms: float = 0.0
    llm_time_ms: float = 0.0
    ocr_ok: bool = True
    llm_ok: bool = True
    error_msg: Optional[str] = None
    vision_llm_text: str = ""        # 视觉 LLM 从截图提取的文字
    cross_validated_text: str = ""   # 交叉验证/合并后的文字（依 CROSS_VALIDATE_MODE）


class SharedState:
    """最新仅保留单槽：主线程写 current_frame、读 latest_result；管道线程读帧副本、写 latest_result。支持多帧融合与稳定后才 OCR。"""
    def __init__(self, fusion_frames: int = 0):
        self._lock = threading.Lock()
        self.latest_result = DisplayResult()
        self._current_frame: Optional[np.ndarray] = None
        self._frame_count = 0
        self._last_ocr_frame_count = -999
        self._fusion_frames = max(0, int(fusion_frames))
        self._frame_buffer: deque = deque(maxlen=max(1, self._fusion_frames))
        self._last_submitted_frame: Optional[np.ndarray] = None
        # 用户指令 Agent：待处理命令 + 解释窗口内容
        self._pending_command: Optional[str] = None
        self._content_for_command: str = ""
        self._explanation_title: str = ""
        self._explanation_content: str = ""
        # 视觉 LLM + 交叉验证：存一帧供 vision 用，以及 vision/交叉结果
        self._last_ocr_frame: Optional[np.ndarray] = None
        self._vision_llm_text: str = ""
        self._cross_validated_text: str = ""
        # 语音助手：对话历史 (role, text, timestamp, audio_path?) + 待发送的用户消息 + 待自动播放音频
        self._chat_history: List[Tuple] = []
        self._pending_chat_message: Optional[str] = None
        self._pending_play_audio: Optional[str] = None

    def append_chat(self, role: str, text: str, audio_path: Optional[str] = None) -> None:
        """后台线程：追加一条对话（user 或 assistant），带时间戳；可选附带朗读音频路径（会触发自动播放）。"""
        with self._lock:
            path = (audio_path or "").strip() or ""
            self._chat_history.append((role, (text or "").strip(), time.time(), path))
            if path:
                self._pending_play_audio = path
            max_len = 64
            if len(self._chat_history) > max_len:
                self._chat_history = self._chat_history[-max_len:]

    def get_and_clear_pending_play_audio(self) -> Optional[str]:
        """主线程：取走待自动播放的音频路径，取后清空。"""
        with self._lock:
            path = self._pending_play_audio
            self._pending_play_audio = None
            return path

    def get_chat_history(self) -> List[Tuple]:
        """主线程：获取对话历史副本 [(role, text, timestamp, audio_path), ...]，用于绘制。"""
        with self._lock:
            return list(self._chat_history)

    def set_pending_chat(self, message: str) -> None:
        """主线程：用户输入/语音识别后，提交给助手。"""
        with self._lock:
            self._pending_chat_message = (message or "").strip() or None

    def get_and_clear_pending_chat(self) -> Optional[str]:
        """后台线程：取走待处理用户消息。"""
        with self._lock:
            msg = self._pending_chat_message
            self._pending_chat_message = None
            return msg

    def get_content_for_command(self) -> str:
        """后台线程：获取当前可用于朗读/翻译等的文本（纠错后或去抖 OCR）。"""
        with self._lock:
            return (self.latest_result.corrected or self.latest_result.debounced_ocr or "").strip()

    def get_content_and_confidence_for_command(self) -> Tuple[str, float]:
        """后台线程：获取当前可朗读的文本及其置信度（0~1），用于「读一下」短路判断。"""
        with self._lock:
            c = (self.latest_result.corrected or self.latest_result.debounced_ocr or "").strip()
            return c, float(self.latest_result.confidence)

    def set_last_ocr_frame(self, frame: np.ndarray) -> None:
        """后台线程：保存当前用于 OCR 的帧，供视觉 LLM 提取文字。"""
        with self._lock:
            self._last_ocr_frame = frame.copy() if frame is not None else None

    def get_and_clear_last_ocr_frame(self) -> Optional[np.ndarray]:
        """后台线程：取走供视觉 LLM 用的帧，取后清空。"""
        with self._lock:
            out = self._last_ocr_frame
            self._last_ocr_frame = None
            return out

    def set_vision_and_cross_validated(self, vision_text: str, cross_text: str) -> None:
        """后台线程：写入视觉 LLM 结果与交叉验证/合并结果。"""
        with self._lock:
            self._vision_llm_text = (vision_text or "").strip()
            self._cross_validated_text = (cross_text or "").strip()

    def set_pending_user_command(self, cmd: str, content: str) -> None:
        """主线程：用户按下 R/T/P/E 时调用，传入命令与当前识别内容。"""
        with self._lock:
            self._pending_command = cmd
            self._content_for_command = (content or "").strip()

    def get_and_clear_pending_command(self) -> Tuple[Optional[str], str]:
        """后台线程：取走待处理命令与内容，取后清空。返回 (cmd, content)。"""
        with self._lock:
            cmd, content = self._pending_command, self._content_for_command
            self._pending_command = None
            self._content_for_command = ""
            return cmd, content

    def set_explanation(self, title: str, content: str) -> None:
        """后台线程：写入解释窗口标题与正文。"""
        with self._lock:
            self._explanation_title = (title or "").strip()
            self._explanation_content = (content or "").strip()

    def get_explanation(self) -> Tuple[str, str]:
        """主线程：读取解释窗口标题与正文（不阻塞）。"""
        with self._lock:
            return self._explanation_title, self._explanation_content

    def set_frame(self, frame: np.ndarray) -> None:
        """主线程每帧调用；每调用一次帧计数+1，并写入融合用环形缓冲。"""
        with self._lock:
            self._current_frame = frame
            self._frame_count += 1
            self._frame_buffer.append(frame.copy())

    def get_frame_for_ocr(
        self,
        skip: int,
        fusion_frames: int = 0,
        motion_stable_enabled: bool = False,
        motion_threshold: float = 20.0,
    ) -> Optional[np.ndarray]:
        """后台线程调用：满足 skip 且（若开启）画面稳定时，返回当前帧或融合帧副本。"""
        with self._lock:
            if self._current_frame is None:
                return None
            if self._frame_count - self._last_ocr_frame_count < skip:
                return None
            # 多帧融合：取最近 fusion_frames 帧平均
            n_fuse = max(0, int(fusion_frames))
            if n_fuse > 1 and len(self._frame_buffer) >= n_fuse:
                frames = list(self._frame_buffer)[-n_fuse:]
                out = np.stack(frames, axis=0).astype(np.float32)
                out = np.mean(out, axis=0).astype(np.uint8)
            else:
                out = self._current_frame.copy()
            # 稳定后才 OCR：与上一帧差异过大则本轮不识别
            if motion_stable_enabled and self._last_submitted_frame is not None:
                try:
                    a = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
                    b = cv2.cvtColor(self._last_submitted_frame, cv2.COLOR_BGR2GRAY)
                    diff = cv2.absdiff(a, b)
                    if diff.mean() > motion_threshold:
                        return None
                except Exception:
                    pass
            self._last_submitted_frame = out.copy()
            self._last_ocr_frame_count = self._frame_count
            return out

    def get_pending_frames_count(self) -> int:
        """主线程/日志用：自上次 OCR 以来写入的帧数（单槽下无队列，此为“待处理”概念）."""
        with self._lock:
            return max(0, self._frame_count - self._last_ocr_frame_count)

    def get_latest_result(self) -> DisplayResult:
        """主线程每帧调用，不阻塞."""
        with self._lock:
            return DisplayResult(
                raw_ocr=self.latest_result.raw_ocr,
                debounced_ocr=self.latest_result.debounced_ocr,
                corrected=self.latest_result.corrected,
                confidence=self.latest_result.confidence,
                ocr_time_ms=self.latest_result.ocr_time_ms,
                llm_time_ms=self.latest_result.llm_time_ms,
                ocr_ok=self.latest_result.ocr_ok,
                llm_ok=self.latest_result.llm_ok,
                error_msg=self.latest_result.error_msg,
                vision_llm_text=self._vision_llm_text,
                cross_validated_text=self._cross_validated_text,
            )

    def set_latest_result(
        self,
        raw_ocr: str,
        corrected: str,
        confidence: float,
        ocr_time_ms: float,
        llm_time_ms: float,
        ocr_ok: bool,
        llm_ok: bool,
        error_msg: Optional[str] = None,
        debounced_ocr: Optional[str] = None,
    ) -> None:
        """后台线程在完成一次 OCR+LLM 后调用."""
        with self._lock:
            self.latest_result = DisplayResult(
                raw_ocr=raw_ocr,
                debounced_ocr=debounced_ocr if debounced_ocr is not None else "",
                corrected=corrected,
                confidence=confidence,
                ocr_time_ms=ocr_time_ms,
                llm_time_ms=llm_time_ms,
                ocr_ok=ocr_ok,
                llm_ok=llm_ok,
                error_msg=error_msg,
            )
