"""manifest 解析与依赖检查测试。"""

import importlib.metadata
import json
from pathlib import Path

import pytest

from flaza.plugins.manifest import (
    PluginDiscovery,
    PluginManifest,
    check_dependencies,
)


def test_discovery_loads_valid_manifest(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugins" / "hello"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": "hello",
                "name": "示例插件",
                "version": "0.1.0",
                "entry": "main.py",
                "dependencies": ["httpx>=0.28"],
            }
        ),
        encoding="utf-8",
    )

    candidates = PluginDiscovery(tmp_path / "plugins").discover()

    assert len(candidates) == 1
    assert candidates[0].manifest.id == "hello"
    assert candidates[0].manifest.dependencies == ["httpx>=0.28"]


def test_discovery_skips_invalid_and_duplicate_manifests(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    bad = root / "bad"
    bad.mkdir(parents=True)
    (bad / "manifest.json").write_text("{not json", encoding="utf-8")
    for name in ("first", "second"):
        plugin_dir = root / name
        plugin_dir.mkdir()
        (plugin_dir / "manifest.json").write_text(json.dumps({"id": "same"}), encoding="utf-8")

    candidates = PluginDiscovery(root).discover()

    assert len(candidates) == 1
    assert candidates[0].manifest.id == "same"


def test_dependency_check_reports_missing_and_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_version(name: str) -> str:
        if name == "httpx":
            return "0.27.0"
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", fake_version)
    manifest = PluginManifest(
        id="dep-check",
        dependencies=[
            "httpx>=0.28",
            "flaza-missing",
            "not a || requirement",
        ],
    )

    issues = check_dependencies(manifest)

    assert len(issues) == 3
    assert issues[0].requirement == "httpx>=0.28"
    assert issues[1].detail == "未安装"
