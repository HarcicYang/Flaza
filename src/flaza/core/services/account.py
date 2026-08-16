"""账号服务：登录状态机。"""

from __future__ import annotations

import asyncio
import logging

from flaza.core.events import (
    ConnectionStateChanged,
    EventBus,
    LoginPhaseChanged,
    QrCodeReady,
    SelfInfoChanged,
)
from flaza.core.models import (
    ConnectionState,
    LoginPhase,
    QrCodeState,
    SilentLoginResult,
)
from flaza.core.ports import QQClient

logger = logging.getLogger(__name__)

_QR_POLL_INTERVAL_SECONDS = 2.0
_SILENT_LOGIN_TIMEOUT_SECONDS = 15.0


class AccountService:
    """驱动静默登录和二维码登录流程，并发布领域事件。"""

    def __init__(self, qq: QQClient, bus: EventBus) -> None:
        self._qq = qq
        self._bus = bus
        self._qr_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """启动账号服务：先尝试静默登录。"""
        self._bus.publish(ConnectionStateChanged(state=ConnectionState.CONNECTING))
        await self._set_phase(LoginPhase.SILENT_LOGGING_IN)

        try:
            result = await asyncio.wait_for(
                self._qq.try_silent_login(),
                timeout=_SILENT_LOGIN_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            logger.warning("静默登录超时（%s 秒），进入扫码登录流程", _SILENT_LOGIN_TIMEOUT_SECONDS)
            await self._set_phase(LoginPhase.FAILED, detail="静默登录超时，请扫码登录")
            return
        except Exception as exc:
            logger.exception("静默登录失败")
            await self._set_phase(LoginPhase.FAILED, detail=repr(exc))
            return

        if result is SilentLoginResult.OK:
            await self._on_online()
        elif result is SilentLoginResult.FAILED:
            await self._set_phase(LoginPhase.FAILED, detail="已有会话失效，请重新扫码登录")
        else:
            await self._set_phase(LoginPhase.IDLE, detail="等待扫码登录")

    async def start_qr_login(self) -> None:
        """获取二维码并在后台任务中轮询状态。"""
        await self.cancel_qr_login()
        qr = await self._qq.fetch_qrcode()
        self._bus.publish(QrCodeReady(qr=qr))
        self._qr_task = asyncio.create_task(self._poll_qrcode(), name="flaza-qr-login")

    async def cancel_qr_login(self) -> None:
        """取消当前二维码登录流程。"""
        if self._qr_task is not None:
            self._qr_task.cancel()
            await asyncio.gather(self._qr_task, return_exceptions=True)
            self._qr_task = None
        await self._qq.cancel_login()

    async def stop(self) -> None:
        """停止后台登录任务。"""
        await self.cancel_qr_login()

    async def _poll_qrcode(self) -> None:
        try:
            while True:
                await asyncio.sleep(_QR_POLL_INTERVAL_SECONDS)
                state = await self._qq.poll_qrcode()

                if state is QrCodeState.CONFIRMED:
                    await self._set_phase(LoginPhase.CONFIRMED)
                    await self._qq.complete_qrcode_login()
                    await self._on_online()
                    return
                if state in (QrCodeState.EXPIRED, QrCodeState.CANCELED):
                    await self._set_phase(LoginPhase.FAILED, detail=f"二维码{state.value}")
                    return
                await self._set_phase(self._qr_phase(state))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("二维码登录失败")
            await self._set_phase(LoginPhase.FAILED, detail=repr(exc))

    async def _on_online(self) -> None:
        info = await self._qq.get_self_info()
        self._bus.publish(SelfInfoChanged(info=info))
        self._bus.publish(ConnectionStateChanged(state=ConnectionState.ONLINE))
        await self._set_phase(LoginPhase.ONLINE)

    async def _set_phase(self, phase: LoginPhase, *, detail: str = "") -> None:
        self._bus.publish(LoginPhaseChanged(phase=phase, detail=detail))

    @staticmethod
    def _qr_phase(state: QrCodeState) -> LoginPhase:
        return {
            QrCodeState.WAITING_FOR_SCAN: LoginPhase.WAITING_SCAN,
            QrCodeState.WAITING_FOR_CONFIRM: LoginPhase.WAITING_CONFIRM,
            QrCodeState.CONFIRMED: LoginPhase.CONFIRMED,
            QrCodeState.EXPIRED: LoginPhase.FAILED,
            QrCodeState.CANCELED: LoginPhase.FAILED,
        }[state]
