"""凭据信封加密（AES-256-GCM）。

用于 external_credentials 中 user_access_token / refresh_token 的加密存储：
- 明文 token 永不落库、不进入日志、不进入 API 响应；
- 每次加密使用随机 nonce，密文结构为 base64(nonce || ciphertext)；
- 密钥来自配置 token_enc_key（base64 编码的 32 字节），生产环境须用密钥管理/部署变量覆盖。
"""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NONCE_SIZE = 12


def derive_key(key_b64: str) -> bytes:
    """解析配置密钥；必须是 base64 编码的 32 字节。"""
    try:
        key = base64.b64decode(key_b64)
    except (ValueError, TypeError) as exc:
        raise ValueError("token_enc_key 不是合法 base64") from exc
    if len(key) != 32:
        raise ValueError("token_enc_key 必须是 base64 编码的 32 字节密钥")
    return key


def encrypt(plaintext: str, key_b64: str) -> bytes:
    """加密明文，返回 base64(nonce || ciphertext)。"""
    key = derive_key(key_b64)
    nonce = os.urandom(_NONCE_SIZE)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ciphertext)


def decrypt(payload: bytes, key_b64: str) -> str:
    """解密密文并返回明文；payload 为 encrypt 的输出。"""
    key = derive_key(key_b64)
    raw = base64.b64decode(payload)
    if len(raw) < _NONCE_SIZE + 1:
        raise ValueError("密文格式不正确")
    nonce, ciphertext = raw[:_NONCE_SIZE], raw[_NONCE_SIZE:]
    return AESGCM(key).decrypt(nonce, ciphertext, None).decode("utf-8")
