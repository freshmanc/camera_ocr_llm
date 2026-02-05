# -*- coding: utf-8 -*-
"""
朗读 Agent：统一负责“纠错结果稳定 → 检测语言 → 选择发音人 → 朗读”。
- 纠错内容需在最近 N 次中至少 K 次相同/相似才触发朗读，避免一闪而过误读。
- 自动识别文本为英语或法语，再选用对应语音朗读。
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import threading
import unicodedata
from collections import deque
from typing import Optional

import config

# 避免重复朗读同一段文字
_last_spoken_text: Optional[str] = None
_lock = threading.Lock()

# 纠错结果去抖：仅当稳定（最近 N 次中至少 K 次相同/相似）后才朗读
_corrected_history: deque = deque(maxlen=5)  # maxlen 取配置与默认的较大值，speak() 内按配置截断

# 语言检测：短文本可能不准，用种子保证可复现
try:
    from langdetect import detect, DetectorFactory
    DetectorFactory.seed = 0
    _HAS_LANGDETECT = True
except ImportError:
    _HAS_LANGDETECT = False


def _normalize_for_lang(text: str) -> str:
    """统一为 NFC，便于识别「e + 组合重音」等为 é。"""
    return unicodedata.normalize("NFC", (text or "").strip())


def detect_language(text: str) -> str:
    """
    识别文本主要语言，返回 'en' 或 'fr'。
    支持 config.TTS_FORCE_LANG 强制指定；有法语特征或常见法语词时优先判为法语。
    """
    t = _normalize_for_lang(text or "")
    if not t or len(t) < 2:
        return getattr(config, "TTS_DEFAULT_LANG", "en")
    force = (getattr(config, "TTS_FORCE_LANG", "") or "").strip().lower()
    if force in ("fr", "en"):
        return force
    # 先看是否有明显法语特征（重音、ç、œ、æ）
    if _has_french_markers(t):
        return "fr"
    # OCR 常丢失重音：看是否含常见法语词（无重音写法）
    if _looks_like_french_by_words(t):
        return "fr"
    if not _HAS_LANGDETECT:
        return _fallback_detect_language(t) or getattr(config, "TTS_DEFAULT_LANG", "en")
    try:
        lang = detect(t)
        if lang in ("en", "fr"):
            return lang
        return getattr(config, "TTS_DEFAULT_LANG", "en")
    except Exception:
        return _fallback_detect_language(t) or getattr(config, "TTS_DEFAULT_LANG", "en")


def _looks_like_french_by_words(text: str) -> bool:
    """无重音时根据常见法语词判断（OCR 常把 déterminants 识别成 determinants）。"""
    t = (text or "").lower()
    words = set(w.strip(".,;:?!\"'()") for w in t.split() if len(w.strip(".,;:?!\"'()")) >= 2)
    # 常见法语词（无重音形式），出现 2 个以上则倾向法语
    french_hints = {
        "les", "des", "une", "est", "sont", "dans", "pour", "avec", "aux", "que", "qui",
        "pas", "sur", "tout", "sous", "mais", "ces", "mes", "ses", "nos", "vos", "leur",
        "ont", "fait", "plus", "bien", "très", "aussi", "comme", "être", "avoir", "se", "le", "la",
        "ferment", "fermer", "determinants", "déterminants", "souverain", "souveraine",
    }
    count = sum(1 for w in words if w in french_hints)
    if count >= 2:
        return True
    # 单词但很典型（如整句 "les determinants se ferment" 里 les + des 等）
    if count >= 1 and len(words) >= 2:
        return True
    return False


def _has_french_markers(text: str) -> bool:
    """文本中是否含有明显法语特征（重音、ç、œ、æ 等），有则优先当法语。先 NFC 规范化以便识别组合字符。"""
    t = _normalize_for_lang(text or "")
    french_chars = "éèêëàâçîïôùûüœæ"
    count = sum(1 for c in t if c.lower() in french_chars)
    if count >= 1:
        return True
    if "ç" in t or "œ" in t.lower() or "æ" in t.lower():
        return True
    return False


def _fallback_detect_language(text: str) -> Optional[str]:
    """无 langdetect 时：简单根据法文特征字符判断。"""
    if _has_french_markers(text):
        return "fr"
    return "en"


def get_voice_for_language(lang: str) -> str:
    """根据语言代码返回 edge-tts 的 voice id。"""
    if lang == "fr":
        return getattr(config, "TTS_VOICE_FR", "fr-FR-DeniseNeural")
    return getattr(config, "TTS_VOICE_EN", "en-US-JennyNeural")


def _get_stable_corrected() -> Optional[str]:
    """
    从纠错历史中取“稳定”文本：最近 N 次中至少 K 次相同或相似（>= similarity）则返回
    最后一次属于该稳定簇的原文（用于朗读）；否则返回 None。
    """
    from agents.debounce import text_similarity

    history = list(_corrected_history)
    if not history:
        return None
    n = getattr(config, "TTS_DEBOUNCE_HISTORY_LEN", 3)
    min_votes = getattr(config, "TTS_DEBOUNCE_MIN_VOTES", 2)
    sim_th = getattr(config, "TTS_DEBOUNCE_SIMILARITY", 0.92)
    best_count = 0
    best_representative = None
    for t in history:
        count = sum(1 for s in history if text_similarity(t, s) >= sim_th)
        if count >= min_votes and count > best_count:
            best_count = count
            best_representative = t
    if best_representative is None:
        return None
    # 返回历史中最后一次与代表文本相似的原文（保留换行等）
    for i in range(len(history) - 1, -1, -1):
        if text_similarity(history[i], best_representative) >= sim_th:
            return history[i]
    return best_representative


def speak_immediate(text: str) -> None:
    """
    立即朗读，不去抖。用于用户主动说「读一下」等指令时，直接读出当前文字。
    """
    t = (text or "").strip()
    if not t or len(t) > 2000:
        return
    if not getattr(config, "ENABLE_TTS", True):
        return
    threading.Thread(target=_do_speak, args=(t,), daemon=True).start()


def speak(text: str) -> None:
    """
    朗读 Agent 唯一对外接口。
    纠错结果需稳定（最近 N 次中至少 K 次相同/相似）后才朗读；再按语言选发音人。在后台线程执行，不阻塞。
    """
    global _last_spoken_text, _corrected_history
    t = (text or "").strip()
    if not t or len(t) > 2000:
        return
    with _lock:
        _corrected_history.append(t)
        n = getattr(config, "TTS_DEBOUNCE_HISTORY_LEN", 3)
        while len(_corrected_history) > n:
            _corrected_history.popleft()
        stable = _get_stable_corrected()
        if stable is None:
            return
        if _last_spoken_text is not None and _last_spoken_text.strip():
            from agents.debounce import text_similarity
            if text_similarity(stable, _last_spoken_text) >= getattr(config, "TTS_DEBOUNCE_SIMILARITY", 0.92):
                return
        _last_spoken_text = stable
    threading.Thread(target=_do_speak, args=(stable,), daemon=True).start()


def _do_speak(text: str) -> None:
    """后台线程：检测语言 → 选发音人 → 合成并播放。"""
    lang = detect_language(text)
    voice = get_voice_for_language(lang)
    try:
        _speak_edge_tts(text, voice)
    except Exception:
        try:
            _speak_pyttsx3(text)
        except Exception:
            pass


def _tts_dir() -> str:
    """朗读音频存放目录（对话框内嵌播放用），默认项目下 logs/tts。"""
    root = getattr(config, "_ROOT_DIR", None) or os.path.dirname(os.path.dirname(os.path.abspath(config.__file__)))
    d = os.path.join(root, "logs", "tts")
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        d = tempfile.gettempdir()
    return d


def generate_tts_file(text: str, lang_detect_text: Optional[str] = None) -> Optional[str]:
    """
    仅生成朗读音频文件并返回路径，不调用系统播放器。用于对话框内嵌「🔊 播放」。
    文本过长会截断；失败返回 None。文件保存在 logs/tts，保留最近若干份。
    lang_detect_text：若提供则仅用于语言检测（可传带重音的原文），朗读内容仍用 text。
    """
    t = (text or "").strip()
    if not t or len(t) > 2000:
        return None
    try:
        import edge_tts
    except ImportError:
        return None
    lang = detect_language((lang_detect_text or t).strip())
    voice = get_voice_for_language(lang)
    rate = getattr(config, "TTS_RATE", "+0%")
    communicate = edge_tts.Communicate(t, voice, rate=rate)
    import time as _time
    name = f"tts_{_time.strftime('%Y%m%d_%H%M%S')}_{id(t) % 100000}.mp3"
    out_dir = _tts_dir()
    path = os.path.join(out_dir, name)
    try:
        asyncio.run(communicate.save(path))
    except Exception:
        return None
    # 保留最近 N 个文件，删更早的
    try:
        files = [os.path.join(out_dir, f) for f in os.listdir(out_dir) if f.startswith("tts_") and f.endswith(".mp3")]
        files.sort(key=os.path.getmtime)
        for f in files[:-10]:
            try:
                os.unlink(f)
            except Exception:
                pass
    except Exception:
        pass
    return path


def _speak_edge_tts(text: str, voice: str) -> None:
    """使用 edge-tts（微软神经语音）。"""
    try:
        import edge_tts
    except ImportError:
        raise ImportError("edge-tts not installed")
    rate = getattr(config, "TTS_RATE", "+0%")
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    try:
        asyncio.run(communicate.save(tmp.name))
        tmp.close()
        _play_audio(tmp.name)
        def _del_later():
            try:
                if os.path.exists(tmp.name):
                    os.unlink(tmp.name)
            except Exception:
                pass
        threading.Timer(30.0, _del_later).start()
    except Exception:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass


def _play_audio(path: str) -> None:
    """播放音频：Windows 用系统默认播放器。"""
    try:
        if os.name == "nt":
            os.startfile(path)
        else:
            import subprocess
            subprocess.run(["xdg-open", path], check=False, timeout=2)
    except Exception:
        pass


def _speak_pyttsx3(text: str) -> None:
    """兜底：pyttsx3（音质一般，不区分语种）。"""
    import pyttsx3
    engine = pyttsx3.init()
    engine.setProperty("rate", getattr(config, "TTS_PYTTSX_RATE", 150))
    voices = engine.getProperty("voices")
    voice_id = getattr(config, "TTS_PYTTSX_VOICE_ID", None)
    if voice_id is not None and isinstance(voice_id, str):
        for v in voices:
            if voice_id in v.id or voice_id in (v.name or ""):
                engine.setProperty("voice", v.id)
                break
    engine.say(text)
    engine.runAndWait()
    engine.stop()
