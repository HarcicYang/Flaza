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

    async def fetch_missing_messages(self, chat: ChatTarget, after_seq: int, limit: int = 500) -> list[Message]:
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
