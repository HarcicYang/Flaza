"""主窗口页面。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

from neony.application import icons
from neony.application.elements import Button, HStack, Progress, Spacer, Text, Toast
from neony.application.theme import stub
from neony.dom import Border, Color, Computed, Div, DOMElement, Signal, Styles
from neony.dom.reactive import effect

from flaza.config import AppConfig
from flaza.core.events import (
    EventBus,
    GroupReactionChanged,
)
from flaza.core.models import (
    ChatTarget,
    EmojiElement,
    FileElement,
    ForwardElement,
    GroupChat,
    GroupMemberRole,
    MarketFaceElement,
    Message,
    StoredMessage,
)
from flaza.plugins.registry import PluginExtensionRegistry
from flaza.ui.actions import UiActions
from flaza.ui.components.composer import Composer
from flaza.ui.components.forward_dialog import ForwardDialog
from flaza.ui.components.group_manage import GroupManageDialog
from flaza.ui.components.image_viewer import ImageViewer
from flaza.ui.components.message_list import MessageList
from flaza.ui.components.new_chat_dialog import NewChatDialog
from flaza.ui.components.profile_dialog import ProfileDialog
from flaza.ui.components.request_center import RequestCenterDialog
from flaza.ui.components.session_list import SessionList
from flaza.ui.state import UiStateStore

logger = logging.getLogger(__name__)

_BODY = Styles(display="flex", flex_grow="1", min_height="0", width="100%")

_RIGHT = Styles(display="flex", flex_direction="column", flex_grow="1", min_width="0", min_height="0")

_CHAT_HEADER = Styles(
    display="flex",
    align_items="center",
    gap="8px",
    padding="10px 16px",
    border_bottom="1px solid var(--color-border)",
    flex_shrink="0",
)

_DROP_HINT = Styles(
    position="fixed",
    top="0",
    left="0",
    width="100%",
    height="100%",
    z_index="1200",
    display="flex",
    align_items="center",
    justify_content="center",
    pointer_events="none",
    background_color=Color(rgba=(0, 0, 0, 0.30)),
)

_DROP_HINT_CARD = Styles(
    padding="18px 28px",
    border_radius="14px",
    background_color=stub.surface,
    border=Border(width="1px", color=stub.border_glass),
    color=stub.text_primary,
    font_size="15px",
    box_shadow="0 16px 48px var(--color-shadow)",
)

_LIST_WRAPPER = Styles(
    position="relative",
    display="flex",
    flex_direction="column",
    flex_grow="1",
    flex_basis="0",
    min_height="0",
)

_SYNC_FLOAT = Styles(
    display="flex",
    flex_direction="column",
    position="fixed",
    top="52px",
    left="50%",
    transform="translateX(-50%)",
    width="320px",
    z_index="1100",
    padding="12px 16px",
    border_radius="12px",
    background_color=stub.surface_glass_bg,
    backdrop_filter="blur(20px) saturate(1.2)",
    border=Border(width="1px", color=stub.border_glass),
    box_shadow="0 12px 40px var(--color-shadow)",
)


class HomePage:
    """登录成功后的主界面。"""

    def __init__(
        self,
        state: UiStateStore,
        actions: UiActions,
        bus: EventBus,
        config: AppConfig,
        render: Callable[[], Awaitable[None]],
        plugin_registry: PluginExtensionRegistry | None = None,
    ) -> None:
        self._state = state
        self._actions = actions
        self._config = config
        self._render = render
        self._new_chat: NewChatDialog | None = None
        self._new_chat_el: DOMElement | None = None
        self._request_center: RequestCenterDialog | None = None
        self._request_center_el: DOMElement | None = None
        self._profile_dialog: ProfileDialog | None = None
        self._profile_el: DOMElement | None = None
        self._group_manage_dialog: GroupManageDialog | None = None
        self._group_manage_el: DOMElement | None = None
        self._forward_dialog: ForwardDialog | None = None
        self._forward_el: DOMElement | None = None
        self._forward_picker: NewChatDialog | None = None
        self._forward_picker_el: DOMElement | None = None
        self._forward_messages: list[Message] = []
        self._state_refresh_task: asyncio.Task[None] | None = None
        self._state_refresh_again = False
        self._refresh_lock = asyncio.Lock()
        self._bus = bus
        self._plugin_registry = plugin_registry
        actions.set_chat_view_refresher(self._refresh_async)

        self.session_list = SessionList(state, actions, self._on_session_selected)
        self.image_viewer = ImageViewer(render)
        self.message_list = MessageList(
            state,
            on_image_click=self.image_viewer.open,
            on_message_action=self._on_message_action,
            on_reaction_selected=self._on_reaction_selected,
            on_load_older=self._on_load_older,
            on_file_download=self._on_file_download,
            on_forward_click=self._on_forward_click,
            on_card_click=self._on_card_click,
            plugin_registry=self._plugin_registry,
        )
        state.set_chat_prebuilder(self.message_list.prebuild_messages)
        self.toast = Toast(placement="top-right", duration=3.0, top_offset="40px")
        self.composer = Composer(actions, render, on_error=self._show_error, state=state)

        chat_title = Text("", size="16px", weight="600")
        chat_title.bind_text(state.active_chat_title)
        request_button = Button(
            Computed(lambda: _request_button_label(len(state.requests()))),
            variant="ghost",
            icon=icons.notifications,
        )
        request_button.on_click(self.open_request_center)
        manage_button = Button("群管理", variant="ghost", icon=icons.settings)
        manage_button.on_click(self.open_group_manage)
        manage_root = manage_button.build()
        manage_root.bind_visible(Computed(lambda: isinstance(state.active_chat(), GroupChat)))
        selection_text = Text("", role="secondary", size="12px")
        selection_text.bind_text(Computed(lambda: f"已选 {len(state.selected_messages())} 条"))
        forward_selected = Button("转发", variant="ghost")
        forward_selected.on_click(self._forward_selection)
        cancel_selection = Button("取消", variant="ghost")
        cancel_selection.on_click(self._cancel_selection)
        selection_bar = HStack(
            selection_text.build(),
            forward_selected.build(),
            cancel_selection.build(),
            gap="8px",
            align="center",
        ).build()
        selection_bar.bind_visible(Computed(lambda: bool(state.selected_messages())))
        chat_header = Div(
            styles=_CHAT_HEADER,
            container=[chat_title.build(), Spacer().build(), selection_bar, manage_root, request_button.build()],
        )

        sync_progress = Progress(indeterminate=True, label="正在同步离线消息…")
        sync_root = sync_progress.build()
        sync_root.styles = sync_root.styles.model_copy(
            update={key: getattr(_SYNC_FLOAT, key) for key in _SYNC_FLOAT.model_fields_set}
        )
        sync_root.bind_visible(state.sync_in_progress)

        self._dragging_files = Signal(False)
        drop_hint = Div(
            styles=_DROP_HINT,
            container=[Div(styles=_DROP_HINT_CARD, container=["松开以添加图片或文件"])],
        )
        drop_hint.bind_visible(self._dragging_files)

        list_wrapper = Div(
            styles=_LIST_WRAPPER,
            container=[self.message_list.root, self.message_list.jump_button],
        )
        right = Div(styles=_RIGHT, container=[chat_header, list_wrapper, self.composer.root])
        body = Div(styles=_BODY, container=[self.session_list.root, right])
        self.root = Div(
            styles=Styles(display="flex", flex_direction="column", width="100%", flex_grow="1", min_height="0"),
            container=[
                body,
                sync_root,
                self.image_viewer.root,
                self.toast.build(),
                drop_hint,
            ],
        )
        self.root.bubble_events = True
        self.root.on_dragover(self._on_dragover)
        self.root.on_dragleave(self._on_dragleave)
        self.root.on_drop(self._on_drop)

        self._apply_state()
        # 真实依赖 effect：这里读取 Signal，信号变化时自动调度增量刷新。
        effect(self._on_state_signal_changed)

    # ---- 数据刷新 ----

    def _apply_state(self) -> None:
        sessions = list(self._state.sessions())
        self.session_list.set_sessions(sessions)
        active = self._state.active_chat()
        self.message_list.set_messages(
            active,
            self._state.messages(),
            self._state.notices(),
            self._state.pending_messages(),
        )
        self.message_list.apply_selection()

    def _on_state_signal_changed(self) -> None:
        # 建立 Effect 依赖；真实变化会进入下面的合并调度。
        _ = (
            self._state.sessions(),
            self._state.active_chat(),
            self._state.messages(),
            self._state.pending_messages(),
            self._state.notices(),
            self._state.group_roles(),
            self._state.self_info(),
        )
        if self._state.state_refresh_suppressed:
            return
        self._schedule_state_refresh()

    def _schedule_state_refresh(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._state_refresh_task is None:
            task = loop.create_task(self._state_refresh_loop())
            self._state_refresh_task = task
            task.add_done_callback(self._state_refresh_done)
        else:
            self._state_refresh_again = True

    def _state_refresh_done(self, task: asyncio.Task[None]) -> None:
        self._state_refresh_task = None
        if self._state_refresh_again:
            self._state_refresh_again = False
            loop = asyncio.get_running_loop()
            new_task = loop.create_task(self._state_refresh_loop())
            self._state_refresh_task = new_task
            new_task.add_done_callback(self._state_refresh_done)

    async def _state_refresh_loop(self) -> None:
        async with self._refresh_lock:
            self._apply_state()
            await self._render()
        await self.message_list.scroll_to_bottom()

    async def _refresh_async(self, force_scroll: bool = True) -> None:
        async with self._refresh_lock:
            self._apply_state()
            await self._render()
        if force_scroll:
            await self.message_list.scroll_to_bottom(force=True)

    async def _on_load_older(self) -> None:
        try:
            await self._actions.load_older_messages()
        except Exception:
            logger.exception("加载更早消息失败")
            await self._show_error("加载更早消息失败")

    async def _on_message_action(self, value: str, stored: StoredMessage) -> None:
        try:
            if value == "copy":
                await self._actions.copy_text(stored.message.text)
            elif value == "forward":
                await self._open_forward_picker_for([stored.message])
            elif value == "select":
                self._state.toggle_message_selection(stored)
                self.message_list.apply_selection()
                await self._render()
            elif value == "send_face":
                element = next(
                    (item for item in stored.message.elements if isinstance(item, (EmojiElement, MarketFaceElement))),
                    None,
                )
                if element is not None:
                    await self._actions.send_element(stored.message.chat, element)
            elif value == "essence":
                chat = stored.message.chat
                rand = stored.message.rand
                if not isinstance(chat, GroupChat) or not rand:
                    return
                await self._actions.set_group_essence(chat.group_id, stored.message.seq, rand)
                self.toast.show("已设为精华消息", type="success")
                await self._render()
            elif value == "profile":
                await self.open_profile(stored.message.sender_uid, stored.message.sender_uin)
            elif value == "poke":
                await self._actions.send_nudge(stored.message.chat, stored.message.sender_uin)
            elif value == "recall":
                await self._actions.recall_message(stored.message.chat, stored.message.seq)
            elif value == "download":
                file = next((item for item in stored.message.elements if isinstance(item, FileElement)), None)
                if file is not None:
                    await self._on_file_download(file)
            elif value == "reply":
                self.composer.set_reply_to(stored)
                await self._render()
            elif value.startswith("plugin:"):
                _, plugin_id, action = value.split(":", 2)
                if self._plugin_registry is None:
                    raise RuntimeError("插件系统未启用")
                if not await self._plugin_registry.run_message_action(plugin_id, action, stored):
                    raise RuntimeError(f"插件动作不可用: {plugin_id}:{action}")
        except Exception:
            logger.exception(
                "消息菜单动作失败: action=%s chat=%s seq=%s",
                value,
                stored.message.chat.key,
                stored.message.seq,
            )
            await self._show_error("操作失败")

    async def _on_reaction_selected(self, stored: StoredMessage, emoji: str, emoji_type: int, is_cancel: bool) -> None:
        """发送/取消指定消息的表情回应。"""
        try:
            chat = stored.message.chat
            if isinstance(chat, GroupChat):
                self_info = self._state.self_info()
                await self._actions.send_reaction(
                    chat,
                    stored.message.seq,
                    emoji,
                    emoji_type=emoji_type,
                    is_cancel=is_cancel,
                )
                if self_info is not None and self_info.uid:
                    current = next(
                        (
                            reaction
                            for reaction in stored.message.reactions
                            if reaction.emoji_id == emoji and reaction.emoji_type == emoji_type
                        ),
                        None,
                    )
                    if is_cancel:
                        count = max(0, current.count - 1) if current is not None else 0
                    else:
                        count = (current.count + 1) if current is not None else 1
                    await self._state.update_group_reaction(
                        GroupReactionChanged(
                            group_id=chat.group_id,
                            seq=stored.message.seq,
                            emoji_id=emoji,
                            emoji_type=emoji_type,
                            count=count,
                            is_increase=not is_cancel,
                            operator_uid=self_info.uid,
                        )
                    )
        except Exception as exc:
            logger.exception("发送表情回应失败")
            await self._show_error(f"表情回应失败：{exc}")

    async def _on_dragover(self, _event: object) -> None:
        if self.image_viewer.is_open:
            return
        if not self._dragging_files():
            self._dragging_files.set(True)
            await self._render()

    async def _on_dragleave(self, _event: object) -> None:
        if self.image_viewer.is_open:
            return
        if self._dragging_files():
            self._dragging_files.set(False)
            await self._render()

    async def _on_drop(self, event: object) -> None:
        self._dragging_files.set(False)
        if self.image_viewer.is_open:
            return
        drop_files = getattr(event, "drop_files", None) or []
        paths = [str(file.get("path") or "") for file in drop_files if file.get("path")]
        if paths:
            await self._handle_dropped_paths(paths)
        await self._render()

    async def _handle_dropped_paths(self, paths: list[str]) -> None:
        images = [path for path in paths if self._actions.is_image_path(path)]
        files = [path for path in paths if not self._actions.is_image_path(path)]
        if images:
            self.composer.stage_images(images)
            await self._refresh_async(force_scroll=False)
        if files:
            try:
                await self._actions.send_files(files)
            except Exception:
                logger.exception("拖拽文件发送失败")
                await self._show_error("拖拽文件发送失败")

    async def _on_file_download(self, file: FileElement) -> None:
        try:
            destination = await self._actions.download_file(file)
            if destination:
                self.toast.show(f"已保存到 {destination}", type="success")
                await self._render()
        except Exception as exc:
            logger.exception("文件下载失败: name=%s", file.file_name)
            await self._show_error(f"下载失败：{exc}")

    async def _show_error(self, message: str) -> None:
        self.toast.show(message, type="error")
        await self._render()

    # ---- 标题栏动作入口 ----

    async def open_request_center(self, _event: object = None) -> None:
        """打开通知中心前先拉取服务端待处理申请。"""
        await self._actions.refresh_requests()
        await self._show_request_center()

    async def _show_request_center(self) -> None:
        self._detach_request_center()
        dialog = RequestCenterDialog(
            self._state,
            self._actions,
            on_changed=self._reload_request_center,
            on_error=self._show_error,
        )
        self._request_center = dialog
        self._request_center_el = dialog.dialog.build()
        self.root.container.append(self._request_center_el)
        await self._render()

    async def _reload_request_center(self) -> None:
        await self._show_request_center()

    def _detach_request_center(self) -> None:
        if self._request_center is not None:
            self._request_center.dialog.open = False
        if self._request_center_el is not None:
            with contextlib.suppress(ValueError):
                self.root.container.remove(self._request_center_el)
        self._request_center = None
        self._request_center_el = None

    async def open_profile(self, uid: str, uin: int) -> None:
        """拉取并展示资料卡。"""
        try:
            profile = await self._actions.fetch_user_profile(uid, uin)
        except Exception:
            logger.exception("获取资料卡失败: uid=%s uin=%s", uid, uin)
            await self._show_error("获取资料失败")
            return
        self._detach_profile()
        dialog = ProfileDialog(
            profile,
            self._actions,
            on_like_result=self._on_like_result,
            on_error=self._show_error,
        )
        self._profile_dialog = dialog
        self._profile_el = dialog.dialog.build()
        self.root.container.append(self._profile_el)
        await self._render()

    async def _on_like_result(self, added: int) -> None:
        self.toast.show("已点赞 +1" if added else "今天已经点过赞了", type="success")
        await self._render()

    def _detach_profile(self) -> None:
        if self._profile_dialog is not None:
            self._profile_dialog.dialog.open = False
        if self._profile_el is not None:
            with contextlib.suppress(ValueError):
                self.root.container.remove(self._profile_el)
        self._profile_dialog = None
        self._profile_el = None

    async def open_group_manage(self, _event: object = None) -> None:
        """打开当前群的群管理面板。"""
        chat = self._state.active_chat()
        if not isinstance(chat, GroupChat):
            return
        info = self._state.self_info()
        self_uid = info.uid if info else ""
        members = await self._actions.list_group_members(chat.group_id)
        role = next((member.role for member in members if member.uid == self_uid), GroupMemberRole.MEMBER)
        if role is GroupMemberRole.MEMBER:
            role = self._state.group_roles().get(f"{chat.group_id}:{self_uid}", role)
        name = next(
            (group.name for group in self._state.groups() if group.group_id == chat.group_id),
            str(chat.group_id),
        )
        self._detach_group_manage()
        dialog = GroupManageDialog(
            self._actions,
            group_id=chat.group_id,
            group_name=name,
            self_uid=self_uid,
            self_role=role,
            members=members,
            friends=list(self._state.friends()),
            on_message=self._on_manage_message,
            on_error=self._show_error,
            on_left=self._on_group_left,
        )
        self._group_manage_dialog = dialog
        self._group_manage_el = dialog.dialog.build()
        self.root.container.append(self._group_manage_el)
        await self._render()

    async def _on_manage_message(self, message: str) -> None:
        self.toast.show(message, type="success")
        await self._render()

    async def _on_group_left(self, group_id: int) -> None:
        self._detach_group_manage()
        self._state.groups.set(tuple(group for group in self._state.groups() if group.group_id != group_id))
        session_key = GroupChat(group_id=group_id).key
        self._state.sessions.set(
            tuple(session for session in self._state.sessions() if session.chat.key != session_key)
        )
        active = self._state.active_chat()
        if isinstance(active, GroupChat) and active.group_id == group_id:
            self._state.active_chat.set(None)
            self._state.active_chat_title.set("")
        self.toast.show("已退出群聊", type="success")
        await self._render()

    def _detach_group_manage(self) -> None:
        if self._group_manage_dialog is not None:
            self._group_manage_dialog.dialog.open = False
        if self._group_manage_el is not None:
            with contextlib.suppress(ValueError):
                self.root.container.remove(self._group_manage_el)
        self._group_manage_dialog = None
        self._group_manage_el = None

    async def _on_forward_click(self, element: ForwardElement) -> None:
        """展开合并转发卡片中的聊天记录。"""
        chat = self._state.active_chat()
        if chat is None or not element.resid:
            await self._show_error("无法展开该转发消息")
            return
        try:
            messages = await self._actions.fetch_forward_messages(chat, element.resid)
        except Exception:
            logger.exception("展开转发消息失败: resid=%s", element.resid)
            await self._show_error("展开转发消息失败")
            return
        self._detach_forward()
        dialog = ForwardDialog(messages)
        self._forward_dialog = dialog
        self._forward_el = dialog.dialog.build()
        self.root.container.append(self._forward_el)
        await self._render()

    async def _on_card_click(self, element: object) -> None:
        url = getattr(element, "url", "")
        if url:
            await self._actions.open_external(url)

    def _detach_forward(self) -> None:
        if self._forward_dialog is not None:
            self._forward_dialog.dialog.open = False
        if self._forward_el is not None:
            with contextlib.suppress(ValueError):
                self.root.container.remove(self._forward_el)
        self._forward_dialog = None
        self._forward_el = None

    async def _open_forward_picker_for(self, messages: list[Message]) -> None:
        """选择转发目标会话。"""
        if not messages:
            return
        self._detach_forward_picker()
        dialog = NewChatDialog(self._state, self._forward_to)
        self._forward_picker = dialog
        self._forward_picker_el = dialog.dialog.build()
        self._forward_messages = list(messages)
        self.root.container.append(self._forward_picker_el)
        await self._render()

    async def _forward_selection(self, _event: object = None) -> None:
        messages = [stored.message for stored in self._state.selected_messages()]
        await self._open_forward_picker_for(messages)

    async def _cancel_selection(self, _event: object = None) -> None:
        self._state.clear_message_selection()
        self.message_list.apply_selection()
        await self._render()

    async def _forward_to(self, target: ChatTarget) -> None:
        messages = self._forward_messages
        if not messages:
            return
        try:
            await self._actions.forward_messages(target, messages)
        except Exception:
            logger.exception("转发消息失败: chat=%s count=%s", target.key, len(messages))
            await self._show_error("转发失败")
            return
        self._detach_forward_picker()
        self._state.clear_message_selection()
        self.message_list.apply_selection()
        self.toast.show("已转发", type="success")
        await self._render()

    def _detach_forward_picker(self) -> None:
        if self._forward_picker is not None:
            self._forward_picker.dialog.open = False
        if self._forward_picker_el is not None:
            with contextlib.suppress(ValueError):
                self.root.container.remove(self._forward_picker_el)
        self._forward_picker = None
        self._forward_picker_el = None
        self._forward_messages = []

    async def open_new_chat(self) -> None:
        if self._new_chat_el is not None:
            with contextlib.suppress(ValueError):
                self.root.container.remove(self._new_chat_el)
        dialog = NewChatDialog(self._state, self._select_chat)
        self._new_chat = dialog
        self._new_chat_el = dialog.dialog.build()
        self.root.container.append(self._new_chat_el)
        await self._render()

    async def _select_chat(self, chat: ChatTarget) -> None:
        if self._new_chat is not None:
            self._new_chat.dialog.open = False
        await self._open_and_refresh(chat)

    async def _on_session_selected(self, chat: ChatTarget) -> None:
        await self._open_and_refresh(chat)

    async def _open_and_refresh(self, chat: ChatTarget) -> None:
        await self._actions.open_chat(chat)
        # 更新 Composer 的群成员上下文（用于 @ 提及）
        await self._update_composer_context(chat)
        if self._actions.current_config().window.chat_open_position == "last":
            await self.message_list.restore_scroll(chat.key)
        else:
            await self.message_list.scroll_to_bottom(force=True)

    async def _update_composer_context(self, chat: ChatTarget) -> None:
        """根据当前会话更新 Composer 的草稿与群成员上下文。"""
        self.composer.switch_chat(chat.key)
        if isinstance(chat, GroupChat):
            try:
                members = await self._actions.list_group_members(chat.group_id)
                self_info = self._state.self_info()
                # 判断当前用户是否是群主或管理员
                can_mention_all = False
                if self_info is not None:
                    my_role = self._state.group_roles().get(f"{chat.group_id}:{self_info.uid}")
                    can_mention_all = my_role in (GroupMemberRole.OWNER, GroupMemberRole.ADMIN)
                self.composer.set_group_context(chat.group_id, members, can_mention_all=can_mention_all)
            except Exception:
                logger.exception("加载群成员失败: group=%s", chat.group_id)
                self.composer.set_group_context(chat.group_id, [], can_mention_all=False)
        else:
            self.composer.set_group_context(None)


def _request_button_label(count: int) -> str:
    return f"通知 {count}" if count else "通知"
