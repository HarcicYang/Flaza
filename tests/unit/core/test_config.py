"""配置读写测试。"""

import json
from pathlib import Path

from flaza.config import AppConfig, load_config, save_config


def test_load_config_creates_default_file(tmp_path: Path) -> None:
    path = tmp_path / "appconfig.json"
    config = load_config(path)

    assert isinstance(config, AppConfig)
    assert config.login.uin == 0
    assert config.paths.media_cache_dir == "./media_cache"
    assert path.exists()
    assert config.window.theme == "nightglow-dark"
    assert config.window.chat_open_position == "bottom"


def test_load_config_migrates_legacy_theme(tmp_path: Path) -> None:
    path = tmp_path / "appconfig.json"
    path.write_text(json.dumps({"window": {"theme": "deep_blue"}}), encoding="utf-8")

    config = load_config(path)

    assert config.window.theme == "planet-plaza-dark"


def test_load_config_persists_missing_sign_provider_defaults(tmp_path: Path) -> None:
    path = tmp_path / "appconfig.json"
    path.write_text(json.dumps({"login": {"uin": 123}}), encoding="utf-8")

    config = load_config(path)

    assert config.login.use_custom_sign_provider is True
    assert config.login.sign_provider_path == "../EulerOneBot/sign_provider.py"
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["login"]["use_custom_sign_provider"] is True
    assert stored["login"]["sign_provider_path"] == "../EulerOneBot/sign_provider.py"
    assert stored["login"]["use_ipv6"] is True
    assert stored["login"]["use_optimum"] is True


def test_login_configured_requires_uin_and_signer_url() -> None:
    assert AppConfig().login_configured is False
    assert AppConfig(login={"uin": 123, "signer_url": "https://sign.example.com"}).login_configured is True
    assert AppConfig(login={"uin": 0, "signer_url": "https://sign.example.com"}).login_configured is False
    assert (
        AppConfig(
            login={
                "uin": 123,
                "signer_url": "https://",
                "use_custom_sign_provider": False,
            }
        ).login_configured
        is False
    )


def test_login_configured_accepts_existing_custom_sign_provider(tmp_path: Path) -> None:
    provider = tmp_path / "sign_provider.py"
    provider.write_text("def sign_provider(sign_url, uin, guid, qua):\n    return None\n", encoding="utf-8")

    config = AppConfig(
        login={
            "uin": 123,
            "signer_url": "https://",
            "sign_provider_path": str(provider),
        }
    )

    assert config.login.use_custom_sign_provider is True
    assert config.login_configured is True


def test_login_configured_falls_back_when_custom_provider_is_disabled(tmp_path: Path) -> None:
    provider = tmp_path / "sign_provider.py"
    provider.write_text("def sign_provider(sign_url, uin, guid, qua):\n    return None\n", encoding="utf-8")

    config = AppConfig(
        login={
            "uin": 123,
            "signer_url": "https://sign.example.com",
            "use_custom_sign_provider": False,
            "sign_provider_path": str(provider),
        }
    )

    assert config.login_configured is True


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "appconfig.json"
    config = AppConfig(
        login={"uin": 123456},
        window={"width": 1280, "height": 800, "chat_open_position": "last"},
    )
    save_config(config, path)

    loaded = load_config(path)
    assert loaded.login.uin == 123456
    assert loaded.window.width == 1280
    assert loaded.window.height == 800
    assert loaded.window.chat_open_position == "last"


def test_login_network_switches_default_and_roundtrip(tmp_path: Path) -> None:
    assert AppConfig().login.use_ipv6 is True
    assert AppConfig().login.use_optimum is True

    path = tmp_path / "appconfig.json"
    config = AppConfig(login={"uin": 123, "use_ipv6": False, "use_optimum": False})
    save_config(config, path)

    loaded = load_config(path)
    assert loaded.login.use_ipv6 is False
    assert loaded.login.use_optimum is False
