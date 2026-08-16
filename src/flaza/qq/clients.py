"""基于 lagrange-python 的 QQClient 实现。"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Sequence
from typing import Any, cast
from urllib.parse import quote, urlsplit, urlunsplit

from lagrange import Client
from lagrange.client.message.decoder import parse_friend_msg, parse_grp_msg
from lagrange.client.message.elems import Text
from lagrange.client.wtlogin.enum import QrCodeResult
from lagrange.info import InfoManager
from lagrange.info.app import AppInfo, app_list
from lagrange.pb.message.msg_push import MsgPushBody
from lagrange.pb.service.friend import GetFriendMsgRequest
from lagrange.pb.service.group import PBGetGrpLastSeq, PBGetGrpMsgRequest
from lagrange.utils.binary.protobuf import proto_decode
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
from flaza.qq.convert import friend_message_to_domain, group_message_to_domain

logger = logging.getLogger(__name__)

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
        nickname = sig.nickname
        if not nickname and client.uid:
            try:
                nickname = (await client.get_user_info(client.uid)).name
            except Exception:
                logger.debug("获取当前账号昵称失败，回退为 uin")
        return SelfInfo(
            uin=client.uin,
            uid=client.uid,
            nickname=nickname or str(client.uin),
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

    async def fetch_missing_messages(self, chat: ChatTarget, after_seq: int, limit: int = 500) -> list[Message]:
        """补拉指定会话在 after_seq 之后的消息，单会话最多拉取 limit 条。

        lagrange 自带的 get_friend_msg / get_grp_msg 对空历史和部分空响应
        使用 assert，因此这里直接发送相同协议包并宽容解析响应。
        """
        client = self._require_client()
        if isinstance(chat, FriendChat):
            latest = await client.get_friend_latest_seq(chat.uid)
            start = _sync_start(after_seq, latest, limit)
            if start is None:
                return []
            messages: list[Message] = []
            while start <= latest:
                end = min(start + 49, latest)
                raw_messages = await _fetch_friend_messages(client, chat.uid, start, end)
                messages.extend(friend_message_to_domain(raw, client.uin) for raw in raw_messages)
                start = end + 1
            return messages
        if isinstance(chat, GroupChat):
            latest = await _get_group_last_seq(client, chat.group_id)
            start = _sync_start(after_seq, latest, limit)
            if start is None:
                return []
            messages = []
            while start <= latest:
                end = min(start + 49, latest)
                raw_messages = await _fetch_group_messages(client, chat.group_id, start, end)
                messages.extend(group_message_to_domain(raw, client.uin) for raw in raw_messages)
                start = end + 1
            return messages
        raise TypeError(f"未知会话目标: {chat!r}")

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


_FRIEND_MSG_EMPTY_RETCODE = 100000301


async def _fetch_friend_messages(client: Client, uid: str, start: int, end: int) -> list[Any]:
    packet = await client.send_uni_packet(
        "trpc.msg.register_proxy.RegisterProxy.SsoGetC2cMsg",
        GetFriendMsgRequest(uid=uid, start=start, end=end).encode(),
    )
    raw = proto_decode(packet.data, max_layer=0).proto
    ret_code = raw.get(1)
    if isinstance(ret_code, int) and ret_code != 0:
        if ret_code == _FRIEND_MSG_EMPTY_RETCODE:
            return []
        raise RuntimeError(f"获取好友消息失败: ret_code={ret_code}")

    raw_messages = raw.get(7)
    if raw_messages is None:
        return []
    if isinstance(raw_messages, (bytes, bytearray)):
        raw_messages = [raw_messages]
    elif not isinstance(raw_messages, list):
        return []

    tasks = []
    for raw_message in raw_messages:
        try:
            parsed = MsgPushBody.decode(cast(bytes, raw_message))
        except Exception:
            continue
        tasks.append(parse_friend_msg(client, parsed))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [result for result in results if not isinstance(result, BaseException)]


async def _fetch_group_messages(client: Client, group_id: int, start: int, end: int) -> list[Any]:
    packet = await client.send_uni_packet(
        "trpc.msg.register_proxy.RegisterProxy.SsoGetGroupMsg",
        PBGetGrpMsgRequest.build(group_id, start, end).encode(),
    )
    raw = proto_decode(packet.data, max_layer=0).proto
    body_raw = raw.get(3)
    if not isinstance(body_raw, (bytes, bytearray)):
        return []
    body = proto_decode(bytes(body_raw), max_layer=0).proto

    raw_messages = body.get(6)
    if raw_messages is None:
        return []
    if isinstance(raw_messages, (bytes, bytearray)):
        raw_messages = [raw_messages]
    elif not isinstance(raw_messages, list):
        return []

    tasks = []
    for raw_message in raw_messages:
        try:
            parsed = MsgPushBody.decode(cast(bytes, raw_message))
        except Exception:
            continue
        tasks.append(parse_grp_msg(client, parsed))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [result for result in results if not isinstance(result, BaseException)]


async def _get_group_last_seq(client: Client, group_id: int) -> int:
    response = await client.send_oidb_svc(
        0x88D,
        0,
        PBGetGrpLastSeq.build(client.app_info.sub_app_id, group_id).encode(),
    )
    raw = proto_decode(response.data).proto
    body = raw.get(1)
    if not isinstance(body, dict):
        return 0
    args = body.get(3)
    if not isinstance(args, dict):
        return 0
    seq = args.get(22)
    return int(seq) if isinstance(seq, int) and seq > 0 else 0


def _sync_start(after_seq: int, latest_seq: int, limit: int) -> int | None:
    """计算补拉起点；没有缺口时返回 None。"""
    if limit <= 0 or latest_seq <= after_seq:
        return None
    if latest_seq - after_seq > limit:
        return latest_seq - limit + 1
    return after_seq + 1


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
