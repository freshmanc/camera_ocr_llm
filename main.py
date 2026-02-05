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
from tools.overlay import build_display_lines, build_display_lines_compact, draw_text_block, wrap_text_for_display
from shared_state import SharedState
from worker import start_worker, shutdown_ocr_process_pool
from tools.logger_util import log, log_metrics, save_debug_frame
from tools.metrics import Metrics
from tools.ocr_engine import init_paddle_ocr_engine

# 系统管理窗口：关闭即退出整个程序，并管理 Web 服务
_manager_window = None
# 语音助手窗口：关闭仅关本窗口，不退出程序；可从管理窗口再次打开
_chat_window = None
# 摄像头隐藏时的占位图（仅用于 show_camera_window 隐藏时的占位）
_placeholder_frame = None

# 摄像头窗口标题（仅在实际打开摄像头时创建/显示，关闭时销毁）
_CAMERA_WIN_NAME = "Camera OCR + LLM"


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
    state = SharedState(fusion_frames=getattr(config, "OCR_FUSION_FRAMES", 0))
    state.set_show_camera_window(getattr(config, "CAMERA_WINDOW_START_VISIBLE", True))
    # 按需启停：默认不打开摄像头，按 C 键或点对话窗口按钮再开
    state.set_camera_wanted(not getattr(config, "CAMERA_START_OFF", True))
    cap = None
    metrics = Metrics()
    try:
        if not init_paddle_ocr_engine():
            log("PaddleOCR 预初始化失败，OCR 可能不可用；请重启程序再试", level="WARNING")
    except Exception as e:
        log(f"PaddleOCR 预初始化异常（OCR 可能不可用）: {e}", level="WARNING")
    start_worker(state, metrics)
    key_toggle = getattr(config, "KEY_TOGGLE_CAMERA", ord("c"))
    log("后台已启动。按 C 键或点对话窗口「打开/关闭摄像头」启停识别，按 Q 退出。")
    win = _CAMERA_WIN_NAME
    # 摄像头窗口不在此创建，在首次打开摄像头时再创建，关闭时销毁
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
        from tools.manager_window import ManagerWindow
        global _manager_window, _chat_window

        def _open_voice_assistant():
            global _chat_window
            try:
                if _chat_window is not None and _chat_window._root and _chat_window._root.winfo_exists():
                    _chat_window._root.lift()
                    return
            except Exception:
                pass
            try:
                _chat_window = ChatWindow(state, title="语音助手")
                _chat_window.build()
                if _chat_window._root:
                    _chat_window._root.lift()
                log("语音助手已打开")
            except Exception as e:
                log(f"打开语音助手失败: {e}", level="ERROR")

        def _close_voice_assistant():
            global _chat_window
            if _chat_window is None:
                return
            try:
                _chat_window.close()
            except Exception:
                pass
            _chat_window = None

        def _is_voice_open():
            global _chat_window
            if _chat_window is None:
                return False
            try:
                return _chat_window._root is not None and _chat_window._root.winfo_exists()
            except Exception:
                return False

        _manager_window = ManagerWindow(
            state,
            on_open_voice_assistant=_open_voice_assistant,
            on_close_voice_assistant=_close_voice_assistant,
            is_voice_open=_is_voice_open,
            title="系统管理",
        )
        _manager_window.build()
        log("系统管理窗口已开启：关闭本窗口将退出整个程序；可在此启停 Web/手机 服务。")
        _chat_window = ChatWindow(state, title="语音助手")
        _chat_window.build()
        log("语音助手已开启：白底黑字对话窗口，可打字、点「麦」语音，支持朗读/翻译/读音/例句")
    last_metrics_time = time.monotonic()
    last_fps = 0.0
    retries_left = getattr(config, "CAMERA_REOPEN_RETRIES", 3)
    try:
        while True:
            if state.get_quit_requested():
                break
            if state.get_and_clear_voice_window_closed():
                _chat_window = None
                log("语音助手已关闭")
            if _manager_window is not None:
                try:
                    _manager_window.update_ui()
                    if _manager_window._root and _manager_window._root.winfo_exists():
                        _manager_window._root.update()
                except Exception:
                    pass
            camera_wanted = state.get_camera_wanted()
            key = cv2.waitKey(1) & 0xFF

            # 按 C 键切换摄像头开关
            if key == key_toggle or key == key_toggle - 32:
                state.set_camera_wanted(not camera_wanted)
                camera_wanted = state.get_camera_wanted()
                log("摄像头已开启" if camera_wanted else "摄像头已关闭")
                if not camera_wanted:
                    if cap is not None:
                        cap.release()
                        cap = None
                    try:
                        cv2.destroyWindow(win)
                    except Exception:
                        pass
                    if _chat_window is not None:
                        _chat_window.update_from_state()
                        _chat_window.update()
                    if state.get_quit_requested():
                        break
                    continue

            if not camera_wanted:
                # 未开启：确保设备与窗口已释放/关闭
                if cap is not None:
                    cap.release()
                    cap = None
                try:
                    cv2.destroyWindow(win)
                except Exception:
                    pass
                if _chat_window is not None:
                    _chat_window.update_from_state()
                    _chat_window.update()
                if state.get_quit_requested():
                    break
                if key == ord("q") or key == ord("Q"):
                    break
                now = time.monotonic()
                if now - last_metrics_time >= getattr(config, "METRICS_LOG_INTERVAL_SEC", 30):
                    last_metrics_time = now
                continue

            # 需要摄像头：若未打开则打开，并创建窗口
            if cap is None:
                cap = _open_camera()
                if not cap.isOpened():
                    log("无法打开摄像头，请检查设备或 CAMERA_INDEX", level="ERROR")
                    state.set_camera_wanted(False)
                    cap = None
                    continue
                cv2.namedWindow(win, cv2.WINDOW_NORMAL)
                cv2.resizeWindow(win, config.CAMERA_WIDTH, config.CAMERA_HEIGHT)
                retries_left = getattr(config, "CAMERA_REOPEN_RETRIES", 3)

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
                cap = None
                if retries_left <= 0:
                    log("摄像头重连次数用尽，已关闭", level="ERROR")
                    state.set_camera_wanted(False)
                    continue
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
                display_mode = getattr(config, "OCR_DISPLAY_ON_CAMERA", "full") or "full"
                if display_mode == "none":
                    lines = []
                elif display_mode == "minimal":
                    lines = build_display_lines_compact(
                        res.raw_ocr,
                        res.corrected,
                        res.confidence,
                        res.ocr_time_ms,
                        res.llm_time_ms,
                        fps=last_fps,
                        debounced_ocr=res.debounced_ocr,
                    )
                    h, w = frame.shape[:2]
                    frame = draw_text_block(frame, lines, x=max(10, w - 520), y=max(10, h - 80), font_size=14, color_bgr=(0, 255, 0))
                else:
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
                show_camera = state.get_show_camera_window()
                if show_camera:
                    cv2.imshow(win, frame)
                else:
                    global _placeholder_frame
                    if _placeholder_frame is None or _placeholder_frame.shape[:2] != frame.shape[:2]:
                        _placeholder_frame = np.zeros((frame.shape[0], frame.shape[1], 3), dtype=np.uint8)
                        _placeholder_frame[:] = (36, 36, 36)
                        _placeholder_frame = draw_text_block(
                            _placeholder_frame,
                            ["摄像头已隐藏", "点击对话窗口「打开摄像头」恢复识别"],
                            x=24, y=24, font_size=20, color_bgr=(180, 180, 180),
                        )
                    cv2.imshow(win, _placeholder_frame)
            except Exception as e:
                log(f"主循环单帧异常: {e}", level="ERROR")
                save_debug_frame(frame, "frame_error")
            if _chat_window is not None:
                _chat_window.update_from_state()
                _chat_window.update()
            if state.get_quit_requested():
                break
            if key == ord("q") or key == ord("Q"):
                break
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
        try:
            shutdown_ocr_process_pool()
        except Exception:
            pass
        proc = state.get_web_server_process()
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            state.set_web_server_process(None)
        if _manager_window is not None:
            try:
                if _manager_window._root and _manager_window._root.winfo_exists():
                    _manager_window._root.destroy()
            except Exception:
                pass
        if _chat_window is not None:
            try:
                _chat_window.destroy()
            except Exception:
                pass
        if cap is not None:
            cap.release()
        try:
            cv2.destroyWindow(win)
        except Exception:
            pass
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    code = main()
    # 强制退出进程，避免 ProcessPoolExecutor/Tk 等非 daemon 线程阻塞导致终端无法回到命令行
    os._exit(code)
