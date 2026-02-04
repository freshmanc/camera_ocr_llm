# -*- coding: utf-8 -*-
"""
主程序：主线程仅负责摄像头采集与画面刷新，OCR+LLM 在后台执行。
Agent D：每帧 try/except、摄像头断线重连、周期指标日志、可选 debug 存帧。
"""
import os
import sys

# 保证项目目录优先，避免与 site-packages 里的 tools 冲突（命令行/不同环境运行时易被顶掉）
_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)
# 清掉可能被别的环境提前注册的 tools，强制用本项目的
for _n in list(sys.modules):
    if _n == "tools" or _n.startswith("tools."):
        del sys.modules[_n]

import time

# 必须在首次 import paddle 之前设置，避免 Windows 上 oneDNN/PIR 报错
os.environ.setdefault("FLAGS_use_mkldnn", "0")
os.environ.setdefault("FLAGS_use_onednn", "0")

import cv2  # type: ignore[import-untyped]
import numpy as np
import config
from tools.overlay import build_display_lines, draw_text_block, wrap_text_for_display
from shared_state import SharedState
from worker import start_worker
from tools.logger_util import log, log_metrics, save_debug_frame
from tools.metrics import Metrics
from tools.ocr_engine import init_paddle_ocr_engine

# 白底黑字可交互对话窗口（打字 + 小麦克风）
_chat_window = None


def _open_camera():
    cap = cv2.VideoCapture(config.CAMERA_INDEX)
    if cap.isOpened():
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.CAMERA_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.CAMERA_HEIGHT)
    return cap


def main() -> int:
    # 切换到项目根目录并提前创建 logs，避免“找不到 log”或相对路径错误
    import os
    root = getattr(config, "_ROOT_DIR", None) or os.path.dirname(os.path.dirname(os.path.abspath(config.__file__)))
    if root and os.path.isdir(root):
        try:
            os.chdir(root)
        except Exception:
            pass
    log_dir = getattr(config, "LOG_DIR", None) or os.path.join(root or ".", "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
    except Exception:
        pass
    log("正在打开摄像头...")
    cap = _open_camera()
    if not cap.isOpened():
        log("无法打开摄像头，请检查设备或 CAMERA_INDEX", level="ERROR")
        return 1
    state = SharedState(fusion_frames=getattr(config, "OCR_FUSION_FRAMES", 0))
    metrics = Metrics()
    try:
        if not init_paddle_ocr_engine():
            log("PaddleOCR 预初始化失败，OCR 可能不可用；请重启程序再试", level="WARNING")
    except Exception as e:
        log(f"PaddleOCR 预初始化异常（OCR 可能不可用）: {e}", level="WARNING")
    start_worker(state, metrics)
    log("后台 OCR+LLM 已启动；主线程仅刷新画面。按 Q 退出。")
    win = "Camera OCR + LLM"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    if getattr(config, "ENABLE_VOICE_ASSISTANT", False):
        # 按路径强制加载本项目的 tools，避免被 site-packages 里的 tools 顶掉
        import importlib.util
        _tools_dir = os.path.join(_script_dir, "tools")
        for _n in list(sys.modules):
            if _n == "tools" or _n.startswith("tools."):
                del sys.modules[_n]
        if _script_dir not in sys.path:
            sys.path.insert(0, _script_dir)
        _spec = importlib.util.spec_from_file_location(
            "tools", os.path.join(_tools_dir, "__init__.py"),
            submodule_search_locations=[_tools_dir],
        )
        _tools_mod = importlib.util.module_from_spec(_spec)
        sys.modules["tools"] = _tools_mod
        _spec.loader.exec_module(_tools_mod)
        from tools.chat_window import ChatWindow
        global _chat_window
        _chat_window = ChatWindow(state, title="语音助手")
        _chat_window.build()
        log("语音助手已开启：白底黑字对话窗口，可打字、点「麦」语音，支持朗读/翻译/读音/例句")
    last_metrics_time = time.monotonic()
    last_fps = 0.0
    retries_left = getattr(config, "CAMERA_REOPEN_RETRIES", 3)
    try:
        while True:
            try:
                ret, frame = cap.read()
            except Exception as e:
                log(f"cap.read 异常: {e}", level="ERROR")
                save_debug_frame(frame if "frame" in dir() else None, "read_error")
                ret = False
            if not ret:
                log("读取帧失败，尝试重连摄像头...", level="ERROR")
                save_debug_frame(None, "camera_lost")
                cap.release()
                if retries_left <= 0:
                    log("摄像头重连次数用尽，退出", level="ERROR")
                    break
                time.sleep(getattr(config, "CAMERA_REOPEN_DELAY_SEC", 2))
                cap = _open_camera()
                if not cap.isOpened():
                    retries_left -= 1
                    continue
                retries_left = getattr(config, "CAMERA_REOPEN_RETRIES", 3)
                continue
            try:
                metrics.tick_frame()
                state.set_frame(frame)
                res = state.get_latest_result()
                lines = build_display_lines(
                    res.raw_ocr,
                    res.corrected,
                    res.confidence,
                    res.ocr_time_ms,
                    res.llm_time_ms,
                    res.ocr_ok,
                    res.llm_ok,
                    res.error_msg,
                    fps=last_fps,
                    debounced_ocr=res.debounced_ocr,
                    vision_llm_text=res.vision_llm_text or None,
                    cross_validated_text=res.cross_validated_text or None,
                )
                frame = draw_text_block(frame, lines, x=10, y=10, font_size=18, color_bgr=(0, 255, 0))
                cv2.imshow(win, frame)
                # 白底黑字对话窗口：每帧刷新并处理事件
                if _chat_window is not None:
                    _chat_window.update_from_state()
                    _chat_window.update()
            except Exception as e:
                log(f"主循环单帧异常: {e}", level="ERROR")
                save_debug_frame(frame, "frame_error")
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q") or key == ord("Q"):
                break
            # 用户指令：用当前纠错后内容执行读/翻译/读音/例句（无内容时仅朗读可触发，其余不请求 LLM）
            res = state.get_latest_result()
            content = (res.corrected or res.debounced_ocr or "").strip()
            key_r = getattr(config, "KEY_READ", ord("r"))
            key_t = getattr(config, "KEY_TRANSLATE", ord("t"))
            key_p = getattr(config, "KEY_PRONOUNCE", ord("p"))
            key_e = getattr(config, "KEY_EXAMPLES", ord("e"))
            if key == key_r or key == key_r - 32:
                state.set_pending_user_command("read", content)
            elif content and (key == key_t or key == key_t - 32):
                state.set_pending_user_command("translate", content)
            elif content and (key == key_p or key == key_p - 32):
                state.set_pending_user_command("pronounce", content)
            elif content and (key == key_e or key == key_e - 32):
                state.set_pending_user_command("examples", content)
            now = time.monotonic()
            if now - last_metrics_time >= getattr(config, "METRICS_LOG_INTERVAL_SEC", 30):
                fps, count = metrics.snapshot_fps()
                ocr_ms, llm_ms = metrics.get_last_ocr_llm_ms()
                pending = state.get_pending_frames_count()
                log_metrics(fps, ocr_ms, llm_ms, pending)
                last_fps = fps
                last_metrics_time = now
    except KeyboardInterrupt:
        log("用户中断")
    finally:
        if _chat_window is not None:
            try:
                _chat_window.destroy()
            except Exception:
                pass
        cap.release()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
