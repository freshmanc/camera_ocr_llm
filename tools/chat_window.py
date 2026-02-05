# -*- coding: utf-8 -*-
"""
白底黑字可交互对话窗口：文字输入、发送、小麦克风点击语音。与 SharedState 同步，支持本地 LLM 动作（朗读/翻译/读音/例句）。
"""
from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import font as tkfont
from tkinter import scrolledtext
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from shared_state import SharedState


def _wrap_text(text: str, width_chars: int = 36) -> list[str]:
    out = []
    for line in text.split("\n"):
        s = line.strip()
        while len(s) > width_chars:
            out.append(s[:width_chars])
            s = s[width_chars:]
        if s:
            out.append(s)
    return out or [""]


class ChatWindow:
    """白底黑字对话窗口：聊天区 + 输入框 + 发送 + 麦克风按钮。由主循环调用 update_from_state() 刷新。"""

    def __init__(self, state: "SharedState", title: str = "语音助手"):
        self.state = state
        self.title = title
        self._root: Optional[tk.Tk] = None
        self._chat_text: Optional[tk.Text] = None
        self._entry: Optional[tk.Entry] = None
        self._last_history_len = -1
        self._get_content_for_command: Optional[Callable[[], str]] = None
        self._stop_voice = threading.Event()
        self._voice_recording = False
        self._play_tag_to_path: dict = {}
        self._last_history_sig: Optional[str] = None  # 仅当对话变化时重绘，避免每帧刷新

    def set_content_for_command_callback(self, fn: Callable[[], str]) -> None:
        """可选：用于语音指令取当前识别内容（与 worker 一致）。"""
        self._get_content_for_command = fn

    def build(self) -> tk.Tk:
        self._root = tk.Tk()
        self._root.title(self.title)
        self._root.configure(bg="#ffffff")
        self._root.geometry("500x480+80+80")
        self._root.minsize(380, 400)

        # 先放底部栏，保证输入框和「语音」始终在窗口底部可见
        bottom = tk.Frame(self._root, bg="#ffffff", height=56)
        bottom.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=(0, 8))
        bottom.pack_propagate(False)

        # 聊天区域在上方，填充剩余空间
        chat_frame = tk.Frame(self._root, bg="#ffffff")
        chat_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=8)
        font_chat = tkfont.Font(family="Microsoft YaHei UI" if tkfont.nametofont("TkDefaultFont").actual() else "TkDefaultFont", size=11)
        self._chat_text = scrolledtext.ScrolledText(
            chat_frame,
            wrap=tk.WORD,
            font=font_chat,
            bg="#ffffff",
            fg="#000000",
            insertbackground="#000000",
            state=tk.DISABLED,
            padx=6,
            pady=6,
        )
        self._chat_text.pack(fill=tk.BOTH, expand=True)
        self._chat_text.bind("<Key>", lambda e: "break")  # 禁止在聊天区打字，但保持 NORMAL 以便点击「播放」
        self._entry = tk.Entry(
            bottom,
            font=("Microsoft YaHei UI", 11),
            bg="#ffffff",
            fg="#000000",
            insertbackground="#000000",
            relief=tk.SOLID,
            bd=2,
            highlightthickness=1,
            highlightcolor="#888888",
        )
        self._entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=6, padx=(0, 6))
        self._entry.bind("<Return>", lambda e: self._on_send())

        send_btn = tk.Button(
            bottom,
            text="发送",
            font=("Microsoft YaHei UI", 10),
            bg="#e0e0e0",
            fg="#000000",
            activebackground="#d0d0d0",
            relief=tk.RAISED,
            bd=1,
            padx=12,
            pady=6,
            cursor="hand2",
            command=self._on_send,
        )
        send_btn.pack(side=tk.LEFT, padx=(0, 6))

        # 小麦克风：按住说话、松开结束并识别
        mic_btn = tk.Button(
            bottom,
            text="语音",
            font=("Microsoft YaHei UI", 10),
            bg="#dae8fc",
            fg="#000000",
            activebackground="#b8d4f0",
            relief=tk.RAISED,
            bd=1,
            padx=10,
            pady=6,
            cursor="hand2",
        )
        mic_btn.bind("<ButtonPress-1>", lambda e: self._on_mic_press())
        mic_btn.bind("<ButtonRelease-1>", lambda e: self._on_mic_release())
        mic_btn.pack(side=tk.LEFT)

        # 窗口置前并让输入框获得焦点，便于直接打字
        self._root.lift()
        self._root.attributes("-topmost", True)
        self._root.after(200, self._focus_entry)
        self._root.after(500, lambda: self._root.attributes("-topmost", False))

        return self._root

    def _focus_entry(self) -> None:
        if self._entry and self._root:
            try:
                self._entry.focus_set()
            except tk.TclError:
                pass

    def _on_send(self) -> None:
        if not self._entry:
            return
        msg = (self._entry.get() or "").strip()
        self._entry.delete(0, tk.END)
        if not msg:
            return
        self.state.append_chat("user", msg)
        self.state.append_chat("assistant", "已收到，正在处理…")
        self.state.set_pending_chat(msg)
        self._last_history_len = -1
        self._entry.focus_set()

    def _on_mic_press(self) -> None:
        if self._voice_recording:
            return
        self._voice_recording = True
        self._stop_voice.clear()
        self.state.append_chat("assistant", "正在听…（松开结束）")
        self._last_history_len = -1
        threading.Thread(target=self._record_until_release, daemon=True).start()

    def _on_mic_release(self) -> None:
        self._stop_voice.set()

    def _record_until_release(self) -> None:
        """按住期间录音，松手后停止并识别。"""
        try:
            import speech_recognition as sr
            import pyaudio
        except ImportError:
            self.state.append_chat("assistant", "语音输入需要安装: pip install SpeechRecognition pyaudio")
            self._voice_recording = False
            self._last_history_len = -1
            return
        try:
            pa = pyaudio.PyAudio()
            rate, chunk_frames = 16000, 1600  # 0.1 秒一块
            stream = pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=rate,
                input=True,
                frames_per_buffer=chunk_frames,
            )
            chunks = []
            max_sec = 30
            while not self._stop_voice.is_set() and (len(chunks) * 0.1 < max_sec):
                try:
                    data = stream.read(chunk_frames, exception_on_overflow=False)
                    chunks.append(data)
                except Exception:
                    break
            stream.stop_stream()
            stream.close()
            pa.terminate()

            if len(chunks) < 5:
                self.state.append_chat("assistant", "（录音太短，请按住「语音」说话后松开）")
            else:
                audio_bytes = b"".join(chunks)
                # 可选降噪（需安装 noisereduce）
                try:
                    import config as _voice_cfg
                    if getattr(_voice_cfg, "VOICE_REDUCE_NOISE", False):
                        import numpy as np
                        import noisereduce as nr
                        arr = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
                        arr = nr.reduce_noise(y=arr, sr=rate, prop_decrease=0.8)
                        audio_bytes = (np.clip(arr, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()
                except ImportError:
                    pass
                except Exception:
                    pass
                try:
                    import config as _voice_cfg
                    engine = (getattr(_voice_cfg, "VOICE_RECOGNITION_ENGINE", "google") or "google").strip().lower()
                except Exception:
                    engine = "google"
                r = sr.Recognizer()
                audio = sr.AudioData(audio_bytes, rate, 2)
                text = None
                if engine == "whisper":
                    try:
                        text = r.recognize_whisper(audio, language="zh", model="base")
                    except AttributeError:
                        text = r.recognize_google(audio, language="zh-CN")
                    except Exception as e_whisper:
                        # Windows 上 Whisper 常因 WinError 127（DLL/依赖缺失或冲突）失败，回退到谷歌
                        try:
                            import sys
                            print(f"[语音] Whisper 失败，回退谷歌: {e_whisper}", file=sys.stderr)
                        except Exception:
                            pass
                        try:
                            text = r.recognize_google(audio, language="zh-CN")
                            self.state.append_chat("assistant", "（Whisper 不可用，已用谷歌识别；需联网）")
                        except Exception:
                            raise
                if text is None:
                    text = r.recognize_google(audio, language="zh-CN")
                if text and text.strip():
                    self.state.append_chat("user", text.strip())
                    self.state.append_chat("assistant", "已识别，正在处理…")
                    self.state.set_pending_chat(text.strip())
                else:
                    self.state.append_chat("assistant", "（未识别到内容，请重试）")
        except Exception as e:
            self.state.append_chat("assistant", f"（语音识别异常: {str(e)[:40]}）")
        finally:
            self._voice_recording = False
        self._last_history_len = -1

    def _play_audio_in_app(self, path: str) -> None:
        """应用内播放音频，不弹窗。优先 pygame，其次 playsound，最后才用系统播放器。"""
        if not path or not os.path.isfile(path):
            return
        path = os.path.abspath(path)

        def _do() -> None:
            import time as _time
            # 1) 优先 pygame：Windows 下应用内播 MP3 通常可用
            try:
                import pygame
                if not pygame.mixer.get_init():
                    pygame.mixer.init(frequency=44100, size=-16, channels=2)
                pygame.mixer.music.load(path)
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy():
                    _time.sleep(0.05)
                return
            except ImportError:
                pass
            except Exception as e:
                _log_play_error("pygame", path, e)
            # 2) 其次 playsound
            try:
                import playsound
                playsound.playsound(path, block=True)
                return
            except ImportError:
                pass
            except Exception as e:
                _log_play_error("playsound", path, e)
            # 3) 最后才用系统播放器（会弹窗）
            if os.name == "nt":
                try:
                    os.startfile(path)
                except Exception as e2:
                    _log_play_error("startfile", path, e2)

        def _log_play_error(method: str, p: str, err: Exception) -> None:
            try:
                import sys
                print(f"[播放] {method} 失败: {p!r} -> {err}", file=sys.stderr)
            except Exception:
                pass

        threading.Thread(target=_do, daemon=True).start()

    def update_from_state(self) -> None:
        """主循环每帧调用：仅当对话变化时重绘，避免不停刷新；带音频的消息显示「🔊 播放」可点击。"""
        if not self._root or not self._chat_text:
            return
        try:
            import time as time_mod
            history = self.state.get_chat_history()
            streaming = self.state.get_streaming_content()
            sig = str(len(history)) + (str(history[-1]) if history else "")
            if streaming is not None:
                sig += "_stream_%d" % len(streaming)  # 流式时随内容增长触发重绘，及时显示 LLM 输出
            if sig == self._last_history_sig:
                return
            self._last_history_sig = sig
            self._last_history_len = len(history)
            self._play_tag_to_path.clear()
            self._chat_text.configure(state=tk.NORMAL)
            self._chat_text.delete("1.0", tk.END)
            try:
                import config
                hint = getattr(config, "DIALOG_FEATURE_PROMPT", "")
            except Exception:
                hint = "在下方输入框打字，点「发送」或回车发送；按住「语音」说话，松开结束。"
            if not hint:
                hint = "在下方输入框打字，点「发送」或回车发送；按住「语音」说话，松开结束。"
            self._chat_text.insert(tk.END, hint.strip() + "\n\n")
            if history:
                self._chat_text.insert(tk.END, "────────── 对话 ──────────\n\n")
            play_idx = 0
            for item in history:
                role = item[0]
                text = item[1] if len(item) > 1 else ""
                ts = item[2] if len(item) > 2 else None
                audio_path = (item[3] if len(item) > 3 else "") or ""
                tstr = time_mod.strftime("%H:%M:%S", time_mod.localtime(ts)) if ts else ""
                prefix = ("我 " + tstr + "  ") if role == "user" else ("助手 " + tstr + "  ")
                lines = _wrap_text(text or "")
                for i, line in enumerate(lines):
                    self._chat_text.insert(tk.END, (prefix if i == 0 else "    ") + line + "\n")
                if audio_path and role == "assistant" and os.path.isfile(audio_path):
                    play_idx += 1
                    path_for_btn = audio_path
                    btn = tk.Button(
                        self._chat_text,
                        text=" 🔊 播放 ",
                        font=("Microsoft YaHei UI", 10, "bold"),
                        fg="#fff",
                        bg="#0066cc",
                        activeforeground="#fff",
                        activebackground="#0052a3",
                        relief=tk.FLAT,
                        padx=8,
                        pady=2,
                        cursor="hand2",
                        command=(lambda p=path_for_btn: self._play_audio_in_app(p)),
                    )
                    self._chat_text.insert(tk.END, " ")
                    self._chat_text.window_create(tk.END, window=btn)
                    self._chat_text.insert(tk.END, "\n")
                else:
                    self._chat_text.insert(tk.END, "\n")
            self._chat_text.see(tk.END)
            # 自动播放：若本条是刚追加的带音频消息，立即播放
            pending = self.state.get_and_clear_pending_play_audio()
            if pending and os.path.isfile(pending):
                self._play_audio_in_app(pending)
            # 保持 NORMAL 以便点击「播放」能触发
        except Exception:
            pass

    def update(self) -> None:
        """处理 tk 事件（主循环中调用），多处理几次保证打字和点击能响应。"""
        if self._root:
            try:
                self._root.update_idletasks()
                for _ in range(3):
                    self._root.update()
            except tk.TclError:
                pass

    def destroy(self) -> None:
        """关闭窗口。"""
        if self._root:
            try:
                self._root.destroy()
            except tk.TclError:
                pass
            self._root = None
