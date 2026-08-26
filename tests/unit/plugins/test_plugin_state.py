"""插件 JSON 状态持久化测试。"""

from flaza.plugins.state import PluginState


def test_plugin_state_roundtrip(tmp_path) -> None:
    path = tmp_path / "plugin_state.json"
    state = PluginState(path)
    assert state.is_enabled("demo") is True

    state.set_enabled("demo", True)
    state.set_enabled("muted", False)
    state.set_setting("demo", "theme", "dark")
    state.kv_set("demo", "counter", 3)

    loaded = PluginState(path)
    loaded.load()

    assert loaded.is_enabled("demo") is True
    assert loaded.is_enabled("muted") is False
    assert loaded.is_enabled("new-plugin") is True
    assert loaded.get_setting("demo", "theme") == "dark"
    assert loaded.kv_get("demo", "counter") == 3
    assert not path.with_suffix(".json.tmp").exists()


def test_plugin_state_ignores_corrupted_file(tmp_path) -> None:
    path = tmp_path / "plugin_state.json"
    path.write_text("{broken", encoding="utf-8")
    state = PluginState(path)

    state.load()

    assert state.is_enabled("anything") is True
    assert state.get_setting("anything", "key") is None
