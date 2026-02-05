# -*- coding: utf-8 -*-
"""
阶段 1：FastAPI 后端，/api/health、/api/recognize（图片 → OCR + LLM 校验）。
与现有 main.py 共享项目根与 config/agents/tools，启动时需在项目根目录执行。
"""
import os
import sys

# 保证与 main.py 一致：项目根在 path 最前，且先于任何业务 import 设置 Paddle 环境
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)
os.chdir(_root)
os.environ.setdefault("FLAGS_use_mkldnn", "0")
os.environ.setdefault("FLAGS_use_onednn", "0")

# 清掉可能冲突的 tools 缓存，强制用本项目
for _n in list(sys.modules):
    if _n == "tools" or _n.startswith("tools."):
        del sys.modules[_n]

from typing import Optional

import cv2
import numpy as np
from fastapi import File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# 业务模块在 path 与 env 就绪后再导入
from tools.ocr_engine import run_ocr
from agents.llm_correct import correct_with_llm

from fastapi import FastAPI
from fastapi.responses import FileResponse

app = FastAPI(
    title="Camera OCR + LLM API",
    description="图片识别与 LLM 纠错，供网页/手机端轻量调用。",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _image_bytes_to_bgr(data: bytes) -> Optional[np.ndarray]:
    """将上传的图片字节转为 OpenCV BGR 数组，失败返回 None。"""
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    return img


class RecognizeResponse(BaseModel):
    raw_ocr: str
    corrected: str
    confidence: float
    ocr_time_ms: float
    llm_time_ms: float
    ocr_ok: bool
    llm_ok: bool
    error_msg: Optional[str] = None


@app.get("/api/health")
def api_health():
    """健康检查，供前端或负载均衡探测。"""
    return {"status": "ok", "service": "camera_ocr_llm"}


@app.post("/api/recognize", response_model=RecognizeResponse)
def api_recognize(file: UploadFile = File(...)):
    """
    上传一张图片，返回 OCR 原始结果 + LLM 纠错结果（与桌面端「截图识别」一致）。
    支持常见图片格式：PNG、JPEG、BMP、WebP 等。
    """
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="请上传非空图片")
    image = _image_bytes_to_bgr(content)
    if image is None:
        raise HTTPException(status_code=400, detail="无法解析图片，请换一张或检查格式")

    # 复用现有 OCR（与 worker 中一致）
    ocr_result = run_ocr(image)
    raw_text = ocr_result.text or ""
    ocr_ok = ocr_result.success
    ocr_time_ms = ocr_result.time_ms
    confidence = ocr_result.confidence
    err_msg = ocr_result.error_msg

    # 无有效文本时仍返回结果，LLM 不调用
    if not (raw_text and raw_text.strip()):
        return RecognizeResponse(
            raw_ocr=raw_text or "(无)",
            corrected=raw_text or "(无)",
            confidence=0.0,
            ocr_time_ms=ocr_time_ms,
            llm_time_ms=0.0,
            ocr_ok=ocr_ok,
            llm_ok=True,
            error_msg=err_msg,
        )

    # LLM 纠错（与 worker 中一致）
    llm_result = correct_with_llm(raw_text.strip())
    corrected = llm_result.corrected_text if llm_result.success else raw_text.strip()
    llm_time_ms = llm_result.time_ms
    llm_ok = llm_result.success
    if llm_result.error_msg:
        err_msg = (err_msg or "") + " " + llm_result.error_msg

    return RecognizeResponse(
        raw_ocr=raw_text,
        corrected=corrected,
        confidence=confidence,
        ocr_time_ms=ocr_time_ms,
        llm_time_ms=llm_time_ms,
        ocr_ok=ocr_ok,
        llm_ok=llm_ok,
        error_msg=(err_msg or "").strip() or None,
    )


# 阶段 1：提供前端页面，访问 http://host:8000/ 即可用网页（与 API 同源，无需改 API_BASE）
_web_dir = os.path.join(_root, "web")
if os.path.isdir(_web_dir):
    @app.get("/")
    def index():
        return FileResponse(os.path.join(_web_dir, "index.html"))

    @app.get("/app.js")
    def app_js():
        return FileResponse(os.path.join(_web_dir, "app.js"), media_type="application/javascript")

    @app.get("/style.css")
    def style_css():
        return FileResponse(os.path.join(_web_dir, "style.css"), media_type="text/css")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
