# -*- coding: utf-8 -*-
"""
系统管理窗口：关闭此窗口则退出整个程序；负责 Web/手机 服务启停与「打开语音助手」。
不修改现有桌面语音助手逻辑，仅作为统一入口与生命周期管理。
"""
from __future__ import annotations

import os
import subprocess
import tkinter as tk
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from shared_state import SharedState

# 项目根目录（与 server/main.py 一致）
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WEB_SERVER_PORT = 8000


class ManagerWindow:
    """系统管理：Web 服务启停、打开语音助手；关本窗口 = 退出整个程序。"""

    def __init__(
        self,
        state: "SharedState",
        on_open_voice_assistant: Callable[[], None],
        on_close_voice_assistant: Callable[[], None],
        is_voice_open: Callable[[], bool],
        title: str = "系统管理",
    ):
        self.state = state
        self._on_open_voice = on_open_voice_assistant
        self._on_close_voice = on_close_voice_assistant
        self._is_voice_open = is_voice_open
        self._title = title
        self._root: Optional[tk.Tk] = None
        self._status_label: Optional[tk.Label] = None
        self._btn_start: Optional[tk.Button] = None
        self._btn_stop: Optional[tk.Button] = None
        self._url_label: Optional[tk.Label] = None
        self._btn_voice: Optional[tk.Button] = None

    def build(self) -> tk.Tk:
        self._root = tk.Tk()
        self._root.title(self._title)
        self._root.configure(bg="#ffffff")
        self._root.geometry("420x260+100+100")
        self._root.minsize(380, 220)
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

        # 说明
        top = tk.Frame(self._root, bg="#f0f4f8", height=44)
        top.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(10, 6))
        top.pack_propagate(False)
        tk.Label(
            top,
            text="关闭本窗口将退出整个程序（含语音助手与 Web 服务）",
            font=("Microsoft YaHei UI", 9),
            fg="#666",
            bg="#f0f4f8",
        ).pack(anchor="w")

        # Web 服务
        frame_web = tk.LabelFrame(self._root, text="Web / 手机访问", font=("Microsoft YaHei UI", 10), bg="#ffffff", padx=10, pady=8)
        frame_web.pack(side=tk.TOP, fill=tk.X, padx=10, pady=6)
        row1 = tk.Frame(frame_web, bg="#ffffff")
        row1.pack(side=tk.TOP, fill=tk.X)
        self._status_label = tk.Label(row1, text="状态：已停止", font=("Microsoft YaHei UI", 10), fg="#333", bg="#ffffff")
        self._status_label.pack(side=tk.LEFT)
        self._btn_start = tk.Button(
            row1, text="启动", font=("Microsoft YaHei UI", 9), width=8,
            command=self._start_server, bg="#e8f5e9", cursor="hand2",
        )
        self._btn_start.pack(side=tk.LEFT, padx=(12, 4))
        self._btn_stop = tk.Button(
            row1, text="停止", font=("Microsoft YaHei UI", 9), width=8,
            command=self._stop_server, bg="#ffebee", state=tk.DISABLED, cursor="hand2",
        )
        self._btn_stop.pack(side=tk.LEFT)
        self._url_label = tk.Label(
            frame_web, text="本机: http://127.0.0.1:%d/  手机: http://本机IP:%d/" % (_WEB_SERVER_PORT, _WEB_SERVER_PORT),
            font=("Microsoft YaHei UI", 9), fg="#666", bg="#ffffff", wraplength=380,
        )
        self._url_label.pack(side=tk.TOP, anchor="w", pady=(6, 0))

        # 语音助手：一键打开/关闭，并做好初始化和退出，不影响 Web/手机端
        frame_voice = tk.Frame(self._root, bg="#ffffff")
        frame_voice.pack(side=tk.TOP, fill=tk.X, padx=10, pady=8)
        self._btn_voice = tk.Button(
            frame_voice, text="打开/关闭语音助手", font=("Microsoft YaHei UI", 10),
            command=self._on_voice_toggle, bg="#e3f2fd", cursor="hand2", padx=12, pady=6,
        )
        self._btn_voice.pack(side=tk.LEFT)

        # 关闭系统：停止所有服务并退出程序
        frame_exit = tk.Frame(self._root, bg="#ffffff")
        frame_exit.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(4, 10))
        tk.Button(
            frame_exit,
            text="关闭系统",
            font=("Microsoft YaHei UI", 10),
            command=self._on_close,
            bg="#ffcdd2",
            fg="#b71c1c",
            cursor="hand2",
            padx=16,
            pady=6,
        ).pack(side=tk.LEFT)

        self._root.lift()
        return self._root

    def _start_server(self) -> None:
        process = self.state.get_web_server_process()
        if process is not None:
            return
        try:
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            process = subprocess.Popen(
                ["python", "-m", "uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", str(_WEB_SERVER_PORT)],
                cwd=_ROOT,
                creationflags=creationflags,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.state.set_web_server_process(process)
            if self._status_label:
                self._status_label.config(text="状态：运行中 (port %d)" % _WEB_SERVER_PORT, fg="#2e7d32")
            if self._btn_start:
                self._btn_start.config(state=tk.DISABLED)
            if self._btn_stop:
                self._btn_stop.config(state=tk.NORMAL)
        except Exception:
            if self._status_label:
                self._status_label.config(text="状态：启动失败", fg="#c62828")

    def _stop_server(self) -> None:
        process = self.state.get_web_server_process()
        if process is not None:
            try:
                process.terminate()
                process.wait(timeout=5)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
            self.state.set_web_server_process(None)
        if self._status_label:
            self._status_label.config(text="状态：已停止", fg="#333")
        if self._btn_start:
            self._btn_start.config(state=tk.NORMAL)
        if self._btn_stop:
            self._btn_stop.config(state=tk.DISABLED)

    def _on_voice_toggle(self) -> None:
        """打开/关闭语音助手窗口：开则创建并初始化，关则销毁并清理状态，不影响 Web/手机。"""
        try:
            if self._is_voice_open():
                self._on_close_voice()
            else:
                self._on_open_voice()
        except Exception:
            pass
        self._update_voice_button_text()

    def _update_voice_button_text(self) -> None:
        # 按钮固定为「打开/关闭语音助手」，无需随状态切换文案
        pass

    def _on_close(self) -> None:
        """停止服务并请求退出；不在此处 destroy 窗口，由主循环退出后 finally 统一销毁，避免在事件回调里 destroy 导致卡死。"""
        self._stop_server()
        try:
            self.state.set_quit_requested(True)
        except Exception:
            pass

    def update_ui(self) -> None:
        """主循环可调：根据进程是否存在更新 Web 状态；并刷新语音助手按钮文案。"""
        if not self._root or not self._root.winfo_exists():
            return
        process = self.state.get_web_server_process()
        if process is not None and process.poll() is not None:
            self.state.set_web_server_process(None)
            if self._status_label:
                self._status_label.config(text="状态：已停止", fg="#333")
            if self._btn_start:
                self._btn_start.config(state=tk.NORMAL)
            if self._btn_stop:
                self._btn_stop.config(state=tk.DISABLED)
        self._update_voice_button_text()
