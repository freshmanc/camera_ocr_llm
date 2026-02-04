# -*- coding: utf-8 -*-
"""
Agent B：OCR 预处理（ROI、去噪、倾斜校正）。
OpenCV 流水线，失败时返回原图或上一步结果，不抛异常。
"""
from __future__ import annotations

from typing import Optional

import cv2  # type: ignore[import-untyped]
import numpy as np

import config


def crop_roi_center(image: np.ndarray, ratio: float = 0.7) -> np.ndarray:
    """保留中心 ratio 比例区域，减少边缘干扰。ratio=0.7 即中心 70% 宽高。"""
    if ratio >= 1.0 or ratio <= 0:
        return image
    h, w = image.shape[:2]
    x = int(w * (1 - ratio) / 2)
    y = int(h * (1 - ratio) / 2)
    rw = int(w * ratio)
    rh = int(h * ratio)
    return image[y : y + rh, x : x + rw].copy()


def upscale_roi(image: np.ndarray, scale: float = 1.5) -> np.ndarray:
    """ROI 放大：短边或整体按 scale 放大，字更清晰。scale<=1 不放大。"""
    if scale <= 1.0:
        return image
    h, w = image.shape[:2]
    nw, nh = int(w * scale), int(h * scale)
    return cv2.resize(image, (nw, nh), interpolation=cv2.INTER_LINEAR)


def sharpen(image: np.ndarray, strength: float = 1.4) -> np.ndarray:
    """锐化：unsharp mask，提升边缘便于二值化。strength 约 1.2~1.8。"""
    if strength <= 1.0 or image.size == 0:
        return image
    blurred = cv2.GaussianBlur(image, (0, 0), 2.0)
    out = cv2.addWeighted(image, strength, blurred, 1.0 - strength, 0)
    return np.clip(out, 0, 255).astype(np.uint8)


def denoise_and_binarize(
    image: np.ndarray,
    blur_ksize: tuple = (3, 3),
    use_adaptive: bool = True,
) -> np.ndarray:
    """去噪：高斯模糊后二值化。use_adaptive=True 用自适应阈值，否则 Otsu。"""
    if image.ndim == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()
    blurred = cv2.GaussianBlur(gray, blur_ksize, 0)
    if use_adaptive:
        binary = cv2.adaptiveThreshold(
            blurred, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            blockSize=11,
            C=2,
        )
    else:
        _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)


def correct_skew_small(image: np.ndarray, max_angle_deg: float = 5.0) -> np.ndarray:
    """轻微倾斜校正：用霍夫直线估计主角度并旋转，max_angle_deg 限制旋转幅度。"""
    if image.ndim == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=80, minLineLength=50, maxLineGap=10)
    if lines is None or len(lines) == 0:
        return image
    angles = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        if x2 - x1 != 0:
            angles.append(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
    if not angles:
        return image
    median_angle = np.median(angles)
    median_angle = float(median_angle)
    if abs(median_angle) > max_angle_deg:
        median_angle = max_angle_deg if median_angle > 0 else -max_angle_deg
    if abs(median_angle) < 0.3:
        return image
    h, w = image.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), -median_angle, 1.0)
    rotated = cv2.warpAffine(image, M, (w, h), borderMode=cv2.BORDER_REPLICATE)
    return rotated


def resize_short_edge(image: np.ndarray, short_edge: int) -> np.ndarray:
    """短边缩放到 short_edge，比例不变。short_edge<=0 不缩放。"""
    if short_edge <= 0:
        return image
    h, w = image.shape[:2]
    s = min(h, w)
    if s <= short_edge:
        return image
    scale = short_edge / s
    nw, nh = int(w * scale), int(h * scale)
    return cv2.resize(image, (nw, nh), interpolation=cv2.INTER_LINEAR)


def preprocess_for_ocr(image: np.ndarray) -> np.ndarray:
    """
    按 config 串联：ROI → ROI 放大 → 缩放 → 锐化(可选) → 去噪/二值化 → 倾斜(可选)。
    任一步失败则返回上一步或原图，不抛异常。
    """
    out = image
    try:
        if getattr(config, "OCR_USE_ROI", True):
            ratio = getattr(config, "OCR_ROI_CENTER_RATIO", 0.7)
            out = crop_roi_center(out, ratio)
        upscale = getattr(config, "OCR_ROI_UPSCALE", 1.0)
        if upscale > 1.0:
            out = upscale_roi(out, upscale)
        if getattr(config, "OCR_RESIZE_SHORT_EDGE", 0) > 0:
            out = resize_short_edge(out, config.OCR_RESIZE_SHORT_EDGE)
        if getattr(config, "OCR_USE_SHARPEN", False):
            strength = getattr(config, "OCR_SHARPEN_STRENGTH", 1.4)
            out = sharpen(out, strength)
        if getattr(config, "OCR_USE_PREPROCESS", True):
            ksize = getattr(config, "OCR_PREPROCESS_BLUR_KSIZE", (3, 3))
            adaptive = getattr(config, "OCR_PREPROCESS_USE_ADAPTIVE_THRESH", True)
            out = denoise_and_binarize(out, blur_ksize=ksize, use_adaptive=adaptive)
        if getattr(config, "OCR_USE_SKEW_CORRECTION", False):
            out = correct_skew_small(out)
    except Exception:
        pass
    return out
