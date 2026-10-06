"""账号服务登录状态机测试。"""

import asyncio
from collections.abc import Sequence
from typing import override

import pytest

from flaza.core.events import EventBus, LoginPhaseChanged, SelfInfoChanged
from flaza.core.models import (
    ChatTarget,
    Friend,
    Group,
    GroupMember,
    LoginPhase,
    Message,
    MessageElement,
    PendingRequest,
    QrCodeData,
    QrCodeState,
    SelfInfo,
    SilentLoginResult,
)
from flaza.core.services import AccountService
from flaza.core.services import account as account_module


class FakeQQ:
    """仅用于账号服务测试的协议假实现。"""

    def __init__(self, silent_result: SilentLoginResult) -> None:
        self.silent_result = silent_result

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def try_silent_login(self) -> SilentLoginResult:
        return self.silent_result

    async def fetch_qrcode(self) -> QrCodeData:
        raise NotImplementedError

    async def poll_qrcode(self) -> QrCodeState:
        raise NotImplementedError

    async def complete_qrcode_login(self) -> None:
        raise NotImplementedError

    async def cancel_login(self) -> None: ...

    async def get_self_info(self) -> SelfInfo:
        return SelfInfo(uin=10001, uid="u_1", nickname="测试账号")

    async def fetch_friends(self) -> list[Friend]:
        raise NotImplementedError

    async def fetch_groups(self) -> list[Group]:
        raise NotImplementedError

    async def fetch_group_members(self, group_id: int) -> list[GroupMember]:
        raise NotImplementedError

    async def fetch_group_member(self, group_id: int, uid: str) -> GroupMember | None:
        raise NotImplementedError

    async def send_message(self, target: ChatTarget, elements: Sequence[MessageElement]) -> Message:
        raise NotImplementedError

    async def send_file(self, target: ChatTarget, path: str, filename: str | None = None) -> Message:
        raise NotImplementedError

    async def recall_message(self, target: ChatTarget, seq: int) -> None:
        raise NotImplementedError

    async def send_reaction(
        self, chat: ChatTarget, seq: int, emoji_id: str, emoji_type: int = 2, is_cancel: bool = False
    ) -> None:
        raise NotImplementedError

    async def send_nudge(self, target: ChatTarget, uin: int) -> None:
        raise NotImplementedError

    async def respond_friend_request(self, uid: str, accept: bool) -> None:
        raise NotImplementedError

    async def fetch_group_requests(self) -> list[PendingRequest]:
        raise NotImplementedError

    async def respond_group_request(self, group_id: int, seq: int, event_type: int, accept: bool) -> None:
        raise NotImplementedError

    async def fetch_user_profile(self, uid: str = "", uin: int = 0):
        raise NotImplementedError

    async def like_friend(self, uid: str) -> int:
        raise NotImplementedError

    async def set_self_nickname(self, nickname: str) -> None:
        raise NotImplementedError

    async def set_self_bio(self, bio: str) -> None:
        raise NotImplementedError

    async def set_self_avatar(self, path: str) -> None:
        raise NotImplementedError

    async def rename_group(self, group_id: int, name: str) -> None:
        raise NotImplementedError

    async def rename_group_member(self, group_id: int, uid: str, name: str) -> None:
        raise NotImplementedError

    async def kick_group_member(self, group_id: int, uin: int) -> None:
        raise NotImplementedError

    async def set_group_admin(self, group_id: int, uid: str, is_set: bool) -> None:
        raise NotImplementedError

    async def set_group_special_title(self, group_id: int, uid: str, title: str) -> None:
        raise NotImplementedError

    async def set_group_mute(self, group_id: int, enable: bool) -> None:
        raise NotImplementedError

    async def mute_group_member(self, group_id: int, uin: int, duration: int) -> None:
        raise NotImplementedError

    async def leave_group(self, group_id: int) -> None:
        raise NotImplementedError

    async def invite_group_members(self, group_id: int, uids: list[str] | dict[str, int]) -> None:
        raise NotImplementedError

    async def set_group_essence(self, group_id: int, seq: int, rand: int, is_remove: bool = False) -> None:
        raise NotImplementedError

    async def fetch_forward_messages(self, chat: ChatTarget, resid: str) -> list[Message]:
        raise NotImplementedError

    async def forward_messages(self, target: ChatTarget, messages: list[Message]) -> None:
        raise NotImplementedError

    async def fetch_missing_messages(self, chat: ChatTarget, after_seq: int, limit: int = 500) -> list[Message]:
        raise NotImplementedError

    async def fetch_message(self, chat: ChatTarget, seq: int) -> Message | None:
        raise NotImplementedError


def _run_account_scenario(silent_result: SilentLoginResult) -> tuple[list[LoginPhase], SelfInfo | None]:
    async def scenario() -> tuple[list[LoginPhase], SelfInfo | None]:
        bus = EventBus()
        qq = FakeQQ(silent_result)
        service = AccountService(qq, bus)

        phases: list[LoginPhase] = []
        done = asyncio.Event()
        info_box: list[SelfInfo] = []

        async def on_phase(event: LoginPhaseChanged) -> None:
            phases.append(event.phase)
            if event.phase is LoginPhase.IDLE:
                done.set()

        async def on_info(event: SelfInfoChanged) -> None:
            info_box.append(event.info)
            done.set()

        bus.subscribe(LoginPhaseChanged, on_phase)
        bus.subscribe(SelfInfoChanged, on_info)
        task = asyncio.create_task(bus.run())

        await service.start()
        await asyncio.wait_for(done.wait(), timeout=1)

        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return phases, info_box[0] if info_box else None

    return asyncio.run(scenario())


def test_silent_login_success() -> None:
    phases, info = _run_account_scenario(SilentLoginResult.OK)
    assert phases == [LoginPhase.SILENT_LOGGING_IN, LoginPhase.ONLINE]
    assert info is not None
    assert info.uin == 10001


def test_silent_login_without_session() -> None:
    phases, info = _run_account_scenario(SilentLoginResult.NO_SESSION)
    assert phases == [LoginPhase.SILENT_LOGGING_IN, LoginPhase.IDLE]
    assert info is None


class SlowQQ(FakeQQ):
    @override
    async def try_silent_login(self) -> SilentLoginResult:
        await asyncio.sleep(1)
        return SilentLoginResult.OK


def test_silent_login_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(account_module, "_SILENT_LOGIN_TIMEOUT_SECONDS", 0.05)

    async def scenario() -> None:
        bus = EventBus()
        service = AccountService(SlowQQ(SilentLoginResult.OK), bus)
        phases: list[LoginPhase] = []
        done = asyncio.Event()

        async def on_phase(event: LoginPhaseChanged) -> None:
            phases.append(event.phase)
            if event.phase is LoginPhase.FAILED:
                done.set()

        bus.subscribe(LoginPhaseChanged, on_phase)
        task = asyncio.create_task(bus.run())
        await service.start()
        await asyncio.wait_for(done.wait(), timeout=1)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert phases == [LoginPhase.SILENT_LOGGING_IN, LoginPhase.FAILED]

    asyncio.run(scenario())
