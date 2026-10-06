"""群管理对话框：群资料、全员禁言与成员管理。"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from neony.application.elements import (
    Badge,
    Button,
    Checkbox,
    Dialog,
    DialogAction,
    HStack,
    Input,
    Spacer,
    Switch,
    Text,
    VStack,
)
from neony.application.theme import stub
from neony.dom import Color, Div, DOMElement, Styles

from flaza.core.models import Friend, GroupMember, GroupMemberRole
from flaza.ui.actions import UiActions

logger = logging.getLogger(__name__)

_MUTE_SECONDS = 10 * 60
_ROLE_BADGE: dict[GroupMemberRole, tuple[str, Literal["danger", "accent"]]] = {
    GroupMemberRole.OWNER: ("群主", "danger"),
    GroupMemberRole.ADMIN: ("管理员", "accent"),
}

_MEMBER_LIST = Styles(
    display="flex",
    flex_direction="column",
    gap="2px",
    max_height="220px",
    overflow_y="auto",
    overflow_x="hidden",
    border="1px solid var(--color-border)",
    border_radius="8px",
    padding="4px",
)
_MEMBER_ROW = Styles(
    display="flex",
    align_items="center",
    gap="8px",
    padding="7px 10px",
    border_radius="6px",
    cursor="pointer",
    background_color=Color(name="transparent"),
)
_MEMBER_ROW_ACTIVE = _MEMBER_ROW.model_copy(update={"background_color": stub.surface_raised})
_INPUT_WRAP = Styles(flex_grow="1", flex_basis="0", min_width="0")
_BUTTON_SLOT = Styles(flex_grow="1", flex_basis="0", min_width="0")
_INVITE_LIST = Styles(
    display="flex",
    flex_direction="column",
    gap="4px",
    max_height="160px",
    overflow_y="auto",
    overflow_x="hidden",
    border="1px solid var(--color-border)",
    border_radius="8px",
    padding="6px 8px",
)


class GroupManageDialog:
    """群资料与成员管理面板。"""

    def __init__(
        self,
        actions: UiActions,
        *,
        group_id: int,
        group_name: str,
        self_uid: str,
        self_role: GroupMemberRole,
        members: list[GroupMember],
        friends: list[Friend] | None = None,
        on_message: Callable[[str], Awaitable[None]],
        on_error: Callable[[str], Awaitable[None]],
        on_left: Callable[[int], Awaitable[None]],
    ) -> None:
        self._actions = actions
        self._group_id = group_id
        self._self_uid = self_uid
        self._self_role = self_role
        self._members = sorted(members, key=_member_sort_key)
        self._friends = friends or []
        self._on_message = on_message
        self._on_error = on_error
        self._on_left = on_left
        self._selected: GroupMember | None = None
        self._rows: dict[str, Div] = {}
        self._can_manage = self_role in (GroupMemberRole.OWNER, GroupMemberRole.ADMIN)

        self._name_input = Input(value=group_name)
        self._mute_switch = Switch("全员禁言", checked=False, disabled=not self._can_manage)
        self._mute_switch.on_change(self._on_mute_all_change)
        self._selected_label = Text("未选择成员", role="secondary", size="12px")

        self._mute_button = Button("禁言 10 分钟", variant="ghost", disabled=True)
        self._mute_button.on_click(self._on_mute_member)
        self._unmute_button = Button("解除禁言", variant="ghost", disabled=True)
        self._unmute_button.on_click(self._on_unmute_member)
        self._admin_button = Button("管理员", variant="ghost", disabled=True)
        self._admin_button.on_click(self._on_toggle_admin)
        self._kick_button = Button("移出群聊", variant="danger", disabled=True)
        self._kick_button.on_click(self._on_kick_member)
        self._title_button = Button("保存头衔", variant="ghost", disabled=True)
        self._title_button.on_click(self._on_save_title)
        self._card_button = Button("保存名片", variant="ghost", disabled=True)
        self._card_button.on_click(self._on_save_card)

        self._title_input = Input(placeholder="专属头衔")
        self._title_input.disabled = not self._can_manage
        self._card_input = Input(placeholder="群名片")
        self._leave_button = Button("退出群聊", variant="danger")
        self._leave_button.on_click(self._on_leave)
        self._invite_button = Button("邀请选中好友")
        self._invite_button.on_click(self._on_invite)
        self._friend_checks: dict[str, tuple[Checkbox, Friend]] = {}

        self._content = self._build_content()
        self.dialog = Dialog(
            title=f"群管理 · {group_name}",
            content=self._content,
            open=True,
            width="620px",
            actions=[DialogAction("关闭", variant="ghost")],
        )

    # ---- 构建 ----

    def _build_content(self):
        rows: list[Any] = []
        if self._can_manage:
            rows.append(Text("群资料", size="13px", weight="600"))
            rows.append(_input_row(self._name_input, _button("保存群名", self._on_rename_group)))
            rows.append(self._mute_switch.build())
            rows.append(Text("邀请好友", size="13px", weight="600"))
            rows.append(self._build_invite_list())
            rows.append(_row_end(self._invite_button))
        rows.append(Text("成员管理", size="13px", weight="600"))
        rows.append(self._selected_label.build())
        rows.append(self._build_member_list())
        if self._can_manage:
            rows.append(_button_pair(self._mute_button, self._unmute_button))
            rows.append(_button_pair(self._admin_button, self._kick_button))
            rows.append(_input_row(self._title_input, self._title_button))
            rows.append(_input_row(self._card_input, self._card_button))
        else:
            rows.append(_input_row(self._card_input, self._card_button))
        rows.append(_row_end(self._leave_button))
        content = VStack(*rows, gap="10px", align="stretch").build()
        content.styles = content.styles.model_copy(
            update={"max_height": "70vh", "overflow_y": "auto", "padding_right": "6px"}
        )
        # 让每行保持自然高度；否则 flex 收缩会压扁按钮并造成文字互相覆盖。
        for child in content.container:
            if isinstance(child, DOMElement):
                child.styles = child.styles.model_copy(update={"flex_shrink": "0"})
        return content

    def _build_invite_list(self) -> Div:
        children: list[Any] = []
        for friend in self._friends:
            checkbox = Checkbox(friend.display_name)
            self._friend_checks[friend.uid] = (checkbox, friend)
            children.append(checkbox.build())
        if not children:
            children.append(Text("暂无好友可邀请", role="secondary", size="12px").build())
        return Div(styles=_INVITE_LIST, container=children)

    def _build_member_list(self) -> Div:
        children: list[Any] = []
        for member in self._members:
            row = Div(styles=_MEMBER_ROW, container=_member_row_children(member, self._self_uid))
            row.bubble_events = True
            row.on_click(self._make_select_handler(member, row))
            self._rows[member.uid] = row
            children.append(row)
        if not children:
            children.append(
                Div(styles=_MEMBER_ROW, container=[Text("暂无成员缓存", role="secondary", size="12px").build()])
            )
        return Div(styles=_MEMBER_LIST, container=children)

    # ---- 选择与动作状态 ----

    def _make_select_handler(self, member: GroupMember, row: Div):
        async def handler(_event: Any = None) -> None:
            self._select(member, row)

        return handler

    def _select(self, member: GroupMember, row: Div) -> None:
        for key, item in self._rows.items():
            item.styles = _MEMBER_ROW_ACTIVE if key == member.uid else _MEMBER_ROW
        self._selected = member
        self._selected_label.text = f"已选择：{member.nickname or member.uin or member.uid}"
        self._card_input.value = member.nickname
        self._refresh_actions()

    def _refresh_actions(self) -> None:
        member = self._selected
        can_manage = self._can_manage
        is_owner = self._self_role is GroupMemberRole.OWNER
        target_is_owner = member is not None and member.role is GroupMemberRole.OWNER
        target_is_self = member is not None and member.uid == self._self_uid
        manageable = can_manage and member is not None and not target_is_owner
        member_uin = member.uin if member is not None else 0

        self._mute_button.disabled = not (manageable and bool(member_uin))
        self._unmute_button.disabled = not (manageable and bool(member_uin))
        if member is not None:
            self._admin_button.label = "取消管理员" if member.role is GroupMemberRole.ADMIN else "设为管理员"
        self._admin_button.disabled = not (
            is_owner and member is not None and bool(member.uid) and not target_is_owner and not target_is_self
        )
        can_kick = manageable and not target_is_self
        if member is not None and member.role is GroupMemberRole.ADMIN and not is_owner:
            can_kick = False
        self._kick_button.disabled = not (can_kick and bool(member_uin))
        self._title_button.disabled = not (is_owner and member is not None and bool(member.uid))
        self._card_button.disabled = not (member is not None and bool(member.uid) and (can_manage or target_is_self))

    # ---- 动作 ----

    async def _on_rename_group(self, _event: Any = None) -> None:
        name = self._name_input.value.strip()
        if not name:
            await self._on_error("群名称不能为空")
            return
        if not await self._run(self._actions.rename_group(self._group_id, name), "修改群名失败"):
            return
        self.dialog.title = name
        await self._on_message("群名已修改")

    async def _on_mute_all_change(self, checked: bool) -> None:
        ok = await self._run(self._actions.set_group_mute(self._group_id, checked), "设置全员禁言失败")
        if not ok:
            self._mute_switch.checked = not checked
            return
        await self._on_message("已开启全员禁言" if checked else "已解除全员禁言")

    async def _on_mute_member(self, _event: Any = None) -> None:
        member = self._require_selected()
        if member is None or not member.uin:
            return
        if await self._run(self._actions.mute_group_member(self._group_id, member.uin, _MUTE_SECONDS), "禁言失败"):
            await self._on_message("已禁言 10 分钟")

    async def _on_unmute_member(self, _event: Any = None) -> None:
        member = self._require_selected()
        if member is None or not member.uin:
            return
        if await self._run(self._actions.mute_group_member(self._group_id, member.uin, 0), "解除禁言失败"):
            await self._on_message("已解除禁言")

    async def _on_toggle_admin(self, _event: Any = None) -> None:
        member = self._require_selected()
        if member is None or not member.uid:
            return
        is_set = member.role is not GroupMemberRole.ADMIN
        if await self._run(self._actions.set_group_admin(self._group_id, member.uid, is_set), "设置管理员失败"):
            await self._on_message("已取消管理员" if not is_set else "已设为管理员")

    async def _on_kick_member(self, _event: Any = None) -> None:
        member = self._require_selected()
        if member is None or not member.uin:
            return
        if await self._run(self._actions.kick_group_member(self._group_id, member.uin), "移出成员失败"):
            await self._on_message("已把成员移出群聊")

    async def _on_save_title(self, _event: Any = None) -> None:
        member = self._require_selected()
        if member is None or not member.uid:
            return
        title = self._title_input.value.strip()
        if await self._run(self._actions.set_group_special_title(self._group_id, member.uid, title), "设置头衔失败"):
            await self._on_message("已保存专属头衔")

    async def _on_save_card(self, _event: Any = None) -> None:
        member = self._require_selected()
        if member is None or not member.uid:
            return
        name = self._card_input.value.strip()
        if await self._run(self._actions.rename_group_member(self._group_id, member.uid, name), "修改群名片失败"):
            await self._on_message("已修改群名片")

    async def _on_leave(self, _event: Any = None) -> None:
        if await self._run(self._actions.leave_group(self._group_id), "退出群聊失败"):
            self.dialog.open = False
            await self._on_left(self._group_id)

    async def _on_invite(self, _event: Any = None) -> None:
        selected = {
            friend.uid: friend.uin
            for checkbox, friend in self._friend_checks.values()
            if checkbox.checked and friend.uid
        }
        if not selected:
            await self._on_error("请先选择要邀请的好友")
            return
        if await self._run(self._actions.invite_group_members(self._group_id, selected), "邀请好友失败"):
            await self._on_message(f"已邀请 {len(selected)} 位好友")

    def _require_selected(self) -> GroupMember | None:
        if self._selected is None:
            return None
        return self._selected

    async def _run(self, awaitable: Awaitable[Any], error_text: str) -> bool:
        try:
            await awaitable
        except Exception:
            logger.exception("群管理动作失败: group=%s", self._group_id)
            await self._on_error(error_text)
            return False
        return True


def _button(label: str, handler: Callable[..., Awaitable[None]]) -> Button:
    button = Button(label)
    button.on_click(handler)
    return button


def _input_row(input_: Input, button: Button) -> DOMElement:
    """输入框占据剩余宽度，按钮保持自然宽度并禁止换行。"""
    button_el = button.build()
    button_el.styles = button_el.styles.model_copy(update={"flex_shrink": "0", "white_space": "nowrap"})
    row = HStack(
        Div(styles=_INPUT_WRAP, container=[input_.build()]),
        button_el,
        gap="8px",
        align="center",
    ).build()
    row.styles = row.styles.model_copy(update={"flex_shrink": "0"})
    return row


def _button_pair(left: Button, right: Button) -> DOMElement:
    """两个等宽按钮并排，避免四个按钮在一行里被压扁。"""
    slots = []
    for button in (left, right):
        button_el = button.build()
        button_el.styles = button_el.styles.model_copy(
            update={"width": "100%", "white_space": "nowrap", "flex_shrink": "0"}
        )
        slots.append(Div(styles=_BUTTON_SLOT, container=[button_el]))
    row = HStack(*slots, gap="8px").build()
    row.styles = row.styles.model_copy(update={"flex_shrink": "0"})
    return row


def _row_end(button: Button) -> DOMElement:
    button_el = button.build()
    button_el.styles = button_el.styles.model_copy(update={"flex_shrink": "0", "white_space": "nowrap"})
    row = HStack(Spacer().build(), button_el, gap="8px", justify="flex-end").build()
    row.styles = row.styles.model_copy(update={"flex_shrink": "0"})
    return row


def _member_row_children(member: GroupMember, self_uid: str):
    name = member.nickname or str(member.uin or member.uid)
    if member.uid == self_uid:
        name = f"{name}（我）"
    children: list[Any] = [Text(name, size="13px").build(), Spacer().build()]
    badge = _ROLE_BADGE.get(member.role)
    if badge is not None:
        label, variant = badge
        children.append(Badge(label, variant=variant).build())
    return children


def _member_sort_key(member: GroupMember) -> tuple[int, str]:
    rank = {
        GroupMemberRole.OWNER: 0,
        GroupMemberRole.ADMIN: 1,
        GroupMemberRole.MEMBER: 2,
    }.get(member.role, 3)
    return rank, member.nickname or str(member.uin)
