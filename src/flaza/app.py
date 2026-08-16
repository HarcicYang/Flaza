"""Flaza 应用组装根。

在这里完成配置、存储、事件总线、协议实现、核心服务和 Neony UI 的接线。
"""

from __future__ import annotations

import asyncio
import logging

from neony.application import DARK, DEEP_BLUE, LIGHT, NeonApplication, Page, Theme
from neony.application.config import Config as NeonyConfig
from neony.application.config import WebViewConfig
from neony.application.config import WindowConfig as NeonyWindowConfig
from neony.application.elements import Heading, Text, VStack

from flaza.config import AppConfig, load_config
from flaza.core.events import EventBus, LoginPhaseChanged, MessageReceived
from flaza.core.models import LoginPhase
from flaza.core.services import AccountService, ContactService, MessageService
from flaza.core.storage import Storage
from flaza.qq.api import LagrangeQQClient
from flaza.ui.state import UiStateStore

_THEME_MAP: dict[str, Theme] = {
    "dark": DARK,
    "light": LIGHT,
    "deep_blue": DEEP_BLUE,
}


def create_page(state: UiStateStore) -> Page:
    """构建基础窗口页面。"""
    status = Text("正在启动…", role="secondary")
    status.bind_text(state.login_phase, fmt=lambda phase: f"登录状态：{phase.value}")

    account = Text("", role="secondary")
    account.bind_text(
        state.self_info,
        fmt=lambda info: f"账号：{info.nickname}（{info.uin}）" if info else "账号：未登录",
    )

    return Page(gap="16px").add(
        VStack(
            Heading("Flaza", level=1),
            Text("基于 lagrange-python 与 Neony 的 QQ 桌面客户端。", role="secondary"),
            status,
            account,
            gap="12px",
        )
    )


def build_application(config: AppConfig) -> tuple[NeonApplication[UiStateStore], UiStateStore]:
    """构造完整的应用对象图，不启动任何异步任务。"""
    storage = Storage()
    bus = EventBus()
    qq = LagrangeQQClient(config.login, config.paths, bus)
    account_service = AccountService(qq, bus)
    contact_service = ContactService(qq, storage, bus)
    message_service = MessageService(qq, storage, bus)

    state = UiStateStore(storage)

    # 入站消息先持久化，再更新 UI 状态。
    bus.subscribe(MessageReceived, message_service.on_message_received)

    async def on_login_phase(event: LoginPhaseChanged) -> None:
        if event.phase is LoginPhase.ONLINE:
            await contact_service.sync()

    bus.subscribe(LoginPhaseChanged, on_login_phase)
    state.wire(bus)

    window = config.window
    neony_config = NeonyConfig(
        window=NeonyWindowConfig(
            title=window.title,
            width=window.width,
            height=window.height,
        ),
        webview=WebViewConfig(devtools=window.devtools),
    )
    app = NeonApplication[UiStateStore](neony_config, state=state)
    app.theme = _THEME_MAP[window.theme]

    bus_task: asyncio.Task[None] | None = None

    async def render() -> None:
        try:
            await app.render()
        except RuntimeError:
            # Neony 尚未运行时忽略；正式事件只会发生在运行之后。
            return

    state.set_render(render)

    async def on_ready() -> None:
        nonlocal bus_task
        await storage.init("flaza.db")
        bus_task = asyncio.create_task(bus.run(), name="flaza-event-bus")
        await qq.start()
        await account_service.start()

    async def on_close() -> None:
        nonlocal bus_task
        await account_service.stop()
        await qq.stop()
        if bus_task is not None:
            bus_task.cancel()
            await asyncio.gather(bus_task, return_exceptions=True)
            bus_task = None
        await storage.close()

    app.ready_handler = on_ready
    app.close_handler = on_close
    return app, state


def main() -> None:
    """启动 Flaza 桌面应用。"""
    config = load_config()
    logging.basicConfig(level=getattr(logging, config.log_level))
    app, state = build_application(config)
    app.run(create_page(state))
