"""基于 lagrange-python 的 QQClient 实现。"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from typing import Any, cast
from urllib.parse import quote, urlsplit, urlunsplit

from lagrange import Client
from lagrange.client.message.elems import Text
from lagrange.client.wtlogin.enum import QrCodeResult
from lagrange.info import InfoManager
from lagrange.info.app import AppInfo, app_list
from lagrange.utils.sign import sign_provider

from flaza.config import LoginConfig, PathsConfig
from flaza.core.events import EventBus
from flaza.core.models import (
    ChatTarget,
    Friend,
    FriendChat,
    Group,
    GroupChat,
    Message,
    MessageElement,
    QrCodeData,
    QrCodeState,
    SelfInfo,
    SilentLoginResult,
    TextElement,
)
from flaza.qq.adapter import LagrangeEventAdapter

_QR_STATE_MAP = {
    QrCodeResult.waiting_for_scan: QrCodeState.WAITING_FOR_SCAN,
    QrCodeResult.waiting_for_confirm: QrCodeState.WAITING_FOR_CONFIRM,
    QrCodeResult.confirmed: QrCodeState.CONFIRMED,
    QrCodeResult.expired: QrCodeState.EXPIRED,
    QrCodeResult.canceled: QrCodeState.CANCELED,
}


class LagrangeQQClient:
    """协议端口 QQClient 的 lagrange-python 实现。"""

    def __init__(self, login: LoginConfig, paths: PathsConfig, bus: EventBus) -> None:
        self._login = login
        self._paths = paths
        self._bus = bus
        self._client: Client | None = None
        self._info: InfoManager | None = None
        self._adapter = LagrangeEventAdapter(bus)

    # ---- 生命周期 ----

    async def start(self) -> None:
        """加载运行数据、创建客户端并启动网络任务。"""
        if self._client is not None:
            return

        app_info = self._load_app_info()
        info = InfoManager(self._login.uin, self._paths.device_info_path, self._paths.sign_info_path)
        info.__enter__()
        self._info = info

        sign = None
        signer_url = _build_signer_url(self._login.signer_url, self._login.signer_token)
        if signer_url:
            sign = sign_provider(signer_url, self._login.uin, info.device.guid, app_info.qua)

        client = Client(
            self._login.uin,
            app_info,
            info.device,
            info.sig_info,
            sign,
        )
        self._adapter.subscribe(client)
        client.connect()
        self._client = client

    async def stop(self) -> None:
        """停止客户端并保存设备/签名信息。"""
        if self._client is not None:
            await self._client.stop()
            self._client = None
        if self._info is not None:
            self._info.__exit__(None, None, None)
            self._info = None

    # ---- 登录 ----

    async def try_silent_login(self) -> SilentLoginResult:
        client = self._require_client()
        sig = self._require_info().sig_info

        if sig.temp_pwd:
            return SilentLoginResult.OK if await client.easy_login() else SilentLoginResult.FAILED
        if sig.d2:
            return SilentLoginResult.OK if await client.register() else SilentLoginResult.FAILED
        return SilentLoginResult.NO_SESSION

    async def fetch_qrcode(self) -> QrCodeData:
        result = await self._require_client().fetch_qrcode()
        if isinstance(result, int):
            raise RuntimeError(f"获取登录二维码失败: 错误码 {result}")
        image, url = result
        return QrCodeData(image=image, url=url)

    async def poll_qrcode(self) -> QrCodeState:
        result = await self._require_client().get_qrcode_result()
        try:
            return _QR_STATE_MAP[QrCodeResult(result)]
        except KeyError:
            raise RuntimeError(f"未知二维码状态: {result}") from None

    async def complete_qrcode_login(self) -> None:
        client = self._require_client()
        if not await client.qrcode_login(refresh_interval=0):
            raise RuntimeError("二维码最终登录失败")
        if not await client.register():
            raise RuntimeError("客户端注册失败")

    async def cancel_login(self) -> None:
        """取消登录流程。

        lagrange 没有取消二维码的协议接口；真正的取消动作由上层停止轮询
        任务实现，这里保留端口语义以便未来协议支持。
        """

    # ---- 在线能力 ----

    async def get_self_info(self) -> SelfInfo:
        client = self._require_client()
        sig = self._require_info().sig_info
        return SelfInfo(
            uin=client.uin,
            uid=client.uid,
            nickname=sig.nickname or str(client.uin),
        )

    async def fetch_friends(self) -> list[Friend]:
        raw_friends = await self._require_client().get_friend_list()
        return [
            Friend(
                uin=raw.uin,
                uid=raw.uid or "",
                nickname=raw.nickname or "",
                remark=raw.remark,
            )
            for raw in raw_friends
        ]

    async def fetch_groups(self) -> list[Group]:
        response = await self._require_client().get_grp_list()
        return [
            Group(
                group_id=raw.grp_id,
                name=raw.info.grp_name,
                member_count=raw.info.now_members,
            )
            for raw in response.grp_list
        ]

    async def send_message(self, target: ChatTarget, elements: Sequence[MessageElement]) -> Message:
        client = self._require_client()
        chain = [self._to_lagrange_element(element) for element in elements]

        if isinstance(target, FriendChat):
            seq = await client.send_friend_msg(uid=target.uid, msg_chain=chain)
        elif isinstance(target, GroupChat):
            seq = await client.send_grp_msg(grp_id=target.group_id, msg_chain=chain)
        else:
            raise TypeError(f"未知会话目标: {target!r}")

        self_info = await self.get_self_info()
        return Message(
            chat=target,
            sender_uin=self_info.uin,
            sender_uid=self_info.uid,
            sender_name=self_info.nickname,
            seq=seq,
            timestamp=int(time.time()),
            elements=list(elements),
            from_self=True,
        )

    # ---- 内部方法 ----

    def _load_app_info(self) -> AppInfo:
        if self._login.use_custom:
            with open(self._login.appinfo_path, encoding="utf-8") as file:
                return AppInfo.load_custom(json.load(file))
        return cast(AppInfo, cast(Any, app_list)[self._login.protocol])

    def _require_client(self) -> Client:
        if self._client is None:
            raise RuntimeError("LagrangeQQClient 尚未 start")
        return self._client

    def _require_info(self) -> InfoManager:
        if self._info is None:
            raise RuntimeError("InfoManager 尚未初始化")
        return self._info

    @staticmethod
    def _to_lagrange_element(element: MessageElement) -> Any:
        if isinstance(element, TextElement):
            return Text(text=element.text)
        raise TypeError(f"暂不支持的发送元素: {type(element).__name__}")


def _build_signer_url(base_url: str, token: str) -> str | None:
    """把配置中的签名服务地址构造成 lagrange 需要的完整 URL。"""
    if not base_url:
        return None
    endpoint = (
        base_url if base_url.rstrip("/").endswith("/api/sign/sec-sign") else f"{base_url.rstrip('/')}/api/sign/sec-sign"
    )
    if not token:
        return endpoint

    parts = urlsplit(endpoint)
    netloc = f"{quote(token, safe='')}@{parts.netloc}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
