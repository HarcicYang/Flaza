"""Flaza 应用入口与组装。

在这里创建 ApplicationRuntime、NeonApplication 和根 Page。
"""

from __future__ import annotations

import logging

from neony.application import NeonApplication, Page
from neony.application.config import Config as NeonyConfig
from neony.application.config import WebViewConfig
from neony.application.config import WindowConfig as NeonyWindowConfig
from neony.application.protocols import local_files
from neony.dom import KeyFrame, Props

from flaza.config import AppConfig, load_config
from flaza.runtime import THEME_MAP, ApplicationRuntime
from flaza.ui.state import UiStateStore


def register_page_keyframes(app: NeonApplication[UiStateStore]) -> None:
    """注册页面切换动画（设置页开启/关闭）。"""
    app.register_keyframe(
        KeyFrame("flaza-page-in")
        .set("0%", Props(opacity=0.0, transform="translateY(10px)"))
        .set("100%", Props(opacity=1.0, transform="translateY(0)"))
    )
    app.register_keyframe(
        KeyFrame("flaza-page-out")
        .set("0%", Props(opacity=1.0, transform="translateY(0)"))
        .set("100%", Props(opacity=0.0, transform="translateY(-8px)"))
    )


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
    # local_files 提供 neony://local/<路径> 协议：页面非 file:// origin，
    # WebKit 拦截 file:// 子资源，本地媒体（视频/音频/文件）须经此协议。
    app = NeonApplication[UiStateStore](neony_config, state=runtime.state, protocols=[local_files])
    app.theme = THEME_MAP[window.theme]
    app.ready_handler = runtime.on_ready
    app.close_handler = runtime.on_close
    register_page_keyframes(app)

    runtime.attach_neony_app(app)
    return app, runtime


def main() -> None:
    """启动 Flaza 桌面应用。"""
    config = load_config()
    logging.basicConfig(level=getattr(logging, config.log_level))
    app, runtime = build_application(config)
    app.run(create_page(runtime))
