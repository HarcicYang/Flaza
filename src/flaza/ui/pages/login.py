"""登录页。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from neony.application.elements import Button, Heading, Progress, Text, VStack
from neony.dom import Computed, Div, DomEvent, Styles

from flaza.config import AppConfig
from flaza.core.models import LoginPhase
from flaza.ui.actions import UiActions
from flaza.ui.components.qr_code import QrCodeView
from flaza.ui.state import UiStateStore


class LoginPage:
    """二维码登录页。"""

    def __init__(
        self,
        state: UiStateStore,
        actions: UiActions,
        config: AppConfig,
        render: Callable[[], Awaitable[None]],
        on_open_settings: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._state = state
        self._actions = actions
        self._config = config
        self._render = render
        self._on_open_settings = on_open_settings

        status = Text("正在启动…", role="secondary")
        status.bind_text(state.login_phase, fmt=lambda phase: f"登录状态：{phase.value}")

        detail = Text("", role="secondary")
        detail.bind_text(state.login_detail)

        qr_view = QrCodeView(state)

        loading_active = Computed(
            lambda: (
                state.login_phase()
                in {
                    LoginPhase.SILENT_LOGGING_IN,
                    LoginPhase.QR_READY,
                    LoginPhase.WAITING_SCAN,
                    LoginPhase.WAITING_CONFIRM,
                    LoginPhase.CONFIRMED,
                }
            )
        )
        loading = Progress(indeterminate=True, label="请稍候…")
        loading_root = loading.build()
        loading_root.bind_visible(loading_active)

        start_button = Button("开始扫码登录")
        start_button.on_click(self._on_start_login)
        settings_button = Button("设置", variant="ghost")
        settings_button.on_click(self._on_open_settings_click)

        panel = VStack(
            Heading("登录 Flaza", level=1),
            status,
            detail,
            qr_view.root,
            loading_root,
            start_button.build(),
            settings_button.build(),
            gap="16px",
            align="center",
            width="360px",
        ).build()

        self.root = Div(
            styles=Styles(
                flex_grow="1",
                width="100%",
                display="flex",
                align_items="center",
                justify_content="center",
                padding="24px",
                overflow_y="auto",
            ),
            container=[panel],
        )

    async def _on_start_login(self, _event: DomEvent) -> None:
        try:
            await self._actions.start_qr_login()
        except Exception:
            # UiActions 内部会把失败写回状态；这里只兜底避免事件处理器崩溃。
            return

    async def _on_open_settings_click(self, _event: DomEvent) -> None:
        if self._on_open_settings is not None:
            await self._on_open_settings()
