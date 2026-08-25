"""确定性 BM25 检索（DD-19 §11.2，供 Fake 适配器与测试使用）。

- ``tokenize``：ASCII 数字/字母连读小写 + CJK 重叠二元组；标点/空白为分隔符。
  中文无空格分词，二元组是无需外部词典的确定性近似，足够支撑 Fake 适配器的
  确定性测试与开发环境检索。
- ``score_documents``：对给定语料计算 BM25（k1=1.5, b=0.75，idf 平滑 +1 防负值），
  返回按分数降序的 ``(doc_id, score)`` 列表；相同输入结果确定（幂等）。

生产环境 BM25 由 OpenSearch 内建分析器提供，本模块只用于 Fake/确定性测试。
"""

from __future__ import annotations

import math
import re

_K1 = 1.5
_B = 0.75
_ASCII_WORD_RE = re.compile(r"[0-9a-zA-Z]+")
# CJK 码位区间（U+3400 扩展 A 起，覆盖常用简体/繁体），重叠二元组切分
_CJK_RUN_RE = re.compile(r"[㐀-鿿]+")


def tokenize(text: str) -> list[str]:
    """把文本切成稳定 token：ASCII 词小写 + CJK 重叠二元组。"""
    if not text:
        return []
    tokens: list[str] = []
    for word in _ASCII_WORD_RE.findall(text):
        tokens.append(word.casefold())
    for run in _CJK_RUN_RE.findall(text):
        if len(run) == 1:
            tokens.append(run)
            continue
        for i in range(len(run) - 1):
            tokens.append(run[i : i + 2])
    return tokens


def _idf(n_docs: int, df: int) -> float:
    return math.log((n_docs - df + 0.5) / (df + 0.5) + 1.0)


def score_documents(
    corpus: list[tuple[str, str]],
    query: str,
    *,
    k1: float = _K1,
    b: float = _B,
) -> list[tuple[str, float]]:
    """对语料计算 BM25 分数并按降序返回 (doc_id, score)。

    corpus：``[(doc_id, text)]``。doc 长度不足 k1 时会因 tf 上限把分数拉低，
    与标准 BM25 一致。返回空列表当语料为空。
    """
    if not corpus or not query:
        return []
    n_docs = len(corpus)
    doc_terms: list[tuple[str, list[str], float]] = []
    for doc_id, text in corpus:
        terms = tokenize(text)
        if not terms:
            continue
        doc_terms.append((doc_id, terms, float(len(terms))))
    if not doc_terms:
        return []
    avgdl = sum(dl for _, _, dl in doc_terms) / len(doc_terms)

    df: dict[str, int] = {}
    for _, terms, _ in doc_terms:
        for t in set(terms):
            df[t] = df.get(t, 0) + 1

    query_terms = tokenize(query)
    if not query_terms:
        return []

    scored: list[tuple[str, float]] = []
    for doc_id, terms, dl in doc_terms:
        counts: dict[str, int] = {}
        for t in terms:
            counts[t] = counts.get(t, 0) + 1
        score = 0.0
        for q in set(query_terms):
            tf = counts.get(q, 0)
            if tf == 0:
                continue
            denom = tf + k1 * (1 - b + b * dl / avgdl)
            score += _idf(n_docs, df.get(q, 0)) * (tf * (k1 + 1)) / denom
        if score > 0:
            scored.append((doc_id, score))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored
