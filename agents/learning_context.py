# -*- coding: utf-8 -*-
"""
学情上下文：为法语教学系统提供「学情摘要」注入助手长期记忆，并支持「记录学情」写入。
复用现有 VOICE_ASSISTANT_MEMORY 机制，本模块只负责从文件读取/追加，供 voice_assistant_agent 拼入 memory。
"""
from __future__ import annotations

import os
import threading
from typing import Optional

# 项目根目录（与 config 一致）
_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_lock = threading.Lock()

# 学情文件最大行数，超出只保留最近部分
MAX_LINES = 200


def _learning_file_path() -> str:
    import config
    rel = (getattr(config, "FRENCH_TEACHING_LEARNING_FILE", "") or "logs/learning_context.txt").strip()
    if os.path.isabs(rel):
        return rel
    return os.path.join(_ROOT_DIR, rel)


def get_learning_summary_for_prompt(max_chars: int = 1200) -> str:
    """
    读取学情文件内容，供拼入助手的【长期记忆】。若文件不存在或为空则返回空字符串。
    """
    path = _learning_file_path()
    with _lock:
        try:
            if not os.path.isfile(path):
                return ""
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            text = "".join(lines).strip()
            if not text:
                return ""
            if len(text) <= max_chars:
                return text
            return text[-max_chars:].strip()
        except Exception:
            return ""


def append_learning_record(content: str, prefix: str = "已学/已讲: ") -> bool:
    """
    将一条学情记录追加到文件末尾；若目录不存在会尝试创建。返回是否写入成功。
    """
    content = (content or "").strip()
    if not content:
        return False
    path = _learning_file_path()
    with _lock:
        try:
            d = os.path.dirname(path)
            if d and not os.path.isdir(d):
                os.makedirs(d, exist_ok=True)
            line = (prefix or "") + content + "\n"
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
            # 可选：限制行数，避免文件过大
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if len(lines) > MAX_LINES:
                with open(path, "w", encoding="utf-8") as f:
                    f.writelines(lines[-MAX_LINES:])
            return True
        except Exception:
            return False
