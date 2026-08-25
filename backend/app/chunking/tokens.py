"""确定性 token 近似估算（DD-19 §10，无外部 tokenizer 依赖）。

CJK 字符按 1 token，其余字符按每 3 个 1 token（向上取整）。该近似用于切片预算与
重叠控制，同一输入结果确定；真实评测阶段（Phase 7 黄金集）再据此微调参数。
"""

from __future__ import annotations

# (lo, hi) 闭区间
_CJK_RANGES = (
    (0x3400, 0x4DBF),    # 扩展 A
    (0x4E00, 0x9FFF),    # 统一表意文字
    (0xF900, 0xFAFF),    # 兼容表意文字
    (0x3000, 0x303F),    # CJK 标点
    (0xFF00, 0xFFEF),    # 全角形式
    (0x20000, 0x2A6DF),  # 扩展 B
)


def is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _CJK_RANGES)


def estimate_tokens(text: str) -> int:
    """CJK 字符按 1 token；其余字符按 ceil(len/3) 估算。空文本返回 0。"""
    if not text:
        return 0
    cjk = 0
    other = 0
    for ch in text:
        if is_cjk(ch):
            cjk += 1
        else:
            other += 1
    return cjk + (other + 2) // 3
