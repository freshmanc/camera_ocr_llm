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
        self._camera_btn: Optional[tk.Button] = None  # 打开/隐藏摄像头，需根据 state 更新文案
        self._ocr_label: Optional[tk.Label] = None    # 当前识别全文，减少画面遮挡时在此查看

    def set_content_for_command_callback(self, fn: Callable[[], str]) -> None:
        """可选：用于语音指令取当前识别内容（与 worker 一致）。"""
        self._get_content_for_command = fn

    def build(self) -> tk.Tk:
        self._root = tk.Tk()
        self._root.title(self.title)
        self._root.configure(bg="#ffffff")
        self._root.geometry("620x680+80+60")
        self._root.minsize(520, 520)
        # 关闭本窗口时通知主程序退出（主程序以语音助手窗口为主窗口）
        self._root.protocol("WM_DELETE_WINDOW", self._on_window_close)

        # 先放底部栏，保证输入框和「语音」始终在窗口底部可见
        bottom = tk.Frame(self._root, bg="#ffffff", height=56)
        bottom.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=(0, 8))
        bottom.pack_propagate(False)

        # 顶部：当前识别全文（设为 minimal/none 时在此查看，不挡摄像头）
        ocr_frame = tk.Frame(self._root, bg="#f5f5f5", height=52)
        ocr_frame.pack(side=tk.TOP, fill=tk.X, padx=8, pady=(8, 0))
        ocr_frame.pack_propagate(False)
        self._ocr_label = tk.Label(
            ocr_frame,
            text="当前识别：（无）",
            font=("Microsoft YaHei UI", 10),
            bg="#f5f5f5",
            fg="#333333",
            anchor="nw",
            justify=tk.LEFT,
            wraplength=580,
        )
        self._ocr_label.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

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

        # 上传文件（.txt / .pdf / .docx），内容会在下次发消息时一并发给 LLM
        upload_btn = tk.Button(
            bottom,
            text="上传",
            font=("Microsoft YaHei UI", 10),
            bg="#e8f5e9",
            fg="#000000",
            activebackground="#c8e6c9",
            relief=tk.RAISED,
            bd=1,
            padx=10,
            pady=6,
            cursor="hand2",
            command=self._on_upload,
        )
        upload_btn.pack(side=tk.LEFT, padx=(0, 4))

        # 打开/关闭摄像头与识别（按需启停，避免启动时报错）
        self._camera_btn = tk.Button(
            bottom,
            text="打开摄像头",
            font=("Microsoft YaHei UI", 10),
            bg="#fff3e0",
            fg="#000000",
            activebackground="#ffe0b2",
            relief=tk.RAISED,
            bd=1,
            padx=8,
            pady=6,
            cursor="hand2",
            command=self._on_toggle_camera,
        )
        self._camera_btn.pack(side=tk.LEFT, padx=(0, 4))

        # 截图识别：当前画面或选择图片，做一次 OCR+LLM 双重校验
        screenshot_btn = tk.Button(
            bottom,
            text="截图识别",
            font=("Microsoft YaHei UI", 10),
            bg="#e3f2fd",
            fg="#000000",
            activebackground="#bbdefb",
            relief=tk.RAISED,
            bd=1,
            padx=8,
            pady=6,
            cursor="hand2",
            command=self._on_screenshot_recognize,
        )
        screenshot_btn.pack(side=tk.LEFT, padx=(0, 4))

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

    def _on_window_close(self) -> None:
        """用户点击关闭：仅关闭本窗口，不退出程序；由「系统管理」窗口关闭时再退出。"""
        try:
            self.state.set_voice_window_closed(True)
        except Exception:
            pass
        try:
            if self._root and self._root.winfo_exists():
                self._root.destroy()
        except Exception:
            pass

    def close(self) -> None:
        """程序化关闭窗口（与用户点 X 一致）：仅关本窗口，做好状态与销毁，不影响 Web/手机端。"""
        self._on_window_close()

    def _on_toggle_camera(self) -> None:
        """切换摄像头与识别的启停：按需打开/关闭设备。"""
        try:
            on = self.state.toggle_camera_wanted()
            if self._camera_btn:
                self._camera_btn.config(text="关闭摄像头" if on else "打开摄像头")
        except Exception:
            pass

    def _on_screenshot_recognize(self) -> None:
        """截图识别：有当前画面则用当前帧，否则选图片文件，提交做一次 OCR+LLM。"""
        try:
            frame = self.state.get_current_frame()
            if frame is None:
                from tkinter import filedialog
                path = filedialog.askopenfilename(
                    title="选择图片（将做 OCR+LLM 识别）",
                    filetypes=[
                        ("图片", "*.png;*.jpg;*.jpeg;*.bmp;*.webp"),
                        ("全部", "*.*"),
                    ],
                )
                if not path:
                    return
                import cv2
                frame = cv2.imread(path)
                if frame is None:
                    self.state.append_chat("assistant", "（无法读取该图片，请换一张）")
                    return
            self.state.set_pending_screenshot(frame)
            self.state.append_chat("assistant", "已提交截图，正在 OCR+LLM 识别…")
            self._last_history_len = -1
        except Exception as e:
            try:
                self.state.append_chat("assistant", "（截图识别失败: " + str(e)[:60] + "）")
            except Exception:
                pass

    def _on_upload(self) -> None:
        """选择 .txt / .pdf / .docx 文件，读取后设为「上传文件」，下次发消息时一并发给 LLM。"""
        try:
            from tkinter import filedialog
            path = filedialog.askopenfilename(
                title="选择文件（将供老师/LLM 识别）",
                filetypes=[
                    ("文本 / PDF / Word", "*.txt;*.pdf;*.docx;*.doc"),
                    ("文本", "*.txt"),
                    ("PDF", "*.pdf"),
                    ("Word", "*.docx;*.doc"),
                    ("全部", "*.*"),
                ],
            )
            if not path:
                return
            from tools.file_util import read_file_as_text
            ok, text_or_err = read_file_as_text(path)
            if not ok:
                self.state.append_chat("assistant", f"（上传失败: {text_or_err}）")
            else:
                name = os.path.basename(path)
                self.state.set_uploaded_file(name, text_or_err)
                self.state.append_chat("assistant", f"已收到文件「{name}」，请说或输入你的问题（如：翻译、精讲、根据文件出题等）。")
            self._last_history_len = -1
        except Exception as e:
            self.state.append_chat("assistant", f"（上传异常: {str(e)[:60]}）")
            self._last_history_len = -1

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
                        # Windows 上 Whisper 常因 WinError 127（DLL/依赖缺失）失败，静默回退到谷歌
                        try:
                            from tools.logger_util import log
                            log("语音识别回退到谷歌（Whisper 不可用）", level="DEBUG")
                        except Exception:
                            pass
                        try:
                            text = r.recognize_google(audio, language="zh-CN")
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
        """主循环每帧调用：仅当对话变化时重绘，避免不停刷新；带音频的消息显示「🔊 播放」可点击；更新摄像头按钮与当前识别。"""
        if not self._root or not self._chat_text:
            return
        try:
            if not self._root.winfo_exists():
                return
        except tk.TclError:
            return
        try:
            # 更新「打开/关闭摄像头」按钮文案（与主循环的启停一致）
            if self._camera_btn:
                try:
                    on = self.state.get_camera_wanted()
                    self._camera_btn.config(text="关闭摄像头" if on else "打开摄像头")
                except Exception:
                    pass
            # 更新「当前识别」区域（全文在此显示时可减少画面遮挡）
            if self._ocr_label:
                try:
                    res = self.state.get_latest_result()
                    txt = (res.corrected or res.debounced_ocr or "").strip()
                    display = (txt[:300] + "…") if len(txt) > 300 else (txt or "（无）")
                    self._ocr_label.config(text="当前识别：" + (display or "（无）"))
                except Exception:
                    pass
            import time as time_mod
            history = self.state.get_chat_history()
            streaming = self.state.get_streaming_content()
            # 用长度 + 最后一条的角色与内容长度做签名，避免 str(history[-1]) 编码或过长导致漏刷
            if history:
                last = history[-1]
                role = last[0] if len(last) > 0 else ""
                text_len = len((last[1] or "") if len(last) > 1 else "")
                sig = "%d_%s_%d" % (len(history), role, text_len)
            else:
                sig = "0"
            if streaming is not None:
                sig += "_stream_%d" % len(streaming)
            if sig == self._last_history_sig:
                return
            self._last_history_sig = sig
            self._last_history_len = len(history)
            self._play_tag_to_path.clear()
            self._chat_text.configure(state=tk.NORMAL)
            self._chat_text.delete("1.0", tk.END)
            try:
                import config
                hint = getattr(config, "DIALOG_FEATURE_PROMPT", "") or ""
                if getattr(config, "FRENCH_TEACHING_MODE", False):
                    extra = getattr(config, "DIALOG_FRENCH_TEACHING_PROMPT", "") or ""
                    if extra:
                        hint = (hint.strip() + "\n" + extra.strip()).strip()
            except Exception:
                hint = "在下方输入框打字，点「发送」或回车发送；按住「语音」说话，松开结束。"
            if not hint:
                hint = "在下方输入框打字，点「发送」或回车发送；按住「语音」说话，松开结束。"
            self._chat_text.insert(tk.END, hint.strip() + "\n\n")
            if history:
                self._chat_text.insert(tk.END, "────────── 对话 ──────────\n\n")
            play_idx = 0
            for item in history:
                try:
                    role = str(item[0]) if item else "user"
                    text = item[1] if len(item) > 1 else ""
                    try:
                        text = str(text).strip() if text is not None else ""
                    except Exception:
                        text = ""
                    ts = item[2] if len(item) > 2 else None
                    try:
                        tstr = time_mod.strftime("%H:%M:%S", time_mod.localtime(ts)) if ts is not None else ""
                    except Exception:
                        tstr = ""
                    audio_path = (item[3] if len(item) > 3 else "") or ""
                    audio_path = str(audio_path) if audio_path else ""
                    prefix = ("我 " + tstr + "  ") if role == "user" else ("助手 " + tstr + "  ")
                    content = text
                    if role == "assistant":
                        try:
                            content = _ensure_paragraph_breaks(content)
                        except Exception:
                            pass
                    try:
                        lines = _wrap_text(content)
                    except Exception:
                        lines = [content[:500]] if content else [""]
                    for i, line in enumerate(lines):
                        try:
                            line_str = str(line) if line is not None else ""
                            if line_str == "":
                                self._chat_text.insert(tk.END, "\n")
                            else:
                                self._chat_text.insert(tk.END, (prefix if i == 0 else "    ") + line_str + "\n")
                        except tk.TclError:
                            try:
                                raw = str(line) if line is not None else ""
                                safe = (prefix if i == 0 else "    ") + raw.encode("ascii", errors="replace").decode("ascii")
                                self._chat_text.insert(tk.END, safe + "\n")
                            except Exception:
                                self._chat_text.insert(tk.END, (prefix if i == 0 else "    ") + "(内容略)\n")
                        except Exception:
                            self._chat_text.insert(tk.END, (prefix if i == 0 else "    ") + "(内容略)\n")
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
                except Exception:
                    # 单条渲染失败不影响其余消息，至少插入占位
                    try:
                        self._chat_text.insert(tk.END, "(该条无法显示)\n")
                    except Exception:
                        pass
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
