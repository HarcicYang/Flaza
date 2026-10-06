"""自定义签名提供者测试。"""

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from flaza.config import LoginConfig
from flaza.qq.clients import _build_sign, _load_custom_sign_factory
from flaza.qq.custom_sign import _MODULE_NAME, load_sign_provider

PROVIDER_SOURCE = "\n".join(
    [
        "def sign_provider(sign_url, uin, guid, qua):",
        "    async def get_sign(cmd, seq, buf):",
        '        return {"sign": "ab" * 32, "token": "", "extra": "cd" * 8}',
        "",
        "    return get_sign",
    ]
)


def _write_provider(tmp_path: Path, source: str = PROVIDER_SOURCE) -> str:
    path = tmp_path / "sign_provider.py"
    path.write_text(source, encoding="utf-8")
    return str(path)


def test_loader_returns_factory_under_fixed_module_name(tmp_path: Path) -> None:
    path = _write_provider(tmp_path)
    factory = load_sign_provider(path, "sign_provider")

    assert sys.modules[_MODULE_NAME].__file__ == path
    get_sign = factory(None, 123, "00" * 16, "V1_LNX_NQ_3.2.26_46494_GW_B")
    assert asyncio.run(get_sign("MessageSvc.PbSendMsg", 1, b"\x00")) == {
        "sign": "ab" * 32,
        "token": "",
        "extra": "cd" * 8,
    }


def test_loader_reloads_module_on_each_call(tmp_path: Path) -> None:
    path = _write_provider(tmp_path)
    load_sign_provider(path, "sign_provider")
    first = sys.modules[_MODULE_NAME]

    load_sign_provider(path, "sign_provider")

    assert sys.modules[_MODULE_NAME] is not first


def test_loader_surfaces_missing_file_entry_and_syntax_errors(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_sign_provider(str(tmp_path / "missing.py"), "sign_provider")

    path = _write_provider(tmp_path)
    with pytest.raises(AttributeError):
        load_sign_provider(path, "missing_entry")

    broken = _write_provider(tmp_path, "this is not python(")
    with pytest.raises(SyntaxError):
        load_sign_provider(broken, "sign_provider")


def test_load_factory_falls_back_when_disabled_or_missing(tmp_path: Path) -> None:
    assert _load_custom_sign_factory(LoginConfig(use_custom_sign_provider=False)) is None

    missing = LoginConfig(sign_provider_path=str(tmp_path / "missing.py"))
    assert _load_custom_sign_factory(missing) is None


def test_build_sign_prefers_custom_provider_and_passes_live_context(tmp_path: Path) -> None:
    record_path = tmp_path / "recorded.json"
    path = _write_provider(
        tmp_path,
        "\n".join(
            [
                "import json",
                "def sign_provider(sign_url, uin, guid, qua):",
                f"    with open({str(record_path)!r}, 'w', encoding='utf-8') as f:",
                "        json.dump({'sign_url': sign_url, 'uin': uin, 'guid': guid, 'qua': qua}, f)",
                "    async def get_sign(cmd, seq, buf):",
                "        return {}",
                "",
                "    return get_sign",
            ]
        ),
    )

    login = LoginConfig(
        uin=3672492480,
        sign_provider_path=path,
        signer_url="https://sign.example.com",
        signer_token="secret",
    )
    info = SimpleNamespace(device=SimpleNamespace(guid="ab" * 16))
    app_info = SimpleNamespace(qua="V1_LNX_NQ_3.2.26_46494_GW_B")

    get_sign = _build_sign(login, info, app_info)  # type: ignore[arg-type]

    assert json.loads(record_path.read_text(encoding="utf-8")) == {
        "sign_url": "https://secret@sign.example.com/api/sign/sec-sign",
        "uin": 3672492480,
        "guid": "ab" * 16,
        "qua": "V1_LNX_NQ_3.2.26_46494_GW_B",
    }
    assert asyncio.run(get_sign("MessageSvc.PbSendMsg", 1, b"\x00")) == {}


def test_build_sign_falls_back_to_signer_url(tmp_path: Path) -> None:
    login = LoginConfig(
        uin=3672492480,
        sign_provider_path=str(tmp_path / "missing.py"),
        signer_url="https://sign.example.com",
    )
    info = SimpleNamespace(device=SimpleNamespace(guid="ab" * 16))
    app_info = SimpleNamespace(qua="V1_LNX_NQ_3.2.26_46494_GW_B")

    get_sign = _build_sign(login, info, app_info)  # type: ignore[arg-type]

    assert get_sign is not None
    assert get_sign.__name__ == "get_sign"


def test_build_sign_returns_none_without_any_provider(tmp_path: Path) -> None:
    login = LoginConfig(
        uin=3672492480,
        sign_provider_path=str(tmp_path / "missing.py"),
        signer_url="https://",
    )
    info = SimpleNamespace(device=SimpleNamespace(guid="ab" * 16))
    app_info = SimpleNamespace(qua="V1_LNX_NQ_3.2.26_46494_GW_B")

    assert _build_sign(login, info, app_info) is None  # type: ignore[arg-type]
