"""Flaza 应用入口与组装。

在这里创建 ApplicationRuntime、NeonApplication 和根 Page。
"""

from __future__ import annotations

import logging

from neony.application import DARK, DEEP_BLUE, LIGHT, NeonApplication, Page, Theme
from neony.application.config import Config as NeonyConfig
from neony.application.config import WebViewConfig
from neony.application.config import WindowConfig as NeonyWindowConfig

from flaza.config import AppConfig, load_config
from flaza.runtime import ApplicationRuntime
from flaza.ui.state import UiStateStore

_THEME_MAP: dict[str, Theme] = {
    "dark": DARK,
    "light": LIGHT,
    "deep_blue": DEEP_BLUE,
}


def create_page(runtime: ApplicationRuntime) -> Page:
    """构建填满窗口的根页面。"""
    runtime.shell.root.styles = runtime.shell.root.styles.model_copy(update={"height": "100%", "overflow": "hidden"})
    return Page(fill=True, padding="0px", max_width="100%").add(runtime.shell.root)


def build_application(config: AppConfig) -> tuple[NeonApplication[UiStateStore], ApplicationRuntime]:
    """构造应用对象图，不启动异步任务。"""
    runtime = ApplicationRuntime(config)

    window = config.window
    neony_config = NeonyConfig(
        window=NeonyWindowConfig(
            title=window.title,
            width=window.width,
            height=window.height,
            decorations=False,
        ),
        webview=WebViewConfig(devtools=window.devtools),
    )
    app = NeonApplication[UiStateStore](neony_config, state=runtime.state)
    app.theme = _THEME_MAP[window.theme]
    app.ready_handler = runtime.on_ready
    app.close_handler = runtime.on_close

    runtime.attach_neony_app(app)
    return app, runtime


def main() -> None:
    """启动 Flaza 桌面应用。"""
    config = load_config()
    logging.basicConfig(level=getattr(logging, config.log_level))
    app, runtime = build_application(config)
    app.run(create_page(runtime))
