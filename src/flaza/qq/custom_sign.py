"""从仓库外的用户文件加载自定义签名实现。

签名文件属于本机私有凭据，默认放在仓库之外；本模块只是加载器，用固定的
模块名执行用户文件，避免和 sys.path 上的任何模块重名。hiro-qq 会在每次运行时
把当前 guid/qua 传给工厂，因此进程内加载一次即可。
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable, Coroutine
from typing import Any, cast

__all__ = ["SignFactory", "SignGetter", "SignResult", "load_sign_provider"]

_MODULE_NAME = "flaza.custom_sign_provider"

SignResult = dict[str, Any]
SignGetter = Callable[[str, int, bytes], Coroutine[Any, Any, SignResult]]
# hiro-qq 的真实调用约定是 (sign_url, uin, guid, qua)；上游类型标注错位了一格。
SignFactory = Callable[[str | None, int, str, str], SignGetter]


def load_sign_provider(path: str, entry: str = "sign_provider") -> SignFactory:
    """从用户文件加载签名工厂，文件不进入仓库。"""
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"签名提供者文件不可导入: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = module
    spec.loader.exec_module(module)
    factory = getattr(module, entry)
    if not callable(factory):
        raise TypeError(f"签名提供者入口不可调用: {path}:{entry}")
    return cast(SignFactory, factory)
