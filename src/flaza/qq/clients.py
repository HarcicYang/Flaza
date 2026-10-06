"""基于 hiro-qq 的 QQClient 实现。"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote, urlsplit, urlunsplit

from lagrange import Client
from lagrange.client.message.decoder import parse_friend_msg, parse_grp_msg
from lagrange.client.message.elems import (
    At,
    AtAll,
    Emoji,
    ForwardNode,
    MarketFace,
    MulitMsg,
    Quote,
    Text,
)
from lagrange.client.wtlogin.enum import QrCodeResult
from lagrange.info import InfoManager
from lagrange.info.app import AppInfo, app_list
from lagrange.info.sig import SigInfo
from lagrange.pb.message.msg_push import MsgPushBody
from lagrange.pb.service.friend import GetFriendMsgRequest
from lagrange.pb.service.group import PBGetGrpLastSeq, PBGetGrpMsgRequest
from lagrange.utils.binary.protobuf import proto_decode
from lagrange.utils.sign import sign_provider

from flaza.config import LoginConfig, PathsConfig
from flaza.core.events import EventBus
from flaza.core.models import (
    AtAllElement,
    AtElement,
    AudioElement,
    ChatTarget,
    EmojiElement,
    Friend,
    FriendChat,
    Group,
    GroupChat,
    GroupMember,
    GroupMemberRole,
    ImageElement,
    MarketFaceElement,
    Message,
    MessageElement,
    PendingRequest,
    PluginElement,
    QrCodeData,
    QrCodeState,
    QuoteElement,
    RequestKind,
    SelfInfo,
    SilentLoginResult,
    TextElement,
    UserProfile,
    VideoElement,
)
from flaza.plugins.registry import PluginExtensionRegistry
from flaza.qq.adapter import LagrangeEventAdapter
from flaza.qq.convert import (
    friend_message_to_domain,
    group_message_to_domain,
    lagrange_audio_to_domain,
    lagrange_elements_to_domain,
    lagrange_file_to_domain,
    lagrange_image_to_domain,
    lagrange_video_to_domain,
)
from flaza.qq.custom_sign import SignFactory, load_sign_provider

logger = logging.getLogger(__name__)

_MESSAGE_PAGE_SIZE = 50
_MESSAGE_FETCH_CONCURRENCY = 6

_QR_STATE_MAP = {
    QrCodeResult.waiting_for_scan: QrCodeState.WAITING_FOR_SCAN,
    QrCodeResult.waiting_for_confirm: QrCodeState.WAITING_FOR_CONFIRM,
    QrCodeResult.confirmed: QrCodeState.CONFIRMED,
    QrCodeResult.expired: QrCodeState.EXPIRED,
    QrCodeResult.canceled: QrCodeState.CANCELED,
}


class LagrangeQQClient:
    """协议端口 QQClient 的 hiro-qq 实现。"""

    def __init__(
        self,
        login: LoginConfig,
        paths: PathsConfig,
        bus: EventBus,
        messages: Any = None,
        plugin_registry: PluginExtensionRegistry | None = None,
    ) -> None:
        self._login = login
        self._paths = paths
        self._bus = bus
        self._plugin_registry = plugin_registry
        self._client: Client | None = None
        self._info: InfoManager | None = None
        self._adapter = LagrangeEventAdapter(bus, messages=messages)

    # ---- 生命周期 ----

    async def start(self) -> None:
        """加载运行数据、创建客户端并启动网络任务。"""
        if self._client is not None:
            return

        app_info = self._load_app_info()
        _seed_login_info(self._paths, self._login.uin)
        info = InfoManager(self._login.uin, self._paths.device_info_path, self._paths.sign_info_path)
        info.__enter__()
        self._info = info

        sign = _build_sign(self._login, info, app_info)

        client = Client(
            self._login.uin,
            app_info,
            info.device,
            info.sig_info,
            sign,
            use_ipv6=self._login.use_ipv6,
            use_optimum=self._login.use_optimum,
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
                owner_uid=raw.info.owner.uid if raw.info.owner is not None else None,
            )
            for raw in response.grp_list
        ]

    async def fetch_group_members(self, group_id: int) -> list[GroupMember]:
        """分页拉取群成员身份。"""
        client = self._require_client()
        response = await client.get_grp_members(group_id)
        members = _member_bodies_to_domain(group_id, response.body)
        next_key = response.next_key
        while next_key:
            response = await client.get_grp_members(group_id, next_key.decode())
            members.extend(_member_bodies_to_domain(group_id, response.body))
            next_key = response.next_key
        return members

    async def fetch_group_member(self, group_id: int, uid: str) -> GroupMember | None:
        """查询指定群成员的即时身份。"""
        response = await self._require_client().get_grp_member_info(group_id, uid)
        members = _member_bodies_to_domain(group_id, response.body)
        return members[0] if members else None

    async def send_message(self, target: ChatTarget, elements: Sequence[MessageElement]) -> Message:
        client = self._require_client()
        chain: list[Any] = []
        outgoing: list[MessageElement] = []
        for element in elements:
            lagrange_element, domain_element = await self._prepare_outgoing_element(target, element)
            chain.append(lagrange_element)
            outgoing.append(domain_element)

        logger.info("准备发送消息: chat=%s element_count=%s", target.key, len(chain))
        if isinstance(target, FriendChat):
            seq = await client.send_friend_msg(uid=target.uid, msg_chain=chain)
        elif isinstance(target, GroupChat):
            seq = await client.send_grp_msg(grp_id=target.group_id, msg_chain=chain)
        else:
            raise TypeError(f"未知会话目标: {target!r}")

        logger.info(
            "消息发送完成: chat=%s seq=%s elements=%s",
            target.key,
            seq,
            [type(element).__name__ for element in outgoing],
        )
        self_info = await self.get_self_info()
        return Message(
            chat=target,
            sender_uin=self_info.uin,
            sender_uid=self_info.uid,
            sender_name=self_info.nickname,
            seq=seq,
            timestamp=int(time.time()),
            elements=outgoing,
            from_self=True,
        )

    async def send_file(self, target: ChatTarget, path: str, filename: str | None = None) -> Message:
        """发送本地文件。

        好友文件上传即发送；群文件通过文件服务发送。两者都不会返回协议
        seq，因此发送前记录会话最新 seq，发送后轮询等待会话 seq 前进，
        再把文件元素与最新 seq 组装为领域消息。
        """
        client = self._require_client()
        file_path = Path(path)
        if not file_path.is_file():
            raise FileNotFoundError(path)
        file_name = filename or file_path.name

        if isinstance(target, FriendChat):
            before_seq = await client.get_friend_latest_seq(target.uid)
            with file_path.open("rb") as file:
                lagrange_file = await client.upload_friend_file(file, target.uid, file_name)
            seq = await self._poll_friend_latest_seq(client, target.uid, before_seq)
            file_url = await self._fetch_friend_file_url(client, target.uid, lagrange_file)
        elif isinstance(target, GroupChat):
            before_seq = await _get_group_last_seq(client, target.group_id)
            with file_path.open("rb") as file:
                lagrange_file = await client.upload_grp_file(file, target.group_id, "/", file_name)
            seq = await self._poll_group_last_seq(client, target.group_id, before_seq)
            file_url = await self._fetch_group_file_url(client, target.group_id, lagrange_file)
        else:
            raise TypeError(f"未知会话目标: {target!r}")

        element = lagrange_file_to_domain(lagrange_file)
        if file_url:
            element = element.model_copy(update={"file_url": file_url})
        self_info = await self.get_self_info()
        return Message(
            chat=target,
            sender_uin=self_info.uin,
            sender_uid=self_info.uid,
            sender_name=self_info.nickname,
            seq=seq,
            timestamp=int(time.time()),
            elements=[element],
            from_self=True,
        )

    async def send_reaction(
        self, chat: ChatTarget, seq: int, emoji_id: str, emoji_type: int = 2, is_cancel: bool = False
    ) -> None:
        """对消息发送表情回应；仅群聊支持，好友暂不支持。"""
        client = self._require_client()
        if isinstance(chat, GroupChat):
            if emoji_type == 1:
                await client.send_grp_reaction(chat.group_id, seq, int(emoji_id), is_cancel=is_cancel)
            else:
                await client.send_grp_reaction(chat.group_id, seq, emoji_id, is_cancel=is_cancel)
        elif isinstance(chat, FriendChat):
            raise NotImplementedError("好友消息暂不支持表情回应")
        else:
            raise TypeError(f"未知会话目标: {chat!r}")

    async def recall_message(self, target: ChatTarget, seq: int) -> None:
        """撤回自己发送的消息。"""
        client = self._require_client()
        if isinstance(target, FriendChat):
            await client.recall_friend_msg(target.uid, seq)
        elif isinstance(target, GroupChat):
            await client.recall_grp_msg(target.group_id, seq)
        else:
            raise TypeError(f"未知会话目标: {target!r}")

    async def send_nudge(self, target: ChatTarget, uin: int) -> None:
        """向好友或群成员发送戳一戳。"""
        client = self._require_client()
        if not uin:
            raise ValueError("戳一戳缺少目标 uin")
        if isinstance(target, FriendChat):
            await client.send_nudge(uin)
        elif isinstance(target, GroupChat):
            await client.send_nudge(uin, target.group_id)
        else:
            raise TypeError(f"未知会话目标: {target!r}")

    async def respond_friend_request(self, uid: str, accept: bool) -> None:
        """同意或拒绝一条好友申请。"""
        await self._require_client().set_friend_request(uid, accept)

    async def fetch_group_requests(self) -> list[PendingRequest]:
        """拉取待处理的入群申请与群邀请，保留处理所需的 seq/event_type。"""
        response = await self._require_client().fetch_grp_request(20)
        requests: list[PendingRequest] = []
        for raw in response.requests:
            group_id = int(getattr(raw.group, "grp_id", 0) or 0)
            group_name = str(getattr(raw.group, "grp_name", "") or "")
            target_uid = str(getattr(raw.target, "uid", "") or "")
            target_name = str(getattr(raw.target, "name", "") or "")
            invitor = getattr(raw, "invitor", None)
            invitor_name = str(getattr(invitor, "name", "") or "") if invitor is not None else ""
            event_type = int(getattr(raw, "event_type", 0) or 0)
            if event_type == 2:
                kind = RequestKind.GROUP_INVITE
                title = f"{invitor_name or '有人'}邀请你加入“{group_name or group_id}”"
                key = f"group-invite:{group_id}"
            else:
                kind = RequestKind.GROUP_JOIN
                title = f"{target_name or target_uid} 申请加入“{group_name or group_id}”"
                key = f"group-join:{group_id}:{target_uid}"
            requests.append(
                PendingRequest(
                    key=key,
                    kind=kind,
                    title=title,
                    subtitle=str(getattr(raw, "comment", "") or ""),
                    target_uid=target_uid,
                    group_id=group_id,
                    group_name=group_name,
                    seq=int(getattr(raw, "seq", 0) or 0),
                    event_type=event_type,
                    timestamp=int(time.time()),
                )
            )
        return requests

    async def respond_group_request(self, group_id: int, seq: int, event_type: int, accept: bool) -> None:
        """同意或拒绝一条入群申请/群邀请；hiro-qq 约定 action 1/2 为同意/拒绝。"""
        await self._require_client().set_grp_request(group_id, seq, event_type, 1 if accept else 2)

    async def fetch_user_profile(self, uid: str = "", uin: int = 0) -> UserProfile:
        """拉取好友或群成员资料卡。"""
        client = self._require_client()
        key: str | int = uid or uin
        if not key:
            raise ValueError("资料卡缺少 uid/uin")
        info = await client.get_user_info(key)
        location = " ".join(part for part in (info.country, info.province, info.city) if part)
        return UserProfile(
            uid=uid,
            uin=uin,
            nickname=info.name,
            bio=info.personal_sign,
            sex=getattr(info.sex, "name", "unknown"),
            age=info.age,
            location=location,
            qid=info.qid,
        )

    async def like_friend(self, uid: str) -> int:
        """给好友名片点赞，返回本次新增的赞数。"""
        if not uid:
            raise ValueError("点赞缺少目标 uid")
        response = await self._require_client().friend_like(uid, 1)
        return int(getattr(response, "added", 0) or 0)

    async def set_self_nickname(self, nickname: str) -> None:
        """修改当前账号昵称。"""
        if not nickname.strip():
            raise ValueError("昵称不能为空")
        await self._require_client().set_nickname(nickname.strip())

    async def set_self_bio(self, bio: str) -> None:
        """修改当前账号个性签名。"""
        await self._require_client().set_bio(bio.strip())

    async def set_self_avatar(self, path: str) -> None:
        """上传并修改当前账号头像。"""
        client = self._require_client()
        with open(path, "rb") as image:
            await client.set_avatar(image)

    # ---- 群管理 ----

    async def rename_group(self, group_id: int, name: str) -> None:
        """修改群名称。"""
        if not name.strip():
            raise ValueError("群名称不能为空")
        await self._require_client().rename_grp_name(group_id, name.strip())

    async def rename_group_member(self, group_id: int, uid: str, name: str) -> None:
        """修改指定成员的群名片。"""
        await self._require_client().rename_grp_member(group_id, uid, name.strip())

    async def kick_group_member(self, group_id: int, uin: int) -> None:
        """把成员移出群聊。"""
        if not uin:
            raise ValueError("移出成员缺少 uin")
        await self._require_client().kick_grp_member(group_id, uin)

    async def set_group_admin(self, group_id: int, uid: str, is_set: bool) -> None:
        """设置或取消群管理员。"""
        await self._require_client().set_grp_admin(group_id, uid, is_set)

    async def set_group_special_title(self, group_id: int, uid: str, title: str) -> None:
        """设置群成员专属头衔。"""
        await self._require_client().set_grp_special_title(group_id, uid, title.strip())

    async def set_group_mute(self, group_id: int, enable: bool) -> None:
        """开启或解除全员禁言。"""
        await self._require_client().set_mute_grp(group_id, enable)

    async def mute_group_member(self, group_id: int, uin: int, duration: int) -> None:
        """禁言指定成员。"""
        if not uin:
            raise ValueError("禁言缺少目标 uin")
        await self._require_client().set_mute_member(group_id, uin, max(0, duration))

    async def leave_group(self, group_id: int) -> None:
        """退出群聊。"""
        await self._require_client().leave_grp(group_id)

    async def invite_group_members(self, group_id: int, uids: list[str] | dict[str, int]) -> None:
        """邀请好友加入群聊。"""
        if not uids:
            return
        await self._require_client().invite_grp_member(group_id, uids)

    async def set_group_essence(self, group_id: int, seq: int, rand: int, is_remove: bool = False) -> None:
        """设置或取消群精华消息。"""
        if not seq or not rand:
            raise ValueError("精华消息缺少 seq/rand")
        await self._require_client().set_essence(group_id, seq, rand, is_remove=is_remove)

    async def fetch_forward_messages(self, chat: ChatTarget, resid: str) -> list[Message]:
        """拉取合并转发卡片中的消息内容。"""
        if not resid:
            raise ValueError("转发消息缺少 resid")
        forward = await self._require_client().get_forward_msg(resid, is_group=isinstance(chat, GroupChat))
        messages: list[Message] = []
        for node in forward.messages:
            messages.append(
                Message(
                    chat=chat,
                    sender_uin=node.sender_uin,
                    sender_uid="",
                    sender_name=node.sender_nick or str(node.sender_uin),
                    seq=0,
                    rand=0,
                    timestamp=node.timestamp,
                    elements=lagrange_elements_to_domain(list(node.content)),
                )
            )
        return messages

    async def fetch_message(self, chat: ChatTarget, seq: int) -> Message | None:
        """按 seq 重新拉取单条消息，解码器补丁会优先使用现代图片元素。"""
        if seq <= 0:
            return None
        client = self._require_client()
        if isinstance(chat, FriendChat):
            raw = await _fetch_friend_messages(client, chat.uid, seq, seq)
            messages = [friend_message_to_domain(item, client.uin) for item in raw]
        elif isinstance(chat, GroupChat):
            raw = await _fetch_group_messages(client, chat.group_id, seq, seq)
            messages = [group_message_to_domain(item, client.uin) for item in raw]
        else:
            raise TypeError(f"未知会话目标: {chat!r}")
        return next((message for message in messages if message.seq == seq), None)

    async def forward_messages(self, target: ChatTarget, messages: list[Message]) -> None:
        """把消息作为合并转发卡片发送到目标会话。"""
        if not messages:
            raise ValueError("没有可转发的消息")
        nodes: list[ForwardNode] = []
        for message in messages:
            nodes.append(
                ForwardNode(
                    content=await self._build_forward_content(target, message),
                    sender_uin=message.sender_uin,
                    sender_nick=message.sender_name or str(message.sender_uin),
                    timestamp=message.timestamp,
                )
            )
        forward = MulitMsg(messages=nodes)
        client = self._require_client()
        if isinstance(target, GroupChat):
            await client.send_grp_forward_msg(forward, target.group_id)
        elif isinstance(target, FriendChat):
            await client.send_friend_forward_msg(forward, target.uid)
        else:
            raise TypeError(f"未知会话目标: {target!r}")

    async def _build_forward_content(self, target: ChatTarget, message: Message) -> list[Any]:
        """把领域消息转换为转发节点内容；媒体尽力保留，未知类型降级为文字占位。"""
        content: list[Any] = []
        for element in message.elements:
            if isinstance(element, TextElement):
                content.append(Text(text=element.text))
            elif isinstance(element, AtElement):
                content.append(At(uin=element.uin, uid=element.uid, text=element.text))
            elif isinstance(element, AtAllElement):
                content.append(AtAll(text=element.text))
            elif isinstance(element, ImageElement) and (element.cached_path or element.local_path):
                content.append(await self._upload_image(target, element.cached_path or element.local_path))
            else:
                content.append(Text(text=str(getattr(element, "preview_text", "[消息]"))))
        if not content:
            content.append(Text(text="[空消息]"))
        return content

    async def fetch_missing_messages(self, chat: ChatTarget, after_seq: int, limit: int = 500) -> list[Message]:
        """补拉指定会话在 after_seq 之后的消息，单会话最多拉取 limit 条。

        lagrange 自带的 get_friend_msg / get_grp_msg 对空历史和部分空响应
        使用 assert，因此这里直接发送相同协议包并宽容解析响应。
        分页之间用有界并发拉取，最后按 seq 顺序合并，缩短长历史的等待时间。
        """
        client = self._require_client()
        if isinstance(chat, FriendChat):
            latest = await client.get_friend_latest_seq(chat.uid)
            start = _sync_start(after_seq, latest, limit)
            if start is None:
                return []

            async def fetch_page(page_start: int, page_end: int) -> list[Message]:
                raw_messages = await _fetch_friend_messages(client, chat.uid, page_start, page_end)
                return [friend_message_to_domain(raw, client.uin) for raw in raw_messages]

            return await _fetch_message_pages(chat.key, _page_ranges(start, latest), fetch_page)
        if isinstance(chat, GroupChat):
            latest = await _get_group_last_seq(client, chat.group_id)
            start = _sync_start(after_seq, latest, limit)
            if start is None:
                return []

            async def fetch_group_page(page_start: int, page_end: int) -> list[Message]:
                raw_messages = await _fetch_group_messages(client, chat.group_id, page_start, page_end)
                return [group_message_to_domain(raw, client.uin) for raw in raw_messages]

            return await _fetch_message_pages(chat.key, _page_ranges(start, latest), fetch_group_page)
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

    async def _prepare_outgoing_element(
        self,
        target: ChatTarget,
        element: MessageElement,
    ) -> tuple[Any, MessageElement]:
        """把领域元素转换为 lagrange 元素，并返回持久化用的领域元素。"""
        if isinstance(element, TextElement):
            return Text(text=element.text), element
        if isinstance(element, AtElement):
            return At(uin=element.uin, uid=element.uid, text=element.text), element
        if isinstance(element, AtAllElement):
            return AtAll(text=element.text), element
        if isinstance(element, QuoteElement):
            return (
                Quote(seq=element.seq, uin=element.uin, timestamp=element.timestamp, uid=element.uid, msg=element.msg),
                element,
            )
        if isinstance(element, PluginElement):
            if self._plugin_registry is None:
                raise RuntimeError("插件消息段发送器未注册")
            return await self._plugin_registry.convert_plugin_element(target, element)
        if isinstance(element, EmojiElement):
            return Emoji(id=element.id), element
        if isinstance(element, MarketFaceElement):
            return (
                MarketFace(
                    name=element.name,
                    face_id=element.face_id,
                    tab_id=element.tab_id,
                    width=element.width,
                    height=element.height,
                ),
                element,
            )
        if isinstance(element, ImageElement) and element.local_path:
            uploaded = await self._upload_image(target, element.local_path)
            if isinstance(target, GroupChat) and getattr(uploaded, "id", 0) == 0:
                raise RuntimeError("群图片上传后未返回 fileid，无法发送")
            logger.info("图片上传完成: chat=%s name=%s", target.key, uploaded.name)
            domain = lagrange_image_to_domain(uploaded)
            # 自己发送的图片暂时没有媒体缓存，先复用本地原图路径渲染，
            # 后续收到协议回包/媒体缓存后再替换为缓存路径。
            return uploaded, domain.model_copy(update={"cached_path": element.local_path})
        if isinstance(element, AudioElement) and element.local_path:
            uploaded = await self._upload_audio(target, element.local_path)
            logger.info("语音上传完成: chat=%s name=%s", target.key, uploaded.name)
            domain = lagrange_audio_to_domain(uploaded)
            return uploaded, domain.model_copy(update={"cached_path": element.local_path})
        if isinstance(element, VideoElement) and element.local_path:
            uploaded = await self._upload_video(target, element.local_path)
            logger.info("视频上传完成: chat=%s name=%s", target.key, uploaded.name)
            domain = lagrange_video_to_domain(uploaded)
            return uploaded, domain.model_copy(update={"cached_path": element.local_path})
        raise TypeError(f"暂不支持的发送元素: {type(element).__name__}")

    async def _upload_image(self, target: ChatTarget, path: str) -> Any:
        """把本地图片上传到对应会话并返回 lagrange Image。"""
        client = self._require_client()
        with open(path, "rb") as image:
            if isinstance(target, FriendChat):
                return await client.upload_friend_image(image, target.uid)
            if isinstance(target, GroupChat):
                return await client.upload_grp_image(image, target.group_id)
        raise TypeError(f"未知会话目标: {target!r}")

    async def _upload_video(self, target: ChatTarget, path: str) -> Any:
        """把本地视频上传到对应会话并返回 lagrange Video。"""
        client = self._require_client()
        with open(path, "rb") as video:
            if isinstance(target, FriendChat):
                return await client.upload_friend_video(video, target.uid)
            if isinstance(target, GroupChat):
                return await client.upload_grp_video(video, target.group_id)
        raise TypeError(f"未知会话目标: {target!r}")

    async def _upload_audio(self, target: ChatTarget, path: str) -> Any:
        """把本地语音上传到对应会话并返回 lagrange Audio。"""
        client = self._require_client()
        with open(path, "rb") as audio:
            if isinstance(target, FriendChat):
                return await client.upload_friend_audio(audio, target.uid)
            if isinstance(target, GroupChat):
                return await client.upload_grp_audio(audio, target.group_id)
        raise TypeError(f"未知会话目标: {target!r}")

    async def _poll_friend_latest_seq(self, client: Client, uid: str, before_seq: int, timeout: float = 5.0) -> int:
        """等待好友会话最新 seq 前进，返回新的最新 seq。"""
        deadline = time.monotonic() + timeout
        while True:
            latest = await client.get_friend_latest_seq(uid)
            if latest > before_seq:
                return latest
            if time.monotonic() >= deadline:
                raise TimeoutError(f"等待好友文件消息 seq 超时: uid={uid} before={before_seq}")
            await asyncio.sleep(0.2)

    async def _poll_group_last_seq(self, client: Client, group_id: int, before_seq: int, timeout: float = 5.0) -> int:
        """等待群会话最新 seq 前进，返回新的最新 seq。"""
        deadline = time.monotonic() + timeout
        while True:
            latest = await _get_group_last_seq(client, group_id)
            if latest > before_seq:
                return latest
            if time.monotonic() >= deadline:
                raise TimeoutError(f"等待群文件消息 seq 超时: group={group_id} before={before_seq}")
            await asyncio.sleep(0.2)

    async def _fetch_friend_file_url(self, client: Client, uid: str, lagrange_file: Any) -> str | None:
        try:
            if lagrange_file.file_uuid and lagrange_file.file_hash:
                return await client.fetch_friend_file_url(lagrange_file.file_uuid, lagrange_file.file_hash, uid)
        except Exception:
            logger.debug("获取好友文件下载链接失败: uid=%s", uid, exc_info=True)
        return None

    async def _fetch_group_file_url(self, client: Client, group_id: int, lagrange_file: Any) -> str | None:
        try:
            if lagrange_file.file_id:
                return await client.fetch_grp_file_url(group_id, lagrange_file.file_id)
        except Exception:
            logger.debug("获取群文件下载链接失败: group=%s", group_id, exc_info=True)
        return None


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


def _member_bodies_to_domain(group_id: int, bodies: list[Any]) -> list[GroupMember]:
    members: list[GroupMember] = []
    for body in bodies:
        role = GroupMemberRole.MEMBER
        if body.is_owner:
            role = GroupMemberRole.OWNER
        elif body.is_admin:
            role = GroupMemberRole.ADMIN
        account = body.account
        if account is None:
            continue
        members.append(
            GroupMember(
                group_id=group_id,
                uid=account.uid,
                uin=account.uin or 0,
                nickname=body.nickname,
                role=role,
            )
        )
    return members


def _sync_start(after_seq: int, latest_seq: int, limit: int) -> int | None:
    """计算补拉起点；没有缺口时返回 None。"""
    if limit <= 0 or latest_seq <= after_seq:
        return None
    if latest_seq - after_seq > limit:
        return latest_seq - limit + 1
    return after_seq + 1


def _page_ranges(start: int, latest: int, page_size: int = _MESSAGE_PAGE_SIZE) -> list[tuple[int, int]]:
    """把补拉区间切分成协议分页。"""
    return [(page_start, min(page_start + page_size - 1, latest)) for page_start in range(start, latest + 1, page_size)]


async def _fetch_message_pages[PageItem](
    chat_key: str,
    ranges: Sequence[tuple[int, int]],
    fetch_page: Callable[[int, int], Awaitable[list[PageItem]]],
) -> list[PageItem]:
    """有界并发拉取分页，按分页顺序合并；单页失败不影响其他页。"""
    if not ranges:
        return []
    semaphore = asyncio.Semaphore(_MESSAGE_FETCH_CONCURRENCY)

    async def run(page_range: tuple[int, int]) -> list[PageItem]:
        async with semaphore:
            return await fetch_page(*page_range)

    results = await asyncio.gather(*(run(page_range) for page_range in ranges), return_exceptions=True)
    pages: list[list[PageItem]] = []
    for (page_start, page_end), result in zip(ranges, results, strict=True):
        if isinstance(result, BaseException):
            logger.warning("消息分页拉取失败: chat=%s range=%s-%s: %r", chat_key, page_start, page_end, result)
            continue
        pages.append(result)
    return [message for page in pages for message in page]


def _build_signer_url(base_url: str, token: str) -> str | None:
    """把配置中的签名服务地址构造成 lagrange 需要的完整 URL。"""
    if not base_url:
        return None
    parts = urlsplit(base_url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    endpoint = (
        base_url if base_url.rstrip("/").endswith("/api/sign/sec-sign") else f"{base_url.rstrip('/')}/api/sign/sec-sign"
    )
    if not token:
        return endpoint

    parts = urlsplit(endpoint)
    netloc = f"{quote(token, safe='')}@{parts.netloc}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _load_custom_sign_factory(login: LoginConfig) -> SignFactory | None:
    """加载自定义签名工厂；未启用或文件缺失时返回 None 以便回退。"""
    if not login.use_custom_sign_provider:
        return None
    try:
        return load_sign_provider(login.sign_provider_path, login.sign_provider_entry)
    except FileNotFoundError:
        logger.warning("自定义签名文件不存在，回退到签名服务: %s", login.sign_provider_path)
    except Exception:
        logger.exception("自定义签名文件加载失败，回退到签名服务: %s", login.sign_provider_path)
    return None


def _build_sign(login: LoginConfig, info: InfoManager, app_info: AppInfo) -> Any:
    """构造 hiro-qq 需要的签名回调，优先使用本地自定义签名实现。"""
    signer_url = _build_signer_url(login.signer_url, login.signer_token)
    factory = _load_custom_sign_factory(login)
    if factory is not None:
        logger.info("使用自定义签名实现: %s", login.sign_provider_path)
        return factory(signer_url, login.uin, info.device.guid, app_info.qua)
    if signer_url:
        return sign_provider(signer_url, login.uin, info.device.guid, app_info.qua)
    return None


def _seed_login_info(paths: PathsConfig, uin: int) -> None:
    """首次运行时从本地 lagrange-python 目录迁移同一账号的设备与签名信息。

    只补齐缺失的目标文件，不覆盖 Flaza 自己已经维护的登录状态；源文件
    与配置 uin 不一致时跳过，避免把其他账号的凭据搬进来。
    """
    source_dir = Path(paths.login_info_source_dir).expanduser() if paths.login_info_source_dir else None
    if source_dir is None or not source_dir.is_dir():
        return
    device_target = Path(paths.device_info_path)
    sig_target = Path(paths.sign_info_path)
    if device_target.exists() and sig_target.exists():
        return

    source_device = source_dir / "device.json"
    source_sig = source_dir / "sig.bin"
    if not source_device.is_file() or not source_sig.is_file():
        return
    try:
        source_uin = SigInfo.load(source_sig.read_bytes()).uin
    except Exception:
        logger.warning("无法读取待迁移的签名信息: %s", source_sig, exc_info=True)
        return
    if source_uin != uin:
        logger.warning("本地登录信息属于其他账号，跳过迁移: source=%s config=%s", source_uin, uin)
        return

    device_target.parent.mkdir(parents=True, exist_ok=True)
    sig_target.parent.mkdir(parents=True, exist_ok=True)
    if not device_target.exists():
        shutil.copy2(source_device, device_target)
    if not sig_target.exists():
        shutil.copy2(source_sig, sig_target)
    logger.info("已从 %s 迁移登录信息", source_dir)
