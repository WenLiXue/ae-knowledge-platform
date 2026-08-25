"""文档向量化（DD-19 §11.1）。"""

from .service import EmbeddingError, EmbeddingItem, EmbeddingRunResult, embed_chunks

__all__ = [
    "EmbeddingError",
    "EmbeddingItem",
    "EmbeddingRunResult",
    "embed_chunks",
]
