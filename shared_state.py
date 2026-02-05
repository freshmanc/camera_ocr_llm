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
        # 语音助手：对话历史 (role, text, timestamp, audio_path?) + 待发送的用户消息 + 待自动播放音频 + 上一次朗读的【内容】（用于「翻译之前的」）
        self._chat_history: List[Tuple] = []
        self._pending_chat_message: Optional[str] = None
        self._pending_play_audio: Optional[str] = None
        self._last_read_content: str = ""
        # 流式回复：当前正在接收的助手内容，get_chat_history 会把它合并到最后一条 assistant 显示
        self._streaming_text: Optional[str] = None
        # 摄像头窗口是否显示实时画面（False 时主循环显示占位图，对话窗口可点「打开摄像头」恢复）
        self._show_camera_window: bool = True
        # 是否开启摄像头与识别：False=不打开设备、不识别；按按键或点按钮切换
        self._camera_wanted: bool = False
        # 用户上传文件：下一次发消息时会附带给 LLM，用后清空
        self._uploaded_file_name: Optional[str] = None
        self._uploaded_file_content: Optional[str] = None
        # 最近一次生成的试卷与答案路径，供「批改试卷」时使用
        self._last_exam_paper_path: Optional[str] = None
        self._last_exam_answer_key_path: Optional[str] = None
        # 截图识别：提交一帧做一次 OCR+LLM，后台取走后清空
        self._pending_screenshot: Optional[np.ndarray] = None
        # 语音助手窗口关闭时设为 True，主循环据此退出
        self._quit_requested: bool = False

    def set_quit_requested(self, value: bool = True) -> None:
        """语音助手窗口关闭时调用，主循环检测后退出。"""
        with self._lock:
            self._quit_requested = value

    def get_quit_requested(self) -> bool:
        """主循环每轮检查，为 True 时退出。"""
        with self._lock:
            return self._quit_requested

    def append_chat(self, role: str, text: str, audio_path: Optional[str] = None) -> None:
        """后台线程：追加一条对话（user 或 assistant），带时间戳；可选附带朗读音频路径（会触发自动播放）。"""
        with self._lock:
            path = (audio_path or "").strip() or ""
            self._chat_history.append((role, (text or "").strip(), time.time(), path))
            if path:
                self._pending_play_audio = path
            try:
                import config
                max_len = getattr(config, "CHAT_HISTORY_MAX", 64)
            except Exception:
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
        """主线程：获取对话历史副本 [(role, text, timestamp, audio_path), ...]，用于绘制。流式时最后一条 assistant 的 text 为当前 _streaming_text。"""
        with self._lock:
            out = list(self._chat_history)
            if self._streaming_text is not None and out and out[-1][0] == "assistant":
                last = out[-1]
                out[-1] = (last[0], self._streaming_text, last[2], last[3] if len(last) > 3 else None)
            return out

    def start_streaming(self, placeholder: str = "已收到，正在处理…") -> None:
        """后台：开始流式回复，最后一条 assistant 显示 placeholder，后续通过 append_streaming_delta 追加；结束时由 finish_streaming 写最终内容。
        若此前有未结束的流（用户中途点麦/发新消息），先把已生成内容写回对应 assistant，避免被新流覆盖丢失。"""
        with self._lock:
            # 此前有流未 finish_streaming 时，先固化到“当时在写”的那条 assistant（最后一条内容为空的）
            if self._streaming_text is not None and self._chat_history:
                prev = (self._streaming_text or "").strip()
                for i in range(len(self._chat_history) - 1, -1, -1):
                    if self._chat_history[i][0] == "assistant" and ((self._chat_history[i][1] or "").strip() == ""):
                        last = self._chat_history[i]
                        self._chat_history[i] = (last[0], prev or "（回复被中断）", last[2], last[3] if len(last) > 3 else None)
                        break
                self._streaming_text = None
            if self._chat_history and self._chat_history[-1][0] == "assistant":
                last = self._chat_history[-1]
                self._chat_history[-1] = (last[0], "", last[2], last[3] if len(last) > 3 else None)
            self._streaming_text = (placeholder or "").strip()

    def append_streaming_delta(self, delta: str) -> None:
        """后台：追加一段流式内容（LLM 每收到一块就调用）。"""
        with self._lock:
            if self._streaming_text is not None:
                self._streaming_text = (self._streaming_text or "") + (delta or "")

    def get_streaming_content(self) -> Optional[str]:
        """主线程：当前流式内容，用于判断是否需要刷新对话区。"""
        with self._lock:
            return self._streaming_text

    def get_show_camera_window(self) -> bool:
        """主线程：是否在摄像头窗口显示实时画面（否则显示占位）。"""
        with self._lock:
            return self._show_camera_window

    def set_show_camera_window(self, show: bool) -> None:
        """主线程/对话窗口：切换摄像头窗口显示实时画面或占位。"""
        with self._lock:
            self._show_camera_window = bool(show)

    def get_camera_wanted(self) -> bool:
        """是否开启摄像头与识别（按按键或点按钮切换）。"""
        with self._lock:
            return self._camera_wanted

    def set_camera_wanted(self, wanted: bool) -> None:
        """设置是否开启摄像头与识别。"""
        with self._lock:
            self._camera_wanted = bool(wanted)

    def toggle_camera_wanted(self) -> bool:
        """切换摄像头开关状态，返回切换后的状态。"""
        with self._lock:
            self._camera_wanted = not self._camera_wanted
            return self._camera_wanted

    def finish_streaming(self, final_text: str) -> None:
        """后台：结束流式，将最后一条 assistant 设为最终内容并清空 _streaming_text。"""
        with self._lock:
            text = (final_text or "").strip()
            if self._chat_history and self._chat_history[-1][0] == "assistant":
                last = self._chat_history[-1]
                self._chat_history[-1] = (last[0], text, last[2], last[3] if len(last) > 3 else None)
            else:
                self._chat_history.append(("assistant", text, time.time(), None))
            self._streaming_text = None
            try:
                import config
                max_len = getattr(config, "CHAT_HISTORY_MAX", 64)
            except Exception:
                max_len = 64
            if len(self._chat_history) > max_len:
                self._chat_history = self._chat_history[-max_len:]

    def set_uploaded_file(self, name: str, content: str) -> None:
        """主线程：用户上传文件后调用，供下一次对话附带给 LLM。"""
        with self._lock:
            self._uploaded_file_name = (name or "").strip() or None
            self._uploaded_file_content = (content or "").strip() or None

    def get_uploaded_file(self) -> Tuple[Optional[str], Optional[str]]:
        """后台线程：获取当前上传的文件名与内容（不清空）。返回 (name, content)。"""
        with self._lock:
            return self._uploaded_file_name, self._uploaded_file_content

    def get_and_clear_uploaded_file(self) -> Tuple[Optional[str], Optional[str]]:
        """后台线程：取走上传的文件名与内容，取后清空。返回 (name, content)。"""
        with self._lock:
            name, content = self._uploaded_file_name, self._uploaded_file_content
            self._uploaded_file_name = None
            self._uploaded_file_content = None
            return name, content

    def set_last_exam_paths(self, paper_path: Optional[str], answer_key_path: Optional[str]) -> None:
        """后台：保存最近一次生成的试卷与答案路径，供批改时使用。"""
        with self._lock:
            self._last_exam_paper_path = (paper_path or "").strip() or None
            self._last_exam_answer_key_path = (answer_key_path or "").strip() or None

    def get_last_exam_paths(self) -> Tuple[Optional[str], Optional[str]]:
        """后台：获取最近一次试卷与答案路径。返回 (paper_path, answer_key_path)。"""
        with self._lock:
            return self._last_exam_paper_path, self._last_exam_answer_key_path

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

    def get_content_for_tts_lang_detect(self) -> str:
        """后台线程：获取用于 TTS 语言检测的文本。优先用 debounced_ocr（可能保留重音），避免纠错后丢重音被误判成英语。"""
        with self._lock:
            # 优先用去抖 OCR，因 LLM 纠错有时会去掉 é 等重音
            return (self.latest_result.debounced_ocr or self.latest_result.corrected or "").strip()

    def set_last_read_content(self, content: str) -> None:
        """后台线程：保存最近一次朗读的【内容】，供「翻译之前的句子」等使用。"""
        with self._lock:
            self._last_read_content = (content or "").strip()

    def get_last_read_content(self) -> str:
        """后台线程：取回最近一次朗读的【内容】。"""
        with self._lock:
            return (self._last_read_content or "").strip()

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

    def get_current_frame(self) -> Optional[np.ndarray]:
        """主线程/截图按钮：获取当前最新帧副本；无帧时返回 None。"""
        with self._lock:
            if self._current_frame is None:
                return None
            return self._current_frame.copy()

    def set_pending_screenshot(self, frame: np.ndarray) -> None:
        """主线程：提交一帧做「截图识别」，后台将对该帧做一次 OCR+LLM 并更新结果。"""
        with self._lock:
            self._pending_screenshot = frame.copy()

    def get_and_clear_pending_screenshot(self) -> Optional[np.ndarray]:
        """后台线程：取走待识别的截图帧，取后清空。"""
        with self._lock:
            out = self._pending_screenshot
            self._pending_screenshot = None
            return out

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
