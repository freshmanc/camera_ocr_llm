# -*- coding: utf-8 -*-
"""中文叠加显示：PIL 绘制文本到 OpenCV 画面，结构清晰（原始/纠错/置信度/耗时）"""
import os
from typing import Optional

import cv2
import numpy as np

import config

# PIL 仅用于字体渲染
try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


def _get_font(size: int = 20):
    for path in config.FONT_PATHS:
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def draw_text_block(
    img_bgr: np.ndarray,
    lines: list,
    x: int = 10,
    y: int = 10,
    font_size: int = 18,
    color_bgr: tuple = (0, 255, 0),
    bg_alpha: float = 0.6,
) -> np.ndarray:
    """在 BGR 图上绘制多行中文/英文。若无 PIL 则用 cv2.putText 降级（中文会乱码）。"""
    if not lines:
        return img_bgr
    h, w = img_bgr.shape[:2]
    if HAS_PIL:
        img_pil = Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(img_pil)
        font = _get_font(font_size)
        y_off = y
        for line in lines:
            if not line:
                y_off += font_size + 4
                continue
            # 单行 try/except：Unicode/字体异常时不崩整块绘制（Agent D）
            try:
                line_str = line if isinstance(line, str) else str(line)
                line_str = line_str.encode("utf-8", errors="replace").decode("utf-8")  # 替换不可显示字符
            except Exception:
                line_str = "?"
            try:
                try:
                    bbox = draw.textbbox((0, 0), line_str, font=font)
                    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                except AttributeError:
                    tw, th = (font.getsize(line_str) if hasattr(font, "getsize") else (len(line_str) * font_size, font_size))
                if x + tw > w or y_off + th > h:
                    break
                draw.rectangle([x, y_off, x + tw + 4, y_off + th + 4], fill=(0, 0, 0))
                draw.text((x + 2, y_off + 2), line_str, font=font, fill=(color_bgr[2], color_bgr[1], color_bgr[0]))
                y_off += th + 6
            except Exception:
                y_off += font_size + 6
        img_bgr = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)
    else:
        for i, line in enumerate(lines):
            try:
                line_str = (line.decode("utf-8", errors="replace") if isinstance(line, bytes) else str(line))[:80]
            except Exception:
                line_str = "?"
            try:
                cy = y + i * (font_size + 6)
                cv2.putText(img_bgr, line_str, (x, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color_bgr, 1)
            except Exception:
                pass
    return img_bgr


def _diff_rate(a: str, b: str) -> Optional[float]:
    """计算两段文字的差别率 0~1：0=完全相同，1=完全不同。基于字符级编辑距离思想。"""
    a = (a or "").strip()
    b = (b or "").strip()
    if not a and not b:
        return 0.0
    n, m = len(a), len(b)
    if n == 0 or m == 0:
        return 1.0
    # 简单 LCS 相似度：最长公共子序列长度 / max(n,m)，差别率 = 1 - 相似度
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if a[i - 1] == b[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    sim = dp[n][m] / max(n, m)
    return round(1.0 - sim, 4)


def build_display_lines(
    raw_ocr: str,
    corrected: str,
    confidence: float,
    ocr_time_ms: float,
    llm_time_ms: float,
    ocr_ok: bool,
    llm_ok: bool,
    error_msg: Optional[str] = None,
    fps: Optional[float] = None,
    debounced_ocr: Optional[str] = None,
    vision_llm_text: Optional[str] = None,
    cross_validated_text: Optional[str] = None,
) -> list:
    """组装要显示的文本行：原始 OCR、去抖 OCR、纠错后、差别率、视觉 LLM、交叉验证、置信度、耗时、FPS、可选错误信息"""
    debounced_s = (debounced_ocr or "").strip()
    debounced_display = (debounced_s[:120] + "..." if len(debounced_s) > 120 else debounced_s) or "(无)"
    lines = [
        "[初始OCR] " + (raw_ocr[:120] + "..." if len(raw_ocr) > 120 else raw_ocr or "(无)"),
        "[去抖] " + debounced_display,
        "[校验后] " + (corrected[:120] + "..." if len(corrected) > 120 else corrected or "(无)"),
    ]
    # 差别率：初始(去抖)与校验后的差异
    base = debounced_s or raw_ocr or ""
    cor = (corrected or "").strip()
    dr = _diff_rate(base, cor)
    if dr is not None:
        lines.append(f"[差别率] {dr:.1%}")
    v_llm = (vision_llm_text or "").strip()
    if v_llm:
        lines.append("[Vision LLM] " + (v_llm[:120] + "..." if len(v_llm) > 120 else v_llm))
    cross = (cross_validated_text or "").strip()
    if cross and cross != cor:
        lines.append("[交叉验证] " + (cross[:120] + "..." if len(cross) > 120 else cross))
    perf_line = f"[耗时] OCR: {ocr_time_ms:.0f}ms  LLM: {llm_time_ms:.0f}ms"
    if fps is not None:
        perf_line += f"  FPS: {fps:.1f}"
    perf_line += f"  置信度: {confidence:.2%}"
    lines.append(perf_line)
    if not ocr_ok or not llm_ok or error_msg:
        status = []
        if not ocr_ok:
            status.append("OCR异常")
        if not llm_ok:
            status.append("LLM超时/断网")
        if error_msg:
            status.append(error_msg[:60])
        lines.append("[状态] " + " | ".join(status))
    return lines


def build_display_lines_compact(
    raw_ocr: str,
    corrected: str,
    confidence: float,
    ocr_time_ms: float,
    llm_time_ms: float,
    fps: Optional[float] = None,
    debounced_ocr: Optional[str] = None,
) -> list:
    """紧凑显示：初始、校验后、差别率、耗时（摄像头角落不挡视线）。"""
    base = (debounced_ocr or raw_ocr or "").strip()
    cor = (corrected or "").strip()
    dr = _diff_rate(base, cor)
    lines = [
        "[初始] " + ((base[:60] + "…") if len(base) > 60 else base or "(无)"),
        "[校验] " + ((cor[:60] + "…") if len(cor) > 60 else cor or "(无)"),
    ]
    if dr is not None:
        lines.append(f"[差别率] {dr:.1%}")
    perf = f"OCR:{ocr_time_ms:.0f}ms LLM:{llm_time_ms:.0f}ms 置信:{confidence:.0%}"
    if fps is not None:
        perf += f" FPS:{fps:.1f}"
    lines.append(perf)
    return lines


def wrap_text_for_display(text: str, chars_per_line: int = 28) -> list:
    """将长文本按字符数折行，用于解释窗口等多行显示。"""
    if not text or chars_per_line <= 0:
        return []
    lines = []
    for para in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        para = para.strip()
        if not para:
            lines.append("")
            continue
        while len(para) > chars_per_line:
            lines.append(para[:chars_per_line])
            para = para[chars_per_line:]
        if para:
            lines.append(para)
    return lines
