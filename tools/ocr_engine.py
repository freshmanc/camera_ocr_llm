# -*- coding: utf-8 -*-
"""
OCR 引擎：EasyOCR 为主，PaddleOCR 兜底；预处理(ROI/去噪/倾斜)、置信度阈值、文本行合并；
失败或低置信度返回可控结果，不抛异常。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

# PaddleOCR/PDX 仅支持进程内单次初始化，且多线程并发创建或调用会触发
# "PDX has already been initialized"。用锁序列化创建与每次 .ocr() 调用。
_paddle_ocr_lock = threading.Lock()
# 若首次创建就报 PDX 重复初始化，则不再尝试创建，直接返回错误
_paddle_ocr_fatal = False
# 初始化只尝试一次：失败后不再重试，避免 PDX 二次初始化刷屏
_paddle_init_attempted = False
_paddle_init_error: Optional[str] = None

import config

try:
    from tools.preprocess import preprocess_for_ocr
except ImportError:
    def preprocess_for_ocr(image):  # type: ignore
        return image


@dataclass
class OCRResult:
    """单次 OCR 结果"""
    text: str
    confidence: float
    time_ms: float
    success: bool
    error_msg: Optional[str] = None
    details: Optional[List[Tuple[str, float]]] = None  # [(text, conf), ...]


def _box_center_y(box) -> float:
    pts = box if isinstance(box[0], (list, tuple)) else [box[:2], box[2:]]
    return sum(p[1] for p in pts) / len(pts)


def _box_center_x(box) -> float:
    pts = box if isinstance(box[0], (list, tuple)) else [box[:2], box[2:]]
    return sum(p[0] for p in pts) / len(pts)


def _sort_boxes_by_reading_order(boxes_texts_confs: List[Tuple[list, str, float]]) -> List[Tuple[list, str, float]]:
    """按阅读顺序排序：先按 bbox 中心 y，再按 x。"""
    return sorted(
        boxes_texts_confs,
        key=lambda x: (round(_box_center_y(x[0]) / 20) * 20, _box_center_x(x[0])),
    )


def _group_into_lines_and_paragraphs(
    boxes_texts_confs: List[Tuple[list, str, float]],
    img_height: int,
) -> str:
    """
    按同一行、同一段落合并：同行用空格，行间用 \\n，段间用 \\n\\n。
    避免整段用空格拼接导致不连贯。
    """
    if not boxes_texts_confs:
        return ""
    line_tol = max(8, img_height * getattr(config, "OCR_LINE_Y_TOLERANCE_RATIO", 0.025))
    para_ratio = getattr(config, "OCR_PARAGRAPH_GAP_RATIO", 1.8)

    # 按 y 再 x 排序
    sorted_items = sorted(
        boxes_texts_confs,
        key=lambda x: (_box_center_y(x[0]), _box_center_x(x[0])),
    )
    # 聚成行：相邻项 center_y 差 < line_tol 视为同一行
    lines: List[List[Tuple[list, str, float]]] = []
    for item in sorted_items:
        cy = _box_center_y(item[0])
        if not lines:
            lines.append([item])
            continue
        last_line = lines[-1]
        last_cy = sum(_box_center_y(t[0]) for t in last_line) / len(last_line)
        if abs(cy - last_cy) <= line_tol:
            last_line.append(item)
        else:
            lines.append([item])

    # 每行内按 x 排序后拼成字符串
    line_texts: List[str] = []
    line_centers: List[float] = []
    for line in lines:
        line_sorted = sorted(line, key=lambda x: _box_center_x(x[0]))
        line_texts.append(" ".join(t[1] for t in line_sorted).strip())
        line_centers.append(sum(_box_center_y(t[0]) for t in line) / len(line))

    # 行间距大于 平均行高 * para_ratio 则插入段落（双换行）
    if len(line_centers) < 2:
        return "\n".join(line_texts).strip()
    gaps = [line_centers[i + 1] - line_centers[i] for i in range(len(line_centers) - 1)]
    avg_gap = sum(gaps) / len(gaps) if gaps else 0
    sep = []
    for i in range(len(line_texts)):
        if i > 0:
            gap = line_centers[i] - line_centers[i - 1]
            sep.append("\n\n" if avg_gap > 0 and gap >= avg_gap * para_ratio else "\n")
        else:
            sep.append("")
    return "".join(s + t for s, t in zip(sep, line_texts)).strip()


def _run_easyocr(image) -> OCRResult:
    try:
        import easyocr
    except ImportError:
        return OCRResult(
            text="",
            confidence=0.0,
            time_ms=0.0,
            success=False,
            error_msg="未安装 easyocr，请 pip install easyocr",
        )
    t0 = time.perf_counter()
    try:
        if not hasattr(_run_easyocr, "reader"):
            _run_easyocr.reader = easyocr.Reader(
                config.OCR_LANGS,
                gpu=config.OCR_GPU,
                verbose=False,
            )
        reader = _run_easyocr.reader
        min_conf = getattr(config, "OCR_MIN_BOX_CONFIDENCE", 0.25)
        try:
            raw = reader.readtext(image, min_confidence=min_conf)
        except TypeError:
            raw = reader.readtext(image)
            if raw and min_conf > 0:
                raw = [item for item in raw if len(item) >= 3 and float(item[2]) >= min_conf]
        elapsed_ms = (time.perf_counter() - t0) * 1000
        if not raw:
            return OCRResult(
                text="",
                confidence=0.0,
                time_ms=elapsed_ms,
                success=True,
                details=[],
            )
        # 按阅读顺序合并：保留行/段落结构（同行空格、行间换行、段间双换行）
        raw_sorted = _sort_boxes_by_reading_order(raw)
        texts = [item[1] for item in raw_sorted]
        confs = [float(item[2]) for item in raw_sorted]
        if getattr(config, "OCR_KEEP_LINE_STRUCTURE", True):
            h = image.shape[0] if hasattr(image, "shape") and len(image.shape) >= 2 else 400
            full_text = _group_into_lines_and_paragraphs(raw_sorted, h)
        else:
            full_text = " ".join(texts)
        avg_conf = sum(confs) / len(confs) if confs else 0.0
        min_avg = getattr(config, "OCR_MIN_AVG_CONFIDENCE", 0.2)
        if avg_conf < min_avg:
            full_text = ""
            avg_conf = 0.0
        return OCRResult(
            text=full_text.strip(),
            confidence=avg_conf,
            time_ms=elapsed_ms,
            success=True,
            details=list(zip(texts, confs)),
        )
    except Exception as e:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        return OCRResult(
            text="",
            confidence=0.0,
            time_ms=elapsed_ms,
            success=False,
            error_msg=str(e),
        )


def _paddle_env_and_import():
    """设置 Paddle 环境并 import PaddleOCR，供创建引擎前调用。"""
    import os
    import sys
    os.environ.setdefault("FLAGS_use_mkldnn", "0")
    os.environ.setdefault("FLAGS_use_onednn", "0")
    try:
        import paddle.base.libpaddle as libpaddle  # type: ignore[attr-defined]
        ac = getattr(libpaddle, "AnalysisConfig", None)
        if ac is not None and not hasattr(ac, "set_optimization_level"):
            setattr(ac, "set_optimization_level", lambda self, level: None)
    except Exception:
        pass
    import paddleocr as _pom
    PaddleOCR = _pom.PaddleOCR
    ver = getattr(_pom, "__version__", "") or "0"
    # 非 2.7.x 会走 paddlex/PDX，只提示一次
    if not ver.startswith("2.7.") and not getattr(_paddle_env_and_import, "_warned_version", False):
        _paddle_env_and_import._warned_version = True
        try:
            from tools.logger_util import log
            log(f"PaddleOCR 当前版本 {ver}，非 2.7.x 会报 PDX 错误。请运行 fix_ocr_env.bat 或: pip install paddleocr==2.7.0.3", level="WARNING")
        except Exception:
            pass
    if "paddlex" in sys.modules and not getattr(_paddle_env_and_import, "_warned_paddlex", False):
        _paddle_env_and_import._warned_paddlex = True
        try:
            from tools.logger_util import log
            log("当前 PaddleOCR 走 paddlex/PDX 链路，会报「PDX has already been initialized」。请运行 fix_ocr_env.bat 或 pip install paddleocr==2.7.0.3", level="WARNING")
        except Exception:
            pass
    return PaddleOCR


def init_paddle_ocr_engine() -> bool:
    """
    在主线程、启动 worker 之前调用，只做一次 PaddleOCR 引擎创建，避免多线程下 PDX 重复初始化。
    返回 True 表示引擎已就绪或无需 OCR，False 表示创建失败（后续 run_ocr 会直接返回错误）。
    """
    global _paddle_ocr_fatal
    try:
        PaddleOCR = _paddle_env_and_import()
    except ImportError:
        return True  # 未安装时 run_ocr 会单独处理
    except OSError:
        return False  # torch/shm.dll 等加载失败，后续 run_ocr 会返回错误
    with _paddle_ocr_lock:
        if hasattr(_run_paddle_ocr, "ocr_engine"):
            return True
        if _paddle_ocr_fatal:
            return False
        lang = getattr(config, "PADDLE_OCR_LANG", "ch")
        force_cpu = getattr(config, "PADDLE_OCR_FORCE_CPU", True)
        use_gpu = False if force_cpu else getattr(config, "OCR_GPU", True)

        def _create(gpu: bool):
            try:
                return PaddleOCR(lang=lang, use_angle_cls=True, device="gpu:0" if gpu else "cpu")
            except TypeError:
                return PaddleOCR(use_angle_cls=True, lang=lang, use_gpu=gpu)

        try:
            try:
                _run_paddle_ocr.ocr_engine = _create(use_gpu)
            except Exception as ae:
                err = str(ae).lower()
                if "analysisconfig" in err or "libpaddle" in err:
                    _run_paddle_ocr.ocr_engine = _create(False)
                else:
                    raise
            # 在主线程里跑一次 dummy ocr，让 PDX 推理路径也只初始化一次
            import numpy as np
            dummy = np.zeros((32, 100, 3), dtype=np.uint8)
            try:
                _run_paddle_ocr.ocr_engine.ocr(dummy, cls=True)
            except TypeError:
                _run_paddle_ocr.ocr_engine.ocr(dummy)
            return True
        except Exception as e:
            err = str(e).lower()
            if "pdx" in err or "reinitialization" in err or "already been initialized" in err:
                _paddle_ocr_fatal = True
            return False


def _run_paddle_ocr(image) -> OCRResult:
    """可选 PaddleOCR 降级路径。遇 AnalysisConfig 等兼容性错误时自动改用 CPU。"""
    global _paddle_ocr_fatal, _paddle_init_attempted, _paddle_init_error
    if _paddle_ocr_fatal:
        return OCRResult(
            text="",
            confidence=0.0,
            time_ms=0.0,
            success=False,
            error_msg="PaddleOCR 初始化失败(PDX 已初始化)，请重启程序",
        )
    try:
        PaddleOCR = _paddle_env_and_import()
    except ImportError:
        return OCRResult(
            text="",
            confidence=0.0,
            time_ms=0.0,
            success=False,
            error_msg="未安装 paddleocr",
        )
    except OSError as e:
        return OCRResult(
            text="",
            confidence=0.0,
            time_ms=0.0,
            success=False,
            error_msg=f"无法加载 paddleocr 依赖: {e}",
        )
    t0 = time.perf_counter()
    with _paddle_ocr_lock:
        # 已尝试过初始化且没有引擎 => 不再重试，否则 PDX 会报 reinit
        if _paddle_init_attempted and not hasattr(_run_paddle_ocr, "ocr_engine"):
            return OCRResult(
                text="",
                confidence=0.0,
                time_ms=0.0,
                success=False,
                error_msg=f"OCR init failed (cached): {_paddle_init_error or 'unknown'}",
            )
        try:
            if not hasattr(_run_paddle_ocr, "ocr_engine"):
                _paddle_init_attempted = True
                _paddle_init_error = None
                lang = getattr(config, "PADDLE_OCR_LANG", "ch")
                force_cpu = getattr(config, "PADDLE_OCR_FORCE_CPU", True) or getattr(
                    _run_paddle_ocr, "_force_cpu_retry", False
                )
                use_gpu = False if force_cpu else getattr(config, "OCR_GPU", True)

                def _create_engine(gpu: bool):
                    try:
                        device = "gpu:0" if gpu else "cpu"
                        return PaddleOCR(lang=lang, use_angle_cls=True, device=device)
                    except TypeError:
                        return PaddleOCR(use_angle_cls=True, lang=lang, use_gpu=gpu)

                try:
                    _run_paddle_ocr.ocr_engine = _create_engine(use_gpu)
                except Exception as ae:
                    err = str(ae).lower()
                    if "analysisconfig" in err or "libpaddle" in err:
                        _run_paddle_ocr.ocr_engine = _create_engine(False)
                    else:
                        if "pdx" in err or "reinitialization" in err or "already been initialized" in err:
                            _paddle_ocr_fatal = True
                        _paddle_init_error = str(ae)
                        raise
            try:
                raw = _run_paddle_ocr.ocr_engine.ocr(image, cls=True)
            except TypeError:
                raw = _run_paddle_ocr.ocr_engine.ocr(image)
        except Exception as e:
            _paddle_init_attempted = True
            _paddle_init_error = str(e)
            err = str(e).lower()
            if "pdx" in err or "reinitialization" in err or "already been initialized" in err:
                _paddle_ocr_fatal = True
            elapsed_ms = (time.perf_counter() - t0) * 1000
            return OCRResult(
                text="",
                confidence=0.0,
                time_ms=elapsed_ms,
                success=False,
                error_msg=str(e),
            )
    elapsed_ms = (time.perf_counter() - t0) * 1000
    try:
        if not raw or not raw[0]:
            return OCRResult(text="", confidence=0.0, time_ms=elapsed_ms, success=True, details=[])
        line_texts = [line[1][0] for line in raw[0]]
        line_confs = [float(line[1][1]) for line in raw[0]]
        min_conf = getattr(config, "OCR_MIN_BOX_CONFIDENCE", 0.25)
        filtered = [(t, c) for t, c in zip(line_texts, line_confs) if c >= min_conf]
        if not filtered:
            return OCRResult(text="", confidence=0.0, time_ms=elapsed_ms, success=True, details=[])
        line_texts, line_confs = zip(*filtered)
        # 保留行结构：行间用换行，避免整段空格不连贯
        full_text = "\n".join(line_texts) if getattr(config, "OCR_KEEP_LINE_STRUCTURE", True) else " ".join(line_texts)
        avg_conf = sum(line_confs) / len(line_confs)
        min_avg = getattr(config, "OCR_MIN_AVG_CONFIDENCE", 0.2)
        if avg_conf < min_avg:
            full_text = ""
            avg_conf = 0.0
        return OCRResult(
            text=full_text.strip(),
            confidence=avg_conf,
            time_ms=elapsed_ms,
            success=True,
            details=list(zip(line_texts, line_confs)),
        )
    except Exception as e:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        return OCRResult(
            text="",
            confidence=0.0,
            time_ms=elapsed_ms,
            success=False,
            error_msg=str(e),
        )


def run_ocr(image) -> OCRResult:
    """
    对外接口：预处理 → PaddleOCR → 置信度过滤与文本行合并。仅用 PaddleOCR，不用 EasyOCR。
    """
    img = preprocess_for_ocr(image)
    return _run_paddle_ocr(img)
