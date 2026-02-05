# -*- coding: utf-8 -*-
"""读取上传文件为纯文本，供 LLM 识别。支持 .txt、.pdf、.docx。"""
from __future__ import annotations

import os
from typing import Optional, Tuple


def read_file_as_text(path: str, max_chars: int = 12000) -> Tuple[bool, str]:
    """
    根据扩展名读取文件为 UTF-8 文本。返回 (成功, 文本)；失败时返回 (False, 错误信息)。
    """
    path = (path or "").strip()
    if not path or not os.path.isfile(path):
        return False, "文件不存在"
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".txt":
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        elif ext == ".pdf":
            text = _read_pdf(path)
        elif ext in (".docx", ".doc"):
            text = _read_docx(path)
        else:
            return False, f"不支持的类型 {ext}，请上传 .txt / .pdf / .docx"
        text = (text or "").strip()
        if not text:
            return False, "文件内容为空"
        if len(text) > max_chars:
            text = text[:max_chars] + "\n\n…（已截断）"
        return True, text
    except Exception as e:
        return False, str(e)[:200]


def _read_pdf(path: str) -> str:
    try:
        import pdfplumber
        out = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    out.append(t)
        return "\n\n".join(out) if out else ""
    except ImportError:
        try:
            import PyPDF2
            out = []
            with open(path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    t = page.extract_text()
                    if t:
                        out.append(t)
            return "\n\n".join(out) if out else ""
        except ImportError:
            raise RuntimeError("请安装 pdfplumber 或 PyPDF2: pip install pdfplumber 或 pip install PyPDF2")


def _read_docx(path: str) -> str:
    try:
        from docx import Document
        doc = Document(path)
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except ImportError:
        raise RuntimeError("请安装 python-docx: pip install python-docx")
