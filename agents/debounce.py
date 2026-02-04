# -*- coding: utf-8 -*-
"""Agent B：OCR 结果去抖动，最近 N 次中至少 K 次相同（或相似）才视为稳定。"""
from __future__ import annotations

from collections import deque
from typing import Optional

import difflib


def _normalize_for_vote(text: str) -> str:
    """用于投票的归一化：去首尾空白、合并空白。"""
    return " ".join((text or "").strip().split())


def text_similarity(a: str, b: str) -> float:
    """简单相似度：0~1，1 表示完全相同，用于“软稳定”判断。"""
    a_n = _normalize_for_vote(a)
    b_n = _normalize_for_vote(b)
    if not a_n and not b_n:
        return 1.0
    if not a_n or not b_n:
        return 0.0
    return difflib.SequenceMatcher(None, a_n, b_n).ratio()


class OCRDebouncer:
    """
    保留最近 N 次 raw_text；get_stable() 返回出现次数 >= min_votes 的文本（优先最多），
    否则返回最近一次。similarity_vote > 0 时按“相似即同段”投票，减少轻微移动就重识。
    """
    def __init__(
        self,
        history_len: int = 3,
        min_votes: int = 2,
        similarity_vote: float = 0.0,
    ):
        self._history_len = max(1, history_len)
        self._min_votes = max(1, min_votes)
        self._similarity_vote = max(0.0, min(1.0, float(similarity_vote)))
        self._q: deque[str] = deque(maxlen=self._history_len)

    def add(self, raw_text: str) -> None:
        normalized = _normalize_for_vote(raw_text)
        self._q.append(normalized)

    def get_stable(self) -> str:
        """返回稳定文本：若某值（或相似簇）出现次数 >= min_votes 则返回该代表，否则返回最近一次。"""
        if not self._q:
            return ""
        if self._similarity_vote <= 0:
            from collections import Counter
            c = Counter(self._q)
            most_common = c.most_common(1)
            if most_common and most_common[0][1] >= self._min_votes:
                return most_common[0][0]
            return self._q[-1]
        # 相似投票：与某代表相似度 >= threshold 的算同一段，取票数最高且 >= min_votes 的代表
        best_count = 0
        best_representative: Optional[str] = None
        seen: set = set()
        for candidate in self._q:
            if candidate in seen:
                continue
            count = sum(
                1 for t in self._q
                if text_similarity(candidate, t) >= self._similarity_vote
            )
            if count >= self._min_votes and count > best_count:
                best_count = count
                best_representative = candidate
            seen.add(candidate)
        if best_representative is not None:
            return best_representative
        return self._q[-1]

    def is_stable(self) -> bool:
        """当前窗口内是否存在出现次数 >= min_votes 的文本（或相似簇）。"""
        if not self._q:
            return False
        if self._similarity_vote <= 0:
            from collections import Counter
            c = Counter(self._q)
            most_common = c.most_common(1)
            return bool(most_common and most_common[0][1] >= self._min_votes)
        best_count = 0
        for candidate in self._q:
            count = sum(
                1 for t in self._q
                if text_similarity(candidate, t) >= self._similarity_vote
            )
            if count > best_count:
                best_count = count
        return best_count >= self._min_votes

    def is_soft_stable(self, similarity_threshold: float = 0.85) -> bool:
        """
        软稳定：当前文本与“稳定文本”足够相似就认为稳定，用于你说的
        “画面还略抖但文字差不多就让 LLM 上”的场景。
        """
        if not self._q:
            return False
        stable = self.get_stable()
        last = self._q[-1]
        return text_similarity(stable, last) >= similarity_threshold
