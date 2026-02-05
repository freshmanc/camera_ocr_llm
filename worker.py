# -*- coding: utf-8 -*-
"""
后台管道：仅保留最新帧/最新结果（单槽覆盖），OCR 与 LLM 在线程池执行；
LLM 使用 Future.result(timeout) 与熔断，失败降级返回原文，主线程永不阻塞。
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Optional

import config
from agents.agent_e import LLMCache, LLMThrottler
from agents.debounce import OCRDebouncer
from agents.llm_correct import correct_with_llm
from tools.logger_util import log_result
from tools.ocr_engine import run_ocr
from shared_state import SharedState
from agents.tts_agent import speak as tts_speak, speak_immediate as tts_speak_immediate, generate_tts_file


class _CircuitBreaker:
    """熔断：连续失败 N 次后，在 cooldown 秒内不再调用 LLM，直接降级返回原文。"""

    def __init__(
        self,
        failure_threshold: int,
        cooldown_sec: float,
    ):
        self._lock = threading.Lock()
        self._failure_threshold = failure_threshold
        self._cooldown_sec = cooldown_sec
        self._consecutive_failures = 0
        self._last_failure_time: float = 0.0

    def record_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0

    def record_failure(self) -> None:
        with self._lock:
            self._consecutive_failures += 1
            self._last_failure_time = time.monotonic()

    def is_open(self) -> bool:
        with self._lock:
            if self._consecutive_failures < self._failure_threshold:
                return False
            return (time.monotonic() - self._last_failure_time) < self._cooldown_sec


def _run_ocr_safe(frame) -> "tuple[str, float, float, bool, str | None]":
    """在线程池中运行 OCR，返回 (raw_text, confidence, time_ms, success, error_msg)。"""
    r = run_ocr(frame)
    return (r.text, r.confidence, r.time_ms, r.success, r.error_msg)


def _run_llm_safe(raw_text: str) -> "tuple[str, float, bool, str | None]":
    """在线程池中运行 LLM，返回 (corrected_text, time_ms, success, error_msg)。"""
    r = correct_with_llm(raw_text)
    return (r.corrected_text, r.time_ms, r.success, r.error_msg)


def _run_vision_and_cross_validate(state: SharedState, corrected_text: str) -> None:
    """用当前缓存的帧跑视觉 LLM，与 corrected 做交叉验证并写入 state。"""
    if not getattr(config, "ENABLE_VISION_LLM", False):
        return
    frame = state.get_and_clear_last_ocr_frame()
    if frame is None:
        return
    try:
        from agents.vision_llm_agent import extract_text_from_image, merge_ocr_and_vision_with_llm
        vision_text = extract_text_from_image(frame)
        mode = getattr(config, "CROSS_VALIDATE_MODE", "show_both")
        if mode == "prefer_ocr":
            cross = corrected_text.strip()
        elif mode == "prefer_vision":
            cross = vision_text
        elif mode == "merge_llm":
            cross = merge_ocr_and_vision_with_llm(corrected_text.strip(), vision_text)
        else:
            cross = corrected_text.strip()  # show_both 时交叉结果仍以 OCR 为主，vision 单独显示
        state.set_vision_and_cross_validated(vision_text, cross)
    except Exception:
        pass


def _pipeline_loop(
    state: SharedState,
    executor: ThreadPoolExecutor,
    circuit_breaker: _CircuitBreaker,
    debouncer: OCRDebouncer,
    metrics: Optional["Metrics"] = None,
    cache: Optional[LLMCache] = None,
    throttler: Optional[LLMThrottler] = None,
) -> None:
    """管道循环：只取最新帧（单槽），OCR → 去抖动 → LLM（缓存+节流+熔断），写回最新结果；并处理用户指令（R/T/P/E）。"""
    from tools.logger_util import log, save_debug_frame
    last_llm_lang_hint: Optional[str] = None
    last_sent_text: Optional[str] = None
    last_corrected: Optional[str] = None
    # LLM 异步：不阻塞管道，提交后立即继续做 OCR，结果在下一轮合并
    pending_llm: Optional[tuple] = None  # (future, stable_text, conf, ocr_ms, display_raw, err_msg)

    while True:
        # 用户指令 Agent：读/翻译/读音/例句（主线程已 set_pending_user_command），放入线程执行避免阻塞 OCR
        cmd, content = state.get_and_clear_pending_command()
        if cmd:
            def _run_user_command():
                if cmd == "read":
                    # 朗读改为生成音频文件并写入对话，由对话框内「🔊 播放」点击播放，不调用系统播放器
                    try:
                        path = generate_tts_file(content or "")
                        if path:
                            state.append_chat("assistant", "正在朗读。", audio_path=path)
                        else:
                            state.append_chat("assistant", "（朗读生成失败或暂无文字）")
                    except Exception:
                        state.append_chat("assistant", "（朗读生成失败）")
                elif content:
                    from agents.user_command_agents import (
                        translate_with_llm,
                        pronunciation_with_llm,
                        examples_with_llm,
                    )
                    if cmd == "translate":
                        result = translate_with_llm(content)
                        state.set_explanation("翻译", result)
                        state.append_chat("assistant", "【翻译】\n" + (result or "（无结果）"))
                    elif cmd == "pronounce":
                        result = pronunciation_with_llm(content)
                        state.set_explanation("读音", result)
                        state.append_chat("assistant", "【读音】\n" + (result or "（无结果）"))
                    elif cmd == "examples":
                        result = examples_with_llm(content)
                        state.set_explanation("例句", result)
                        state.append_chat("assistant", "【例句】\n" + (result or "（无结果）"))
            threading.Thread(target=_run_user_command, daemon=True).start()

        # 语音助手 Agent：用户消息已由 main 显示；此处只做“正在理解”提示并在线程中调 LLM，不阻塞 OCR
        if getattr(config, "ENABLE_VOICE_ASSISTANT", False):
            pending_chat = state.get_and_clear_pending_chat()
            if pending_chat:
                msg = (pending_chat or "").strip()
                content, confidence = state.get_content_and_confidence_for_command()
                keywords = getattr(config, "VOICE_READ_COMMAND_KEYWORDS", ("读一下", "读出来", "朗读", "读一下视频"))
                conf_thresh = getattr(config, "VOICE_READ_DIRECT_CONFIDENCE", 0.0)
                is_read_cmd = any(k in msg for k in keywords)
                # 「读一下」且有画面文字时优先直接朗读，不走 LLM，保证顺序正确且立刻有音频
                if is_read_cmd and content and (confidence >= conf_thresh if conf_thresh > 0 else True):
                    try:
                        # 语言检测优先用 debounced_ocr（可能保留重音），避免纠错后丢重音被读成英语
                        content_for_lang = state.get_content_for_tts_lang_detect()
                        path = generate_tts_file(content, lang_detect_text=content_for_lang or None)
                        if path:
                            _content_preview = (content[:600] + "…") if len(content) > 600 else content
                            state.set_last_read_content(content)
                            state.append_chat("assistant", "正在朗读。\n【内容】\n" + _content_preview, audio_path=path)
                        else:
                            state.append_chat("assistant", "（朗读生成失败或暂无文字）")
                    except Exception:
                        state.append_chat("assistant", "（朗读生成失败）")
                else:
                    history = state.get_chat_history()
                    last_user_idx = None
                    for i in range(len(history) - 1, -1, -1):
                        if history[i][0] == "user":
                            last_user_idx = i
                            break
                    raw = (
                        history[:last_user_idx]
                        if last_user_idx is not None
                        else (history[:-1] if history else [])
                    )
                    recent = [(h[0], h[1]) for h in raw] if raw else []
                    content = state.get_content_for_command()

                    if getattr(config, "VOICE_ASSISTANT_DIRECT_LLM", False):
                        # 直接对接 LLM：流式（VOICE_ASSISTANT_USE_STREAM=True）边收边显示；否则一次性请求
                        state.start_streaming()
                        use_stream = getattr(config, "VOICE_ASSISTANT_USE_STREAM", True)
                        def _run_direct_llm():
                            try:
                                if use_stream:
                                    from agents.voice_assistant_agent import chat_direct_llm_stream
                                    reply = chat_direct_llm_stream(
                                        pending_chat,
                                        recent if recent else None,
                                        content,
                                        on_chunk=state.append_streaming_delta,
                                    )
                                else:
                                    from agents.voice_assistant_agent import chat_direct_llm
                                    reply = chat_direct_llm(pending_chat, recent if recent else None, content)
                                state.finish_streaming(reply)
                            except Exception as e:
                                state.finish_streaming(f"(助手出错: {str(e)[:50]})")
                        threading.Thread(target=_run_direct_llm, daemon=True).start()
                    else:
                        # 原有逻辑：意图解析 + [ACTION:xxx]
                        state.append_chat("assistant", "正在理解并执行…")
                        def _run_chat_assistant():
                            try:
                                from agents.voice_assistant_agent import chat_with_assistant
                                reply, action = chat_with_assistant(pending_chat, recent if recent else None)
                                if action == "read":
                                    content_for_cmd = state.get_content_for_command()
                                    content_for_lang = state.get_content_for_tts_lang_detect()
                                    path = generate_tts_file(content_for_cmd or "", lang_detect_text=content_for_lang or None)
                                    if path:
                                        _txt = (content_for_cmd or "")[:600]
                                        if len(content_for_cmd or "") > 600:
                                            _txt += "…"
                                        state.set_last_read_content(content_for_cmd or "")
                                        state.append_chat("assistant", "正在朗读。\n【内容】\n" + _txt, audio_path=path)
                                    else:
                                        state.append_chat("assistant", reply or "（朗读生成失败）")
                                else:
                                    state.append_chat("assistant", reply)
                                    if action == "translate_previous":
                                        content_prev = state.get_last_read_content()
                                        if content_prev:
                                            from agents.user_command_agents import translate_with_llm
                                            result = translate_with_llm(content_prev)
                                            state.append_chat("assistant", "【翻译】（上一句）\n" + (result or "（无结果）"))
                                        else:
                                            state.append_chat("assistant", "（没有之前的朗读内容可翻译，请先「读一下」或说「翻译」翻译当前画面）")
                                    elif action and action in ("translate", "pronounce", "examples"):
                                        content_for_cmd = state.get_content_for_command()
                                        state.set_pending_user_command(action, content_for_cmd)
                                    elif action == "send_ocr_result":
                                        content_c = state.get_content_for_command()
                                        if content_c:
                                            state.append_chat("assistant", "当前识别到的文字：\n" + content_c)
                                        else:
                                            state.append_chat("assistant", "（当前画面暂无识别到文字，请对准文字后再试）")
                            except Exception as e:
                                state.append_chat("assistant", f"(助手出错: {str(e)[:50]})")
                        threading.Thread(target=_run_chat_assistant, daemon=True).start()

        # 若有未完成的 LLM 请求，先看是否已完成（不阻塞）
        if pending_llm is not None:
            future_llm, pending_stable, pending_conf, pending_ocr_ms, pending_display, pending_err = pending_llm
            if future_llm.done():
                try:
                    corrected, llm_ms, llm_ok, llm_err = future_llm.result(timeout=0)
                except Exception as e:
                    corrected, llm_ms, llm_ok, llm_err = pending_stable, 0.0, False, str(e)
                if llm_ok:
                    circuit_breaker.record_success()
                    last_sent_text = pending_stable
                    last_corrected = corrected
                    if cache is not None and pending_stable.strip():
                        try:
                            cache.put(
                                text=pending_stable,
                                lang_hint=last_llm_lang_hint,
                                corrected=corrected,
                                confidence=None,
                                language_hint=None,
                                llm_ms=llm_ms,
                            )
                        except Exception:
                            pass
                else:
                    circuit_breaker.record_failure()
                combined_err = " ".join(filter(None, [pending_err, llm_err])) or None
                if metrics is not None:
                    try:
                        metrics.set_ocr_llm_ms(pending_ocr_ms, llm_ms)
                    except Exception:
                        pass
                _run_vision_and_cross_validate(state, corrected)
                state.set_latest_result(
                    raw_ocr=pending_display,
                    corrected=corrected,
                    confidence=pending_conf,
                    ocr_time_ms=pending_ocr_ms,
                    llm_time_ms=llm_ms,
                    ocr_ok=True,
                    llm_ok=llm_ok,
                    error_msg=combined_err,
                    debounced_ocr=pending_stable,
                )
                if config.LOG_TO_FILE and pending_stable.strip():
                    log_result(pending_stable, corrected, pending_conf, pending_ocr_ms, llm_ms)
                if getattr(config, "ENABLE_TTS", False) and corrected.strip():
                    try:
                        tts_speak(corrected)
                    except Exception:
                        pass
                pending_llm = None

        try:
            frame = state.get_frame_for_ocr(
                config.FRAME_SKIP,
                fusion_frames=getattr(config, "OCR_FUSION_FRAMES", 0),
                motion_stable_enabled=getattr(config, "OCR_MOTION_STABLE_ENABLED", False),
                motion_threshold=float(getattr(config, "OCR_MOTION_STABLE_THRESHOLD", 20.0)),
            )
        except Exception as e:
            log(f"get_frame_for_ocr 异常: {e}", level="ERROR")
            time.sleep(0.2)
            continue
        if frame is None:
            time.sleep(0.05)
            continue

        # 存当前帧供视觉 LLM 与 OCR 交叉验证用
        state.set_last_ocr_frame(frame)

        # OCR 在池中执行，带超时
        try:
            future_ocr = executor.submit(_run_ocr_safe, frame)
            raw_text, conf, ocr_ms, ocr_ok, err_msg = future_ocr.result(
                timeout=config.OCR_FUTURE_TIMEOUT_SEC
            )
        except (FuturesTimeoutError, Exception) as e:
            raw_text, conf, ocr_ms = "", 0.0, 0.0
            ocr_ok = False
            err_msg = str(e)
            log(f"OCR 异常/超时: {e}", level="ERROR")
            save_debug_frame(frame, "ocr_error")

        # 去抖动：用最近 N 次中多数/稳定结果作为显示与 LLM 输入
        debouncer.add(raw_text if ocr_ok else "")
        stable_text = debouncer.get_stable()
        is_stable = debouncer.is_stable()
        # 软稳定：当前帧与稳定文本相似度高，也视为已“识别完成”，触发 LLM
        soft_stable = is_stable
        if getattr(config, "OCR_SOFT_STABLE_ENABLED", True) and stable_text and raw_text:
            from agents.debounce import text_similarity

            sim = text_similarity(stable_text, raw_text)
            if sim >= getattr(config, "OCR_SOFT_STABLE_SIMILARITY", 0.85):
                soft_stable = True

        # 原始 OCR 一有结果就显示：raw_ocr 用当前帧识别结果 raw_text，不等到去抖
        display_raw = raw_text if ocr_ok else (stable_text or "(OCR失败)")

        if not ocr_ok:
            # OCR 失败时把具体错误写入日志（引擎内部异常不会抛到 result()，只会在 error_msg 里）
            if err_msg:
                log(f"OCR 失败: {err_msg}", level="ERROR")
            state.set_latest_result(
                raw_ocr=display_raw,
                corrected=stable_text or "(OCR失败)",
                confidence=0.0,
                ocr_time_ms=ocr_ms,
                llm_time_ms=0.0,
                ocr_ok=False,
                llm_ok=True,
                error_msg=err_msg,
                debounced_ocr=stable_text or "",
            )
            if config.LOG_TO_FILE and (raw_text or err_msg):
                log_result(raw_text or "", stable_text or "", 0.0, ocr_ms, 0.0)
            time.sleep(0.05)
            continue

        # 无有效文本或文本尚未稳定：只更新显示（原始OCR用当前帧结果），不请求 LLM
        if not (stable_text and stable_text.strip()) or not soft_stable:
            state.set_latest_result(
                raw_ocr=display_raw,
                corrected=raw_text,
                confidence=conf,
                ocr_time_ms=ocr_ms,
                llm_time_ms=0.0,
                ocr_ok=True,
                llm_ok=True,
                error_msg=None,
                debounced_ocr=stable_text,
            )
            time.sleep(0.05)
            continue

        # Agent E：缓存命中则直接使用，不重复请求 LLM
        cache_entry = cache.get(stable_text, last_llm_lang_hint) if cache is not None else None
        if cache_entry is not None:
            corrected = cache_entry["corrected"]
            llm_ms = float(cache_entry.get("llm_ms", 0.0))
            combined_err = err_msg
            if metrics is not None:
                try:
                    metrics.set_ocr_llm_ms(ocr_ms, llm_ms)
                except Exception:
                    pass
            _run_vision_and_cross_validate(state, corrected)
            state.set_latest_result(
                raw_ocr=display_raw,
                corrected=corrected,
                confidence=conf,
                ocr_time_ms=ocr_ms,
                llm_time_ms=llm_ms,
                ocr_ok=True,
                llm_ok=True,
                error_msg=combined_err,
                debounced_ocr=stable_text,
            )
            if config.LOG_TO_FILE and stable_text.strip():
                log_result(stable_text, corrected, conf, ocr_ms, llm_ms)
            if getattr(config, "ENABLE_TTS", False) and corrected.strip():
                try:
                    tts_speak(corrected)
                except Exception:
                    pass
            time.sleep(0.05)
            continue

        # 文字与上次发给 LLM 的完全相同：不重复发，用上次纠错结果
        if last_sent_text is not None and last_corrected is not None and stable_text == last_sent_text:
            state.set_latest_result(
                raw_ocr=display_raw,
                corrected=last_corrected,
                confidence=conf,
                ocr_time_ms=ocr_ms,
                llm_time_ms=0.0,
                ocr_ok=True,
                llm_ok=True,
                error_msg=None,
                debounced_ocr=stable_text,
            )
            time.sleep(0.05)
            continue

        # 熔断打开则不再请求 LLM，直接返回原文
        if circuit_breaker.is_open():
            state.set_latest_result(
                raw_ocr=display_raw,
                corrected=stable_text,
                confidence=conf,
                ocr_time_ms=ocr_ms,
                llm_time_ms=0.0,
                ocr_ok=True,
                llm_ok=False,
                error_msg="LLM熔断中(降级返回原文)",
                debounced_ocr=stable_text,
            )
            time.sleep(0.05)
            continue

        # Agent E：节流，过于频繁则暂不请求 LLM，只显示原文
        if throttler is not None and not throttler.can_call():
            state.set_latest_result(
                raw_ocr=display_raw,
                corrected=stable_text,
                confidence=conf,
                ocr_time_ms=ocr_ms,
                llm_time_ms=0.0,
                ocr_ok=True,
                llm_ok=True,
                error_msg=None,
                debounced_ocr=stable_text,
            )
            time.sleep(0.05)
            continue

        # 已有 LLM 在途则只更新画面（原始/去抖），不重复提交
        if pending_llm is not None:
            state.set_latest_result(
                raw_ocr=display_raw,
                corrected=stable_text,
                confidence=conf,
                ocr_time_ms=ocr_ms,
                llm_time_ms=0.0,
                ocr_ok=True,
                llm_ok=True,
                error_msg=None,
                debounced_ocr=stable_text,
            )
            time.sleep(0.05)
            continue

        # 提交 LLM 异步执行，不阻塞；结果在下一轮循环中合并
        log(f"调用本地 LLM 纠错: 「{(stable_text[:60] + '...') if len(stable_text) > 60 else stable_text}」", level="INFO")
        future_llm = executor.submit(_run_llm_safe, stable_text)
        last_sent_text = stable_text
        pending_llm = (future_llm, stable_text, conf, ocr_ms, display_raw, err_msg)
        state.set_latest_result(
            raw_ocr=display_raw,
            corrected=stable_text,
            confidence=conf,
            ocr_time_ms=ocr_ms,
            llm_time_ms=0.0,
            ocr_ok=True,
            llm_ok=True,
            error_msg=err_msg,
            debounced_ocr=stable_text,
        )
        time.sleep(0.05)


def start_worker(state: SharedState, metrics: Optional["Metrics"] = None) -> threading.Thread:
    """启动管道线程与线程池；主线程仅需调用 start_worker 一次，永不等待。

    Agent D：可传入 metrics 打指标；
    Agent E：内部创建 LLM 缓存与节流器，提升性能与体验。
    """
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ocr_llm")
    circuit_breaker = _CircuitBreaker(
        failure_threshold=config.LLM_CIRCUIT_BREAKER_FAILURES,
        cooldown_sec=config.LLM_CIRCUIT_BREAKER_COOLDOWN_SEC,
    )
    debouncer = OCRDebouncer(
        history_len=getattr(config, "OCR_DEBOUNCE_HISTORY_LEN", 6),
        min_votes=getattr(config, "OCR_DEBOUNCE_MIN_VOTES", 4),
        similarity_vote=getattr(config, "OCR_DEBOUNCE_SIMILARITY_VOTE", 0.88),
    )
    cache = LLMCache(
        max_size=getattr(config, "LLM_CACHE_MAX_SIZE", 200),
        ttl_sec=getattr(config, "LLM_CACHE_TTL_SEC", 600),
    )
    throttler = LLMThrottler(
        min_interval_ms=getattr(config, "LLM_MIN_INTERVAL_MS", 1000),
    )
    # 启动前用空白图触发一次 OCR 初始化，环境异常时在启动阶段报一次而非每帧刷屏
    try:
        import numpy as np
        _dummy = np.zeros((64, 256, 3), dtype=np.uint8)
        _ = run_ocr(_dummy)
    except Exception:
        pass
    daemon = threading.Thread(
        target=_pipeline_loop,
        args=(state, executor, circuit_breaker, debouncer, metrics, cache, throttler),
        daemon=True,
        name="pipeline",
    )
    daemon.start()
    return daemon
