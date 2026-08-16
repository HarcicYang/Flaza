"""配置读写测试。"""

from pathlib import Path

from flaza.config import AppConfig, load_config, save_config


def test_load_config_creates_default_file(tmp_path: Path) -> None:
    path = tmp_path / "appconfig.json"
    config = load_config(path)

    assert isinstance(config, AppConfig)
    assert config.login.uin == 0
    assert path.exists()


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "appconfig.json"
    config = AppConfig(login={"uin": 123456}, window={"width": 1280, "height": 800})
    save_config(config, path)

    loaded = load_config(path)
    assert loaded.login.uin == 123456
    assert loaded.window.width == 1280
    assert loaded.window.height == 800
