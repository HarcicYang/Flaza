"""资料卡对话框：查看好友/群成员资料并点赞。"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from neony.application.elements import Dialog, DialogAction, Text, VStack

from flaza.core.models import UserProfile
from flaza.ui.actions import UiActions

logger = logging.getLogger(__name__)

_SEX_LABEL = {"male": "男", "female": "女"}


class ProfileDialog:
    """展示资料卡，并提供名片点赞动作。"""

    def __init__(
        self,
        profile: UserProfile,
        actions: UiActions,
        *,
        on_like_result: Callable[[int], Awaitable[None]],
        on_error: Callable[[str], Awaitable[None]],
    ) -> None:
        self._profile = profile
        self._actions = actions
        self._on_like_result = on_like_result
        self._on_error = on_error
        self._liked = False
        self.dialog = Dialog(
            title="资料卡",
            content=self._build_content(),
            open=True,
            width="380px",
            actions=[
                DialogAction("点赞", on_click=self._on_like, close_on_click=False),
                DialogAction("关闭", variant="ghost"),
            ],
        )

    def _build_content(self):
        profile = self._profile
        rows = [
            VStack(
                Text(profile.display_name, weight="600", size="18px"),
                Text(profile.bio or "这个人很懒，什么都没有留下", role="secondary", size="12px"),
                gap="6px",
                align="stretch",
            ).build()
        ]
        if profile.uin:
            rows.append(_info_row("账号", str(profile.uin)))
        if profile.qid:
            rows.append(_info_row("QID", profile.qid))
        location = profile.location
        if location:
            rows.append(_info_row("地区", location))
        sex = _SEX_LABEL.get(profile.sex)
        if sex or profile.age:
            detail = " ".join(part for part in (sex, f"{profile.age} 岁" if profile.age else "") if part)
            rows.append(_info_row("资料", detail))
        content = VStack(*rows, gap="10px", align="stretch").build()
        return content

    async def _on_like(self, _dialog: Any = None) -> None:
        if self._liked:
            return
        try:
            added = await self._actions.like_friend(self._profile.uid)
        except Exception:
            logger.exception("点赞失败: uid=%s", self._profile.uid)
            await self._on_error("点赞失败")
            return
        self._liked = True
        await self._on_like_result(added)


def _info_row(label: str, value: str):
    return VStack(
        Text(label, role="secondary", size="12px"),
        Text(value, size="13px"),
        gap="2px",
        align="stretch",
    ).build()
