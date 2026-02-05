# -*- coding: utf-8 -*-
"""
考试功能：根据材料生成试卷（TXT/PDF/Word）、批改、讲解。
"""
from __future__ import annotations

import os
import re
import time
from typing import Optional, Tuple

import config

_ROOT_DIR = getattr(config, "_ROOT_DIR", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _get_client_and_model():
    from openai import OpenAI
    use_openai = getattr(config, "LLM_USE_OPENAI", False)
    api_key = getattr(config, "OPENAI_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
    if use_openai and api_key:
        client = OpenAI(api_key=api_key)
        model = (getattr(config, "LLM_MODEL", "") or "gpt-4o-mini").strip()
        return client, model
    base_url = getattr(config, "LLM_BASE_URL", "http://127.0.0.1:1234/v1")
    client = OpenAI(base_url=base_url, api_key="lm-studio")
    model = (getattr(config, "LLM_MODEL", "") or "").strip()
    return client, model or "default"


def _ensure_exam_dir() -> str:
    d = os.path.join(_ROOT_DIR, getattr(config, "EXAM_OUTPUT_DIR", "logs/exams"))
    os.makedirs(d, exist_ok=True)
    return d


def generate_exam_paper(
    source_text: str,
    output_format: str = "txt",
    num_questions: int = 5,
) -> Tuple[Optional[str], Optional[str], str]:
    """
    根据材料用 LLM 生成试卷与答案，并写入文件。
    返回 (试卷路径, 答案路径, 错误信息)；失败时路径为 None。
    """
    source_text = (source_text or "").strip()
    if not source_text:
        return None, None, "没有材料内容，请先上传文件、对准摄像头或输入材料后再生成试卷。"
    output_format = (output_format or "txt").lower()
    if output_format not in ("txt", "pdf", "docx"):
        output_format = "txt"
    num_questions = max(1, min(20, int(num_questions)))

    sys_prompt = """你是一位法语教师。请根据用户提供的材料，生成一份法语测验卷。
要求：
1. 题目数量由用户指定，题型可包含：填空、翻译（法译中或中译法）、选择题、简答。
2. 你的回复必须严格按以下格式，不要写其他说明：
---PAPER---
（这里只写题目，每题前加题号如 1. 2.）
---ANSWER---
（这里只写答案，与题目一一对应，每题答案一行，如 1. xxx  2. xxx）
"""
    user_msg = f"请根据以下材料出 {num_questions} 道法语测验题，并给出答案。\n\n材料：\n{source_text[:4000]}"

    try:
        client, model = _get_client_and_model()
        timeout = getattr(config, "EXAM_LLM_TIMEOUT_SEC", 60)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_msg}],
            max_tokens=getattr(config, "EXAM_LLM_MAX_TOKENS", 1500),
            temperature=0.3,
            timeout=timeout,
        )
        raw = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        return None, None, f"生成试卷时 LLM 出错: {str(e)[:100]}"

    # 解析 ---PAPER--- 与 ---ANSWER---
    paper_part = ""
    answer_part = ""
    if "---PAPER---" in raw and "---ANSWER---" in raw:
        a, b = raw.split("---PAPER---", 1)
        paper_part, _, answer_part = b.split("---ANSWER---", 2)
    else:
        # 回退：整段当作题目，或按题号拆分
        paper_part = raw
    paper_part = (paper_part or "").strip()
    answer_part = (answer_part or "").strip()

    if not paper_part:
        return None, None, "LLM 未返回有效题目格式，请重试。"

    out_dir = _ensure_exam_dir()
    ts = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    base_name = f"exam_{ts}"

    paper_path = None
    answer_key_path = None

    if output_format == "txt":
        paper_path = os.path.join(out_dir, f"{base_name}_paper.txt")
        answer_key_path = os.path.join(out_dir, f"{base_name}_answer.txt")
        try:
            with open(paper_path, "w", encoding="utf-8") as f:
                f.write(paper_part)
            with open(answer_key_path, "w", encoding="utf-8") as f:
                f.write(answer_part or "（无答案）")
        except Exception as e:
            return None, None, f"写入 TXT 失败: {str(e)}"
    elif output_format == "pdf":
        try:
            from fpdf import FPDF
            paper_path = os.path.join(out_dir, f"{base_name}_paper.pdf")
            answer_key_path = os.path.join(out_dir, f"{base_name}_answer.txt")
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Helvetica", "", 11)
            for line in paper_part.replace("\r", "").split("\n"):
                try:
                    pdf.multi_cell(0, 6, line)
                except Exception:
                    pdf.multi_cell(0, 6, line.encode("latin-1", "replace").decode("latin-1"))
            pdf.output(paper_path)
            with open(answer_key_path, "w", encoding="utf-8") as f:
                f.write(answer_part or "（无答案）")
        except ImportError:
            paper_path = os.path.join(out_dir, f"{base_name}_paper.txt")
            answer_key_path = os.path.join(out_dir, f"{base_name}_answer.txt")
            with open(paper_path, "w", encoding="utf-8") as f:
                f.write(paper_part)
            with open(answer_key_path, "w", encoding="utf-8") as f:
                f.write(answer_part or "（无答案）")
            return paper_path, answer_key_path, "（未安装 fpdf2，已改为 TXT；pip install fpdf2 可生成 PDF）"
        except Exception as e:
            paper_path = os.path.join(out_dir, f"{base_name}_paper.txt")
            answer_key_path = os.path.join(out_dir, f"{base_name}_answer.txt")
            with open(paper_path, "w", encoding="utf-8") as f:
                f.write(paper_part)
            with open(answer_key_path, "w", encoding="utf-8") as f:
                f.write(answer_part or "（无答案）")
            return paper_path, answer_key_path, f"（PDF 生成失败已改为 TXT: {str(e)[:50]}）"
    elif output_format == "docx":
        try:
            from docx import Document
            from docx.shared import Pt
            paper_path = os.path.join(out_dir, f"{base_name}_paper.docx")
            answer_key_path = os.path.join(out_dir, f"{base_name}_answer.txt")
            doc = Document()
            for line in paper_part.replace("\r", "").split("\n"):
                doc.add_paragraph(line)
            doc.save(paper_path)
            with open(answer_key_path, "w", encoding="utf-8") as f:
                f.write(answer_part or "（无答案）")
        except ImportError:
            paper_path = os.path.join(out_dir, f"{base_name}_paper.txt")
            answer_key_path = os.path.join(out_dir, f"{base_name}_answer.txt")
            with open(paper_path, "w", encoding="utf-8") as f:
                f.write(paper_part)
            with open(answer_key_path, "w", encoding="utf-8") as f:
                f.write(answer_part or "（无答案）")
            return paper_path, answer_key_path, "（未安装 python-docx，已改为 TXT；pip install python-docx 可生成 Word）"
        except Exception as e:
            return None, None, f"生成 Word 失败: {str(e)}"

    return paper_path, answer_key_path, ""


def grade_exam(
    student_answer_content: str,
    answer_key_path: str,
    paper_content: str,
) -> Tuple[str, str]:
    """
    根据答案文件和试卷内容，用 LLM 批改学生答案并生成讲解。
    返回 (成绩/总结一句, 详细反馈与讲解)。
    """
    student_answer_content = (student_answer_content or "").strip()
    if not student_answer_content:
        return "未提交答案", "请上传或粘贴你的答案后再批改。"
    if not os.path.isfile(answer_key_path):
        return "无法批改", "未找到答案文件，请先生成试卷。"
    try:
        with open(answer_key_path, "r", encoding="utf-8") as f:
            answer_key = f.read()
    except Exception as e:
        return "无法批改", f"读取答案文件失败: {str(e)}"

    sys_prompt = """你是法语教师。请批改学生答案：对照标准答案逐题判断对错，给出得分（可简要说明每道题对错），然后对错题进行讲解（语法、词汇、正确写法）。回复用中文，结构清晰。"""
    user_msg = f"【标准答案】\n{answer_key[:3000]}\n\n【试卷题目】\n{(paper_content or '（无）')[:2000]}\n\n【学生答案】\n{student_answer_content[:4000]}"

    try:
        client, model = _get_client_and_model()
        timeout = getattr(config, "EXAM_LLM_TIMEOUT_SEC", 60)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_msg}],
            max_tokens=getattr(config, "EXAM_LLM_MAX_TOKENS", 1500),
            temperature=0.2,
            timeout=timeout,
        )
        feedback = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        return "批改失败", f"LLM 批改出错: {str(e)[:150]}"

    # 第一行或前 80 字作为「成绩总结」
    lines = [ln.strip() for ln in feedback.splitlines() if ln.strip()]
    summary = (lines[0][:80] + "…") if lines and len(lines[0]) > 80 else (lines[0] if lines else "已批改")
    return summary, feedback or "（无反馈）"
