"""LagrangeQQClient 纯函数测试。"""

from flaza.qq.clients import _build_signer_url


def test_build_signer_url_without_token() -> None:
    assert _build_signer_url("https://sign.example.com", "") == "https://sign.example.com/api/sign/sec-sign"


def test_build_signer_url_with_token() -> None:
    url = _build_signer_url("https://sign.example.com", "secret")
    assert url == "https://secret@sign.example.com/api/sign/sec-sign"


def test_build_signer_url_empty() -> None:
    assert _build_signer_url("", "") is None
