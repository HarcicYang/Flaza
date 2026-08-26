"""插件目录发现与 manifest.json 解析。"""

from __future__ import annotations

import importlib.metadata
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)


class PluginManifest(BaseModel):
    """插件目录根部的 manifest.json。"""

    id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$",
    )
    name: str = ""
    version: str = ""
    entry: str = "main.py"
    author: str = ""
    description: str = ""
    dependencies: list[str] = []

    @classmethod
    def load(cls, path: Path) -> PluginManifest:
        """从 JSON 文件加载并校验 manifest。"""
        with path.open(encoding="utf-8") as file:
            data = json.load(file)
        return cls.model_validate(data)


@dataclass(frozen=True)
class PluginCandidate:
    """已通过 manifest 校验的插件目录。"""

    path: Path
    manifest: PluginManifest


class PluginDiscovery:
    """扫描插件根目录，返回可加载的候选插件。"""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def discover(self) -> list[PluginCandidate]:
        """读取根目录下的 manifest.json；无效目录记录警告并跳过。"""
        if not self.root.is_dir():
            return []

        candidates: list[PluginCandidate] = []
        seen_ids: set[str] = set()
        for child in sorted(self.root.iterdir()):
            if not child.is_dir():
                continue
            manifest_path = child / "manifest.json"
            if not manifest_path.is_file():
                continue
            try:
                manifest = PluginManifest.load(manifest_path)
            except (json.JSONDecodeError, ValidationError, OSError):
                logger.warning("插件 manifest 无法解析，跳过: %s", manifest_path)
                continue
            if manifest.id in seen_ids:
                logger.warning("插件 id 重复，跳过: %s", manifest.id)
                continue
            seen_ids.add(manifest.id)
            candidates.append(PluginCandidate(path=child, manifest=manifest))
        return candidates


@dataclass(frozen=True)
class DependencyIssue:
    """一条未满足的插件依赖说明。"""

    requirement: str
    detail: str


def check_dependencies(manifest: PluginManifest) -> list[DependencyIssue]:
    """检查 PEP 508 依赖是否已安装；缺失或版本不符只记录，不阻止加载。"""
    issues: list[DependencyIssue] = []
    for raw in manifest.dependencies:
        try:
            requirement = Requirement(raw)
        except InvalidRequirement as exc:
            issues.append(DependencyIssue(requirement=raw, detail=f"声明无法解析：{exc}"))
            continue
        try:
            installed = importlib.metadata.version(requirement.name)
        except importlib.metadata.PackageNotFoundError:
            issues.append(DependencyIssue(requirement=raw, detail="未安装"))
            continue
        if installed not in requirement.specifier:
            issues.append(
                DependencyIssue(
                    requirement=raw,
                    detail=f"已安装 {installed}，不满足 {requirement.specifier}",
                )
            )
    return issues
