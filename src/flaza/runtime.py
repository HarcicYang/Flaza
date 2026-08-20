"""应用运行时：对象组装、QQ 生命周期和事件接线。"""

from __future__ import annotations

import asyncio
import logging

from neony.application import DARK, DEEP_BLUE, LIGHT, NeonApplication, Theme

from flaza.config import AppConfig
from flaza.core.events import (
    EventBus,
    GroupAdminChanged,
    GroupMemberJoined,
    GroupMemberQuit,
    GroupNameChanged,
    LoginPhaseChanged,
    MessageRecalled,
    MessageReceived,
    Subscription,
)
from flaza.core.models import LoginPhase
from flaza.core.services import AccountService, ContactService, GroupEventService, MessageService
from flaza.core.services.media_cache import MediaCache
from flaza.core.storage import Storage
from flaza.qq.api import LagrangeQQClient
from flaza.ui.actions import UiActions
from flaza.ui.shell import ShellView
from flaza.ui.state import UiStateStore

logger = logging.getLogger(__name__)

THEME_MAP: dict[str, Theme] = {
    "dark": DARK,
    "light": LIGHT,
    "deep_blue": DEEP_BLUE,
}


class ApplicationRuntime:
    """持有应用对象图，并负责异步生命周期。"""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.storage = Storage()
        self.media_cache = MediaCache(config.paths.media_cache_dir)
        self.bus = EventBus()
        self.state = UiStateStore(self.storage)
        self.actions = UiActions(self)
        self.shell = ShellView(self.state, self.actions, self.bus, self.config, self.render)

        self._qq: LagrangeQQClient | None = None
        self._account_service: AccountService | None = None
        self._contact_service: ContactService | None = None
        self._group_event_service: GroupEventService | None = None
        self._message_service: MessageService | None = None
        self._background_tasks: set[asyncio.Task[None]] = set()
        self._service_subscriptions: list[Subscription] = []
        self._state_wired = False
        self._bus_task: asyncio.Task[None] | None = None
        self._neony_app: NeonApplication[UiStateStore] | None = None

    # ---- 属性 ----

    @property
    def account_service(self) -> AccountService | None:
        return self._account_service

    @property
    def contact_service(self) -> ContactService | None:
        return self._contact_service

    @property
    def message_service(self) -> MessageService | None:
        return self._message_service

    @property
    def group_event_service(self) -> GroupEventService | None:
        return self._group_event_service

    def attach_neony_app(self, app: NeonApplication[UiStateStore]) -> None:
        self._neony_app = app
        self.state.set_render(self.render)

    async def render(self) -> None:
        if self._neony_app is None:
            return
        await self._neony_app.render()

    async def eval_js(self, script: str) -> str:
        if self._neony_app is None:
            return ""
        return await self._neony_app.eval_js(script)

    async def open_files(
        self,
        *,
        title: str = "打开",
        default_dir: str | None = None,
        filetypes: list[tuple[str, str]] | None = None,
    ) -> list[str]:
        """打开系统原生多选文件对话框；未挂载应用时返回空列表。"""
        if self._neony_app is None:
            return []
        return await self._neony_app.open_files(title=title, default_dir=default_dir, filetypes=filetypes)

    async def save_file(
        self,
        *,
        title: str = "另存为",
        default_dir: str | None = None,
        default_name: str | None = None,
        filetypes: list[tuple[str, str]] | None = None,
    ) -> str | None:
        """打开系统原生保存文件对话框；未挂载应用时返回 None。"""
        if self._neony_app is None:
            return None
        return await self._neony_app.save_file(
            title=title,
            default_dir=default_dir,
            default_name=default_name,
            filetypes=filetypes,
        )

    async def clipboard_write(self, text: str) -> None:
        """写入系统剪贴板；未挂载应用时静默跳过。"""
        if self._neony_app is not None:
            await self._neony_app.clipboard_write(text)

    async def clipboard_read(self) -> bytes | str:
        """读取系统剪贴板；未挂载应用时返回空字符串。"""
        if self._neony_app is None:
            return ""
        return await self._neony_app.clipboard_read()

    async def set_theme(self, theme_name: str) -> None:
        """立即应用主题；应用尚未创建时静默跳过。"""
        if self._neony_app is None:
            return
        await self._neony_app.set_theme(THEME_MAP[theme_name])

    # ---- 生命周期 ----

    async def on_ready(self) -> None:
        await self.storage.init("flaza.db")
        await self.state.load_initial_state()
        self._bus_task = asyncio.create_task(self.bus.run(), name="flaza-event-bus")
        if self.config.login_configured:
            await self.start_qq()

    async def on_close(self) -> None:
        await self._cancel_background_tasks()
        await self.stop_qq()
        if self._bus_task is not None:
            self._bus_task.cancel()
            await asyncio.gather(self._bus_task, return_exceptions=True)
            self._bus_task = None
        await self.storage.close()

    async def start_qq(self) -> None:
        """创建协议实现与服务，并启动登录流程。"""
        if self._qq is not None:
            return

        qq = LagrangeQQClient(self.config.login, self.config.paths, self.bus, messages=self.storage.messages)
        account_service = AccountService(qq, self.bus)
        contact_service = ContactService(qq, self.storage, self.bus)
        group_event_service = GroupEventService(self.storage)
        message_service = MessageService(qq, self.storage, self.bus, self.media_cache)

        self._qq = qq
        self._account_service = account_service
        self._contact_service = contact_service
        self._group_event_service = group_event_service
        self._message_service = message_service

        self._service_subscriptions = [
            self.bus.subscribe(MessageReceived, message_service.on_message_received),
            self.bus.subscribe(MessageRecalled, message_service.on_message_recalled),
            self.bus.subscribe(GroupNameChanged, group_event_service.on_group_name_changed),
            self.bus.subscribe(GroupMemberJoined, group_event_service.on_group_member_joined),
            self.bus.subscribe(GroupMemberQuit, group_event_service.on_group_member_quit),
            self.bus.subscribe(GroupAdminChanged, group_event_service.on_group_admin_changed),
            self.bus.subscribe(LoginPhaseChanged, self._sync_contacts_on_online),
            self.bus.subscribe(LoginPhaseChanged, self._sync_messages_on_online),
        ]

        if not self._state_wired:
            self.state.wire(self.bus)
            self._state_wired = True

        try:
            await qq.start()
            await account_service.start()
        except Exception as exc:
            logger.exception("QQ 启动失败")
            self.bus.publish(LoginPhaseChanged(phase=LoginPhase.FAILED, detail=f"启动失败：{exc}"))

    async def stop_qq(self) -> None:
        for subscription in self._service_subscriptions:
            subscription.dispose()
        self._service_subscriptions.clear()

        if self._message_service is not None:
            await self._message_service.stop()
        if self._account_service is not None:
            await self._account_service.stop()
        if self._qq is not None:
            await self._qq.stop()

        self._account_service = None
        self._contact_service = None
        self._group_event_service = None
        self._message_service = None
        self._qq = None

    async def _sync_contacts_on_online(self, event: LoginPhaseChanged) -> None:
        if event.phase is not LoginPhase.ONLINE or self._contact_service is None:
            return
        await self._contact_service.sync()
        task = asyncio.create_task(self._contact_service.sync_group_members(), name="flaza-group-members")
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _cancel_background_tasks(self) -> None:
        for task in list(self._background_tasks):
            task.cancel()
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
        self._background_tasks.clear()

    async def _sync_messages_on_online(self, event: LoginPhaseChanged) -> None:
        if event.phase is not LoginPhase.ONLINE or self._message_service is None:
            return
        self.state.sync_in_progress.set(True)
        await self.render()
        try:
            await self._message_service.sync_offline_messages()
        finally:
            self.state.sync_in_progress.set(False)
            await self.render()
