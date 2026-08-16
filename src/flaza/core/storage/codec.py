"""消息模型的版本化二进制编解码。

数据库 payload 列保存完整 pydantic Message 模型。编码使用 msgpack，
避免 JSON 在 bytes、大整数和复杂嵌套模型上的表达能力限制。
"""

from __future__ import annotations

import msgpack
from pydantic import TypeAdapter

from flaza.core.models import Message

_SCHEMA_VERSION = 1

_message_adapter = TypeAdapter(Message)


def encode_message(message: Message) -> bytes:
    """把 Message 编码为带版本信封的 msgpack 字节串。"""
    envelope = {
        "version": _SCHEMA_VERSION,
        "message": message.model_dump(mode="python"),
    }
    payload = msgpack.packb(envelope, use_bin_type=True)
    if payload is None:
        raise RuntimeError("msgpack 编码失败")
    return payload


def decode_message(blob: bytes) -> Message:
    """从版本化 msgpack 字节串还原并校验 Message 模型。"""
    envelope = msgpack.unpackb(blob, raw=False)
    if not isinstance(envelope, dict):
        raise ValueError("消息载荷信封必须是字典")

    version = envelope.get("version")
    if version != _SCHEMA_VERSION:
        raise ValueError(f"不支持的消息载荷版本: {version!r}")

    raw_message = envelope.get("message")
    if not isinstance(raw_message, dict):
        raise ValueError("消息载荷缺少 message 字段")

    return _message_adapter.validate_python(raw_message)
