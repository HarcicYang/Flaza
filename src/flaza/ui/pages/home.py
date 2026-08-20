"""主窗口页面。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

from neony.application.elements import Progress, Text, Toast
from neony.application.theme import stub
from neony.dom import Border, Color, Div, DOMElement, Signal, Styles
from neony.dom.reactive import effect

from flaza.config import AppConfig
from flaza.core.events import (
    EventBus,
)
from flaza.core.models import ChatTarget, FileElement, GroupChat, GroupMemberRole, StoredMessage
from flaza.ui.actions import UiActions
from flaza.ui.components.composer import Composer
from flaza.ui.components.image_viewer import ImageViewer
from flaza.ui.components.message_list import MessageList
from flaza.ui.components.new_chat_dialog import NewChatDialog
from flaza.ui.components.session_list import SessionList
from flaza.ui.components.settings_dialog import SettingsDialog
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

_SYNC_FLOAT = Styles(
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
    ) -> None:
        self._state = state
        self._actions = actions
        self._config = config
        self._render = render
        self._settings_el: DOMElement | None = None
        self._new_chat: NewChatDialog | None = None
        self._new_chat_el: DOMElement | None = None
        self._state_refresh_task: asyncio.Task[None] | None = None
        self._state_refresh_again = False
        self._refresh_lock = asyncio.Lock()
        self._bus = bus
        actions.set_chat_view_refresher(self._refresh_async)

        self.session_list = SessionList(state, actions, self._on_session_selected)
        self.image_viewer = ImageViewer(render, eval_js=actions._runtime.eval_js)
        self.message_list = MessageList(
            state,
            on_image_click=self.image_viewer.open,
            on_message_action=self._on_message_action,
            on_reaction_selected=self._on_reaction_selected,
            on_load_older=self._on_load_older,
            on_file_download=self._on_file_download,
        )
        self.toast = Toast(placement="top-right", duration=3.0, top_offset="40px")
        self.composer = Composer(actions, render, on_error=self._show_error)

        chat_title = Text("", size="16px", weight="600")
        chat_title.bind_text(state.active_chat_title)
        chat_header = Div(styles=_CHAT_HEADER, container=[chat_title.build()])

        sync_progress = Progress(indeterminate=True, label="正在同步离线消息…")
        sync_root = sync_progress.build()
        sync_float = Div(styles=_SYNC_FLOAT, container=[sync_root])
        sync_float.bind_visible(state.sync_in_progress)

        self._dragging_files = Signal(False)
        drop_hint = Div(
            styles=_DROP_HINT,
            container=[Div(styles=_DROP_HINT_CARD, container=["松开以添加图片或文件"])],
        )
        drop_hint.bind_visible(self._dragging_files)

        right = Div(
            styles=_RIGHT,
            container=[chat_header, self.message_list.root, self.composer.root],
        )
        body = Div(styles=_BODY, container=[self.session_list.root, right])
        self.root = Div(
            styles=Styles(display="flex", flex_direction="column", width="100%", flex_grow="1", min_height="0"),
            container=[
                body,
                sync_float,
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
        self.message_list.set_messages(active, self._state.messages(), self._state.notices())

    def _on_state_signal_changed(self) -> None:
        # 建立 Effect 依赖；真实变化会进入下面的合并调度。
        _ = (
            self._state.sessions(),
            self._state.active_chat(),
            self._state.messages(),
            self._state.notices(),
            self._state.group_roles(),
            self._state.self_info(),
        )
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
            elif value == "recall":
                await self._actions.recall_message(stored.message.chat, stored.message.seq)
            elif value == "download":
                file = next((item for item in stored.message.elements if isinstance(item, FileElement)), None)
                if file is not None:
                    await self._on_file_download(file)
            elif value == "reply":
                self.composer.set_reply_to(stored)
                await self._render()
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
            qq = self._actions._runtime._qq
            if qq is not None and isinstance(chat, GroupChat):
                await qq.send_reaction(chat, stored.message.seq, emoji, emoji_type=emoji_type, is_cancel=is_cancel)
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

    async def open_new_chat(self) -> None:
        if self._new_chat_el is not None:
            with contextlib.suppress(ValueError):
                self.root.container.remove(self._new_chat_el)
        dialog = NewChatDialog(self._state, self._select_chat)
        self._new_chat = dialog
        self._new_chat_el = dialog.dialog.build()
        self.root.container.append(self._new_chat_el)
        await self._render()

    async def open_settings(self) -> None:
        if self._settings_el is not None:
            with contextlib.suppress(ValueError):
                self.root.container.remove(self._settings_el)
        config = self._actions.current_config()
        dialog = SettingsDialog(self._actions, config.login, config.window)
        self._settings_el = dialog.dialog.build()
        self.root.container.append(self._settings_el)
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

    async def _update_composer_context(self, chat: ChatTarget) -> None:
        """根据当前会话更新 Composer 的群成员上下文。"""
        if isinstance(chat, GroupChat):
            try:
                members = await self._actions._runtime.storage.members.list_by_group(chat.group_id)
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
