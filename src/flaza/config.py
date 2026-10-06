"""appconfig.json 配置模型与读写。

配置文件由程序生成和写回，UI 设置页是用户修改配置的唯一入口。
"""

import json
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict

ThemeName = Literal[
    "nightglow-dark",
    "nightglow-light",
    "planet-plaza-dark",
    "planet-plaza-light",
    "ember-zone-dark",
    "ember-zone-light",
    "cyberangel-dark",
    "cyberangel-light",
]

ChatOpenPosition = Literal["last", "bottom"]

_LEGACY_THEMES: dict[str, ThemeName] = {
    "dark": "nightglow-dark",
    "light": "nightglow-light",
    "deep_blue": "planet-plaza-dark",
}


class LoginConfig(BaseModel):
    """登录与签名服务配置。"""

    model_config = ConfigDict(frozen=True)

    uin: int = 0
    protocol: Literal["linux", "macos", "windows", "custom"] = "linux"
    signer_url: str = "https://"
    signer_token: str = ""
    use_custom: bool = False
    appinfo_path: str = "./appinfo.json"
    use_custom_sign_provider: bool = True
    sign_provider_path: str = "../EulerOneBot/sign_provider.py"
    sign_provider_entry: str = "sign_provider"
    use_ipv6: bool = True
    use_optimum: bool = True


class PathsConfig(BaseModel):
    """协议运行数据路径。"""

    model_config = ConfigDict(frozen=True)

    device_info_path: str = "./device.json"
    sign_info_path: str = "./sig.bin"
    login_info_source_dir: str = "../lagrange-python"
    media_cache_dir: str = "./media_cache"
    chat_cache_path: str = "./chat_cache.json"
    emoji_cache_path: str = "./emoji_cache.json"
    plugins_dir: str = "./plugins"
    plugin_state_path: str = "./plugin_state.json"


class WindowSettings(BaseModel):
    """桌面窗口配置。"""

    model_config = ConfigDict(frozen=True)

    title: str = "Flaza"
    width: int = 960
    height: int = 640
    theme: ThemeName = "nightglow-dark"
    chat_open_position: ChatOpenPosition = "bottom"
    devtools: bool = False


class AppConfig(BaseModel):
    """appconfig.json 顶层配置。"""

    model_config = ConfigDict(frozen=True)

    login: LoginConfig = LoginConfig()
    paths: PathsConfig = PathsConfig()
    window: WindowSettings = WindowSettings()
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    @property
    def login_configured(self) -> bool:
        """是否具备启动登录所需的最小配置。"""
        if self.login.uin <= 0:
            return False
        if self.login.use_custom_sign_provider and Path(self.login.sign_provider_path).is_file():
            return True
        url = urlsplit(self.login.signer_url)
        return url.scheme in ("http", "https") and bool(url.hostname)


def load_config(path: str | Path = "appconfig.json") -> AppConfig:
    """加载配置；文件不存在时生成带默认值的配置文件。"""
    config_path = Path(path)
    if not config_path.exists():
        config = AppConfig()
        save_config(config, config_path)
        return config

    with config_path.open(encoding="utf-8") as file:
        data = json.load(file)
    theme = data.get("window", {}).get("theme")
    if theme in _LEGACY_THEMES:
        data.setdefault("window", {})["theme"] = _LEGACY_THEMES[theme]
    config = AppConfig.model_validate(data)
    login_data = data.get("login")
    if isinstance(login_data, dict) and any(
        key not in login_data
        for key in (
            "use_custom_sign_provider",
            "sign_provider_path",
            "sign_provider_entry",
            "use_ipv6",
            "use_optimum",
        )
    ):
        # 老配置文件补全新签名项，保证 custom sign provider 在文件里可见可改。
        save_config(config, config_path)
    return config


def save_config(config: AppConfig, path: str | Path = "appconfig.json") -> None:
    """把配置写回 appconfig.json。"""
    config_path = Path(path)
    payload = config.model_dump(mode="json")
    config_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
