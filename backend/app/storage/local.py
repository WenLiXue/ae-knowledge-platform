"""本地文件对象存储。

对象存储接入前的过渡实现：Worker FETCH 的 raw 内容按 key 写入本地目录。
key 结构对齐 DD-04 §7（raw/{source_id}/{version_id}/original.json），
替换为真实对象存储时保持同一 put/get 契约即可。
"""

from __future__ import annotations

from pathlib import Path


class LocalObjectStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def put(self, key: str, data: bytes) -> str:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    def get(self, key: str) -> bytes:
        return (self.root / key).read_bytes()

    def exists(self, key: str) -> bool:
        return (self.root / key).exists()
