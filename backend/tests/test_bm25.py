"""确定性 BM25 token 与打分测试（DD-19 §11.2，Phase 5 检索）。

覆盖：ASCII 小写、CJK 重叠二元组、混合 token、BM25 排序、空输入确定性。
"""

from __future__ import annotations

from app.search.bm25 import score_documents, tokenize


def test_tokenize_ascii_lowercase_and_punctuation() -> None:
    # ASCII 词（小写）与 CJK 组分别收集，词袋语义下顺序不影响 BM25
    assert tokenize("E3800 的 SMB V3") == ["e3800", "smb", "v3", "的"]
    assert tokenize("7.0.3.3.3490") == ["7", "0", "3", "3", "3490"]
    assert tokenize("") == []


def test_tokenize_cjk_overlapping_bigrams() -> None:
    tokens = tokenize("防病毒吞吐量")
    assert tokens == ["防病", "病毒", "毒吞", "吞吐", "吐量"]
    # 单个 CJK 字符保留原样；连续 CJK 用重叠二元组
    assert tokenize("的") == ["的"]
    assert tokenize("内存") == ["内存"]


def test_tokenize_deterministic() -> None:
    text = "G1280D 国产化型号 海光 C86 3350"
    assert tokenize(text) == tokenize(text)


def test_bm25_prefers_matching_doc() -> None:
    corpus = [
        ("spec", "T90000 CPU 是 AMD EPYC 7H12 内存 256GB 磁盘 16TB"),
        ("other", "防毒墙支持网桥模式 路由模式 反向代理模式"),
        ("close", "T90000 接口为半高非 Bypass 双口万兆"),
    ]
    ranked = score_documents(corpus, "T90000 内存 256GB")
    assert ranked and ranked[0][0] == "spec"
    # 相同输入结果确定（幂等）
    assert score_documents(corpus, "T90000 内存 256GB") == ranked


def test_bm25_no_query_or_empty_corpus() -> None:
    assert score_documents([], "anything") == []
    assert score_documents([("a", "text")], "") == []
    assert score_documents([("a", "text")], "   ") == []


def test_bm25_ranks_only_relevant_above_zero() -> None:
    corpus = [("a", "苹果 香蕉"), ("b", "香蕉 葡萄")]
    ranked = score_documents(corpus, "苹果")
    assert [doc for doc, _ in ranked] == ["a"]
