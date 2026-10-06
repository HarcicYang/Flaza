"""通知中心对话框：待处理的好友申请、入群申请与群邀请。"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from neony.application.elements import Button, Dialog, DialogAction, Spacer, Text, VStack
from neony.application.theme import stub
from neony.dom import Div, Styles

from flaza.core.models import PendingRequest, RequestKind
from flaza.ui.actions import UiActions
from flaza.ui.state import UiStateStore

logger = logging.getLogger(__name__)

_KIND_LABEL = {
    RequestKind.FRIEND: "好友申请",
    RequestKind.GROUP_JOIN: "入群申请",
    RequestKind.GROUP_INVITE: "群邀请",
}

_ROW = Styles(
    display="flex",
    align_items="center",
    gap="10px",
    padding="10px 12px",
    border="1px solid var(--color-border)",
    border_radius="8px",
    background_color=stub.surface_raised,
)


class RequestCenterDialog:
    """列出待处理申请，并提供同意 / 拒绝 / 刷新动作。"""

    def __init__(
        self,
        state: UiStateStore,
        actions: UiActions,
        *,
        on_changed: Callable[[], Awaitable[None]],
        on_error: Callable[[str], Awaitable[None]],
    ) -> None:
        self._state = state
        self._actions = actions
        self._on_changed = on_changed
        self._on_error = on_error
        self.dialog = Dialog(
            title="通知中心",
            content=self._build_content(),
            open=True,
            width="480px",
            actions=[
                DialogAction("刷新", variant="ghost", close_on_click=False, on_click=self._on_refresh),
                DialogAction("关闭", variant="ghost"),
            ],
        )

    def _build_content(self):
        requests = self._state.requests()
        if not requests:
            empty = VStack(Text("暂无待处理通知", role="secondary"), gap="8px", align="center").build()
            empty.styles = empty.styles.model_copy(update={"padding": "24px 0"})
            return empty
        return VStack(*(self._build_row(item) for item in requests), gap="8px", align="stretch").build()

    def _build_row(self, request: PendingRequest) -> Div:
        subtitle = request.subtitle or _KIND_LABEL[request.kind]
        approve = Button("同意", variant="primary", disabled=not request.can_respond)
        approve.on_click(self._make_respond(request, True))
        reject = Button("拒绝", variant="ghost", disabled=not request.can_respond)
        reject.on_click(self._make_respond(request, False))
        return Div(
            styles=_ROW,
            container=[
                VStack(
                    Text(request.title, weight="600", size="14px"),
                    Text(subtitle, role="secondary", size="12px"),
                    gap="4px",
                    align="stretch",
                ).build(),
                Spacer().build(),
                approve.build(),
                reject.build(),
            ],
        )

    def _make_respond(self, request: PendingRequest, accept: bool):
        async def handler(_event: Any = None) -> None:
            try:
                await self._actions.respond_request(request, accept)
            except Exception:
                logger.exception("处理申请失败: key=%s", request.key)
                await self._on_error("处理申请失败")
                return
            await self._on_changed()

        return handler

    async def _on_refresh(self, _dialog: Any = None) -> None:
        await self._actions.refresh_requests()
        await self._on_changed()
