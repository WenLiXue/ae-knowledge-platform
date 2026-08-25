"""版本化检索引擎 mapping（DD-19 §11.2）。

索引文档 ID 稳定格式：`chunk:{chunk_id}:generation:{generation}`（DD-04 §6.7）。
字段覆盖：正文、向量、source/version/chunk ID、标题、heading_path、locator、
产品、版本、文档类型、产品形态、更新时间、来源优先级、generation。
"""

from __future__ import annotations

MAPPING_VERSION = "1"

INDEX_MAPPING = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
        # kNN 需要的向量维度在 ensure_index 时按实际 embedding 维度填充
    },
    "mappings": {
        "properties": {
            "doc_id": {"type": "keyword"},
            "chunk_id": {"type": "keyword"},
            "generation": {"type": "keyword"},
            "source_id": {"type": "keyword"},
            "version_id": {"type": "keyword"},
            "content": {"type": "text"},
            "embedding": {"type": "knn_vector", "dimension": 768},
            "content_sha256": {"type": "keyword"},
            "heading_path": {"type": "keyword"},
            "locator": {"enabled": False},
            "chunk_type": {"type": "keyword"},
            "ordinal": {"type": "integer"},
            "title": {"type": "text"},
            "product_code": {"type": "keyword"},
            "product_version_code": {"type": "keyword"},
            "document_type_code": {"type": "keyword"},
            "product_form_code": {"type": "keyword"},
            "source_modified_at": {"type": "date"},
            "source_priority": {"type": "integer"},
        }
    },
}


def doc_id(chunk_id: str, generation: str) -> str:
    return f"chunk:{chunk_id}:generation:{generation}"
