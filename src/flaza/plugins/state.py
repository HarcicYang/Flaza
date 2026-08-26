"""插件启停状态、设置与 KV 的 JSON 持久化。"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class PluginState:
    """管理根目录 plugin_state.json，写入采用临时文件加原子替换。"""

    def __init__(self, path: str | Path = "./plugin_state.json") -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._enabled: set[str] = set()
        self._disabled: set[str] = set()
        self._settings: dict[str, dict[str, Any]] = {}
        self._kv: dict[str, dict[str, Any]] = {}

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> None:
        """从磁盘读取状态；文件缺失或损坏时使用空状态。"""
        with self._lock:
            self._enabled.clear()
            self._disabled.clear()
            self._settings.clear()
            self._kv.clear()
            if not self._path.exists():
                return
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                logger.warning("plugin_state.json 无法解析，使用空状态: %s", self._path)
                return
            if not isinstance(data, dict):
                logger.warning("plugin_state.json 顶层必须是 JSON 对象，使用空状态: %s", self._path)
                return
            self._enabled = {str(item) for item in data.get("enabled", []) if isinstance(item, str)}
            self._disabled = {str(item) for item in data.get("disabled", []) if isinstance(item, str)}
            self._settings = _as_nested_dict(data.get("settings"))
            self._kv = _as_nested_dict(data.get("kv"))

    def is_enabled(self, plugin_id: str) -> bool:
        """新发现插件默认启用；disabled 列表只记录被显式禁用的插件。"""
        return plugin_id not in self._disabled

    def set_enabled(self, plugin_id: str, enabled: bool) -> None:
        """设置插件启停状态并立即持久化。"""
        with self._lock:
            if enabled:
                self._enabled.add(plugin_id)
                self._disabled.discard(plugin_id)
            else:
                self._enabled.discard(plugin_id)
                self._disabled.add(plugin_id)
            self._save_locked()

    def get_setting(self, plugin_id: str, key: str, default: Any = None) -> Any:
        return self._settings.get(plugin_id, {}).get(key, default)

    def set_setting(self, plugin_id: str, key: str, value: Any) -> None:
        """写入插件设置并立即持久化。"""
        with self._lock:
            self._settings.setdefault(plugin_id, {})[key] = value
            self._save_locked()

    def delete_setting(self, plugin_id: str, key: str) -> None:
        with self._lock:
            settings = self._settings.get(plugin_id)
            if settings is not None and key in settings:
                del settings[key]
                self._save_locked()

    def all_settings(self, plugin_id: str) -> dict[str, Any]:
        return dict(self._settings.get(plugin_id, {}))

    def kv_get(self, plugin_id: str, key: str, default: Any = None) -> Any:
        return self._kv.get(plugin_id, {}).get(key, default)

    def kv_set(self, plugin_id: str, key: str, value: Any) -> None:
        """写入插件 KV 并立即持久化。"""
        with self._lock:
            self._kv.setdefault(plugin_id, {})[key] = value
            self._save_locked()

    def kv_delete(self, plugin_id: str, key: str) -> None:
        with self._lock:
            kv = self._kv.get(plugin_id)
            if kv is not None and key in kv:
                del kv[key]
                self._save_locked()

    def all_kv(self, plugin_id: str) -> dict[str, Any]:
        return dict(self._kv.get(plugin_id, {}))

    def _save_locked(self) -> None:
        payload = {
            "enabled": sorted(self._enabled),
            "disabled": sorted(self._disabled),
            "settings": self._settings,
            "kv": self._kv,
        }
        if self._path.parent != Path("."):
            self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp_path, self._path)


def _as_nested_dict(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        return {}
    return {str(key): dict(item) for key, item in value.items() if isinstance(item, dict)}
