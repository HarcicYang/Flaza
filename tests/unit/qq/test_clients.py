"""LagrangeQQClient 纯函数测试。"""

from flaza.qq.clients import _build_signer_url, _sync_start


def test_build_signer_url_without_token() -> None:
    assert _build_signer_url("https://sign.example.com", "") == "https://sign.example.com/api/sign/sec-sign"


def test_build_signer_url_with_token() -> None:
    url = _build_signer_url("https://sign.example.com", "secret")
    assert url == "https://secret@sign.example.com/api/sign/sec-sign"


def test_build_signer_url_empty() -> None:
    assert _build_signer_url("", "") is None


def test_sync_start() -> None:
    assert _sync_start(10, 10, 500) is None
    assert _sync_start(10, 20, 500) == 11
    assert _sync_start(0, 1000, 100) == 901
