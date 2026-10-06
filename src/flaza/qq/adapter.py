"""lagrange 事件订阅与领域事件转换。

lagrange 的 Events 每个事件类型只允许一个订阅者，因此这里统一订阅，
再通过领域 EventBus 在 Flaza 内部 fan-out。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from typing import Any

from lagrange.client.client import Client
from lagrange.client.events.friend import (
    FriendAddNotify,
    FriendMessage,
    FriendPoke,
    FriendRecall,
    FriendRequest,
    FriendRequestFinished,
)
from lagrange.client.events.group import (
    BotGrayTip,
    GroupAdminChange,
    GroupAlbumUpdate,
    GroupBotAdded,
    GroupBotJoined,
    GroupInvite,
    GroupMemberGotSpecialTitle,
    GroupMemberJoined,
    GroupMemberJoinedByInvite,
    GroupMemberJoinRequest,
    GroupMemberQuit,
    GroupMessage,
    GroupMuteMember,
    GroupNudge,
    GroupReaction,
    GroupRecall,
    GroupSelfJoined,
    GroupSelfRequireReject,
    GroupSign,
)
from lagrange.client.events.group import (
    GroupNameChanged as LagrangeGroupNameChanged,
)
from lagrange.client.events.service import ClientOffline, ClientOnline, OtherClientInfo, ServerKick
from lagrange.client.message import elems as lagrange_elems

from flaza.core.events import (
    ConnectionStateChanged,
    EventBus,
    FriendPoked,
    GroupAdminChanged,
    GroupMemberMuted,
    GroupNameChanged,
    GroupNotice,
    GroupNudged,
    GroupReactionChanged,
    MessageRecalled,
    MessageReceived,
    OtherClientsUpdated,
    RequestReceived,
    RequestResolved,
)
from flaza.core.events import (
    GroupMemberJoined as GroupMemberJoinedEvent,
)
from flaza.core.events import (
    GroupMemberQuit as GroupMemberQuitEvent,
)
from flaza.core.models import (
    ConnectionState,
    FriendChat,
    GroupChat,
    GroupMemberRole,
    OnlineClient,
    PendingRequest,
    RequestKind,
)
from flaza.core.storage.repositories.messages import MessageRepository
from flaza.qq.convert import friend_message_to_domain, group_message_to_domain

logger = logging.getLogger(__name__)


class LagrangeEventAdapter:
    """把 lagrange 事件转换为 Flaza 领域事件。"""

    def __init__(self, bus: EventBus, messages: MessageRepository | None = None) -> None:
        self._bus = bus
        self._client: Client | None = None
        self._group_message_lock = asyncio.Lock()
        self._member_role_cache: dict[tuple[int, str], GroupMemberRole] = {}
        self._member_role_failed_at: dict[tuple[int, str], float] = {}
        self._messages = messages

    def subscribe(self, client: Client) -> None:
        """注册所有 MVP 所需的 lagrange 事件。"""
        self._client = client
        client.events.subscribe(FriendMessage, self._on_friend_message)
        client.events.subscribe(FriendRecall, self._on_friend_recall)
        client.events.subscribe(GroupMessage, self._on_group_message)
        client.events.subscribe(GroupRecall, self._on_group_recall)
        client.events.subscribe(LagrangeGroupNameChanged, self._on_group_name_changed)
        client.events.subscribe(GroupMemberJoined, self._on_group_member_joined)
        client.events.subscribe(GroupMemberQuit, self._on_group_member_quit)
        client.events.subscribe(GroupAdminChange, self._on_group_admin_change)
        client.events.subscribe(GroupMuteMember, self._on_group_mute_member)
        client.events.subscribe(GroupReaction, self._on_group_reaction)
        client.events.subscribe(FriendPoke, self._on_friend_poke)
        client.events.subscribe(GroupNudge, self._on_group_nudge)
        client.events.subscribe(FriendRequest, self._on_friend_request)
        client.events.subscribe(FriendRequestFinished, self._on_friend_request_finished)
        client.events.subscribe(FriendAddNotify, self._on_friend_add_notify)
        client.events.subscribe(GroupMemberJoinRequest, self._on_group_join_request)
        client.events.subscribe(GroupInvite, self._on_group_invite)
        for notice_type in (
            GroupSign,
            GroupMemberGotSpecialTitle,
            GroupMemberJoinedByInvite,
            GroupSelfJoined,
            GroupSelfRequireReject,
            GroupBotAdded,
            BotGrayTip,
            GroupBotJoined,
            GroupAlbumUpdate,
        ):
            client.events.subscribe(notice_type, self._on_group_notice)
        client.events.subscribe(ClientOnline, self._on_client_online)
        client.events.subscribe(ClientOffline, self._on_client_offline)
        client.events.subscribe(ServerKick, self._on_server_kick)
        client.events.subscribe(OtherClientInfo, self._on_other_clients)

    @property
    def client(self) -> Client:
        if self._client is None:
            raise RuntimeError("LagrangeEventAdapter 尚未订阅")
        return self._client

    async def _on_friend_message(self, client: Client, event: Any) -> None:
        message = friend_message_to_domain(event, client.uin)
        logger.debug("收到好友消息: chat=%s seq=%s", message.chat.key, message.seq)
        self._bus.publish(MessageReceived(message=message))

    async def _on_friend_recall(self, client: Client, event: Any) -> None:
        self._bus.publish(
            MessageRecalled(
                chat=_friend_recall_chat(event, client.uin),
                seq=event.seq,
                timestamp=event.timestamp,
            )
        )

    async def _on_group_recall(self, _client: Client, event: Any) -> None:
        self._bus.publish(
            MessageRecalled(
                chat=GroupChat(group_id=event.grp_id),
                seq=event.seq,
                timestamp=event.time,
                operator_uid=event.operator_id,
            )
        )

    async def _on_group_name_changed(self, _client: Client, event: Any) -> None:
        self._bus.publish(
            GroupNameChanged(
                group_id=event.grp_id,
                name_new=event.name_new,
                operator_uid=event.operator_uid,
                timestamp=event.timestamp,
            )
        )

    async def _on_group_member_joined(self, _client: Client, event: Any) -> None:
        self._bus.publish(
            GroupMemberJoinedEvent(
                group_id=event.grp_id,
                uid=event.uid,
                join_type=event.join_type,
                timestamp=int(time.time()),
            )
        )

    async def _on_group_member_quit(self, _client: Client, event: Any) -> None:
        self._member_role_cache.pop((event.grp_id, event.uid), None)
        self._bus.publish(
            GroupMemberQuitEvent(
                group_id=event.grp_id,
                uid=event.uid,
                uin=event.uin,
                exit_type=event.exit_type,
                operator_uid=event.operator_uid,
                timestamp=int(time.time()),
            )
        )

    async def _on_group_admin_change(self, _client: Client, event: Any) -> None:
        role = GroupMemberRole.ADMIN if event.is_set else GroupMemberRole.MEMBER
        self._member_role_cache[(event.grp_id, event.uid)] = role
        self._bus.publish(
            GroupAdminChanged(
                group_id=event.grp_id,
                uid=event.uid,
                is_set=event.is_set,
                timestamp=int(time.time()),
            )
        )

    async def _on_group_mute_member(self, _client: Client, event: Any) -> None:
        self._bus.publish(
            GroupMemberMuted(
                group_id=event.grp_id,
                operator_uid=event.operator_uid,
                target_uid=event.target_uid,
                duration=event.duration,
                timestamp=int(time.time()),
            )
        )

    async def _on_group_reaction(self, _client: Client, event: Any) -> None:
        try:
            # emoji_id 是 Unicode code point (int)，需要转为实际字符
            emoji_char = chr(event.emoji_id) if event.emoji_type == 2 else str(event.emoji_id)
            self._bus.publish(
                GroupReactionChanged(
                    group_id=event.grp_id,
                    seq=event.seq,
                    emoji_id=emoji_char,
                    emoji_type=event.emoji_type,
                    count=event.emoji_count,
                    is_increase=event.is_increase,
                    operator_uid=event.uid,
                )
            )
        except Exception:
            logger.debug("处理群表情回应事件失败", exc_info=True)

    async def _on_friend_poke(self, _client: Client, event: Any) -> None:
        self._bus.publish(
            FriendPoked(
                sender_uin=event.sender_uin or event.from_uin,
                sender_uid=event.sender_uid or event.from_uid,
                target_uin=event.target_uin,
                action=event.action,
                suffix=event.suffix,
                timestamp=event.timestamp or int(time.time()),
            )
        )

    async def _on_group_nudge(self, _client: Client, event: Any) -> None:
        self._bus.publish(
            GroupNudged(
                group_id=event.grp_id,
                sender_uin=event.sender_uin,
                target_uin=event.target_uin,
                action=event.action,
                suffix=event.suffix,
            )
        )

    async def _on_group_notice(self, _client: Client, event: Any) -> None:
        """把纯提示类群事件投影为聊天流灰条。"""
        notice = _group_notice_from_event(event)
        if notice is not None:
            self._bus.publish(notice)

    async def _on_friend_request(self, _client: Client, event: Any) -> None:
        self._bus.publish(
            RequestReceived(
                request=PendingRequest(
                    key=f"friend:{event.from_uid}",
                    kind=RequestKind.FRIEND,
                    title=f"{event.from_uin} 请求添加你为好友",
                    subtitle=event.message or "",
                    target_uid=event.from_uid,
                    timestamp=int(time.time()),
                )
            )
        )

    async def _on_friend_request_finished(self, _client: Client, event: Any) -> None:
        accepted = event.result == 0
        self._bus.publish(
            RequestResolved(
                key=f"friend:{event.from_uid}",
                accepted=accepted,
                detail="好友申请已通过" if accepted else "好友申请未通过",
                refresh_contacts=accepted,
            )
        )

    async def _on_friend_add_notify(self, _client: Client, event: Any) -> None:
        self._bus.publish(
            RequestResolved(
                key=f"friend:{event.from_uid}",
                accepted=True,
                detail="已成为好友",
                refresh_contacts=True,
            )
        )

    async def _on_group_join_request(self, _client: Client, event: Any) -> None:
        """入群申请事件不带 seq；先给出占位条目，通知中心会再拉取完整参数。"""
        self._bus.publish(
            RequestReceived(
                request=PendingRequest(
                    key=f"group-join:{event.grp_id}:{event.uid}",
                    kind=RequestKind.GROUP_JOIN,
                    title="有新的入群申请",
                    subtitle=event.answer or "",
                    target_uid=event.uid,
                    group_id=event.grp_id,
                    timestamp=int(time.time()),
                )
            )
        )

    async def _on_group_invite(self, _client: Client, event: Any) -> None:
        self._bus.publish(
            RequestReceived(
                request=PendingRequest(
                    key=f"group-invite:{event.grp_id}",
                    kind=RequestKind.GROUP_INVITE,
                    title="你收到了加入群聊的邀请",
                    subtitle=f"群 {event.grp_id}",
                    group_id=event.grp_id,
                    timestamp=int(time.time()),
                )
            )
        )

    async def _on_group_message(self, client: Client, event: Any) -> None:
        async with self._group_message_lock:
            uid_to_nickname = await self._resolve_quote_nicknames(event)
            message = group_message_to_domain(event, client.uin, uid_to_nickname=uid_to_nickname)
            if (
                isinstance(message.chat, GroupChat)
                and not message.from_self
                and message.sender_role is GroupMemberRole.MEMBER
            ):
                role = await self._resolve_member_role(client, message.chat.group_id, message.sender_uid)
                message = message.model_copy(update={"sender_role": role})
            logger.debug("收到群消息: chat=%s seq=%s", message.chat.key, message.seq)
            self._bus.publish(MessageReceived(message=message))

    async def _resolve_quote_nicknames(self, event: Any) -> dict[str, str] | None:
        """遍历 msg_chain 中的 Quote 元素，查被引用消息的 sender_name。"""
        if self._messages is None:
            return None
        uid_to_nickname: dict[str, str] = {}
        for elem in event.msg_chain:
            if isinstance(elem, lagrange_elems.Quote):
                chat = GroupChat(group_id=event.grp_id)
                stored = await self._messages.get_by_seq(chat, elem.seq)
                if stored is not None:
                    name = stored.message.sender_name or str(elem.uin)
                    uid_to_nickname[elem.uid or str(elem.uin)] = name
        return uid_to_nickname or None

    async def _on_client_online(self, _client: Client, _event: Any) -> None:
        self._bus.publish(ConnectionStateChanged(state=ConnectionState.ONLINE))

    async def _on_client_offline(self, _client: Client, event: Any) -> None:
        state = ConnectionState.RECONNECTING if event.recoverable else ConnectionState.OFFLINE
        self._bus.publish(ConnectionStateChanged(state=state))

    async def _on_server_kick(self, _client: Client, event: Any) -> None:
        self._bus.publish(
            ConnectionStateChanged(
                state=ConnectionState.KICKED,
                detail=f"{event.title}: {event.tips}",
            )
        )

    async def _on_other_clients(self, _client: Client, event: Any) -> None:
        self._bus.publish(
            OtherClientsUpdated(
                clients=[
                    OnlineClient(
                        sub_id=client.sub_id,
                        os_name=client.os_name,
                        device_name=client.device_name,
                    )
                    for client in event.clients
                ]
            )
        )

    async def _resolve_member_role(self, client: Client, group_id: int, uid: str) -> GroupMemberRole:
        key = (group_id, uid)
        cached = self._member_role_cache.get(key)
        if cached is not None:
            return cached

        now = time.monotonic()
        if now - self._member_role_failed_at.get(key, 0.0) < 60.0:
            return GroupMemberRole.MEMBER

        try:
            response = await client.get_grp_member_info(group_id, uid)
            if not response.body:
                role = GroupMemberRole.MEMBER
            else:
                body = response.body[0]
                if body.is_owner:
                    role = GroupMemberRole.OWNER
                elif body.is_admin:
                    role = GroupMemberRole.ADMIN
                else:
                    role = GroupMemberRole.MEMBER
            self._member_role_cache[key] = role
            return role
        except Exception:
            logger.debug("查询群成员身份失败: group=%s uid=%s", group_id, uid, exc_info=True)
            self._member_role_failed_at[key] = now
            return GroupMemberRole.MEMBER


def _friend_recall_chat(event: Any, self_uin: int) -> FriendChat:
    if event.from_uin == self_uin:
        return FriendChat(uid=event.to_uid, uin=event.to_uin)
    return FriendChat(uid=event.from_uid, uin=event.from_uin)


def _group_notice_from_event(event: Any) -> GroupNotice | None:
    """把 hiro-qq 的提示类群事件翻译成灰条文案。"""
    group_id = int(getattr(event, "grp_id", 0))
    now = int(time.time())
    if isinstance(event, GroupSign):
        name = event.nickname or str(event.uin)
        timestamp = event.timestamp or now
        return GroupNotice(
            group_id=group_id,
            text=f"{name} 打卡了",
            timestamp=timestamp,
            key=f"sign:{group_id}:{event.uin}:{timestamp}",
            kind="sign",
        )
    if isinstance(event, GroupMemberGotSpecialTitle):
        return GroupNotice(
            group_id=group_id,
            text=f"{event.member_uin} 获得专属头衔“{event.special_title}”",
            timestamp=now,
            key=f"title:{group_id}:{event.member_uin}:{event.special_title}",
            kind="special_title",
        )
    if isinstance(event, GroupInvite):
        return GroupNotice(
            group_id=group_id,
            text="你收到了加入群聊的邀请",
            timestamp=now,
            key=f"invite:{group_id}:{event.invitor_uid}",
            kind="invite",
        )
    if isinstance(event, GroupMemberJoinedByInvite):
        return GroupNotice(
            group_id=group_id,
            text=f"{event.invitor_uin} 邀请 {event.uin} 加入了群聊",
            timestamp=now,
            key=f"invite-joined:{group_id}:{event.uin}",
            kind="member_joined",
        )
    if isinstance(event, GroupSelfJoined):
        return GroupNotice(
            group_id=group_id,
            text="你加入了群聊",
            timestamp=now,
            key=f"self-joined:{group_id}:{event.op_uid}",
            kind="self_joined",
        )
    if isinstance(event, GroupSelfRequireReject):
        return GroupNotice(
            group_id=group_id,
            text=f"入群申请被拒绝：{event.message}" if event.message else "入群申请被拒绝",
            timestamp=now,
            key=f"self-reject:{group_id}",
            kind="join_rejected",
        )
    if isinstance(event, GroupBotAdded):
        return GroupNotice(
            group_id=group_id,
            text="群内添加了机器人",
            timestamp=now,
            key=f"bot-added:{group_id}:{event.bot_uid}",
            kind="bot_added",
        )
    if isinstance(event, BotGrayTip):
        digest = hashlib.sha1(event.content.encode("utf-8", "ignore")).hexdigest()[:12]
        return GroupNotice(
            group_id=group_id,
            text=event.content,
            timestamp=now,
            key=f"bot-tip:{group_id}:{digest}",
            kind="bot_tip",
        )
    if isinstance(event, GroupBotJoined):
        return GroupNotice(
            group_id=group_id,
            text=f"{event.nick_name} 添加了机器人 {event.robot_name}",
            timestamp=now,
            key=f"bot-joined:{group_id}:{event.opqq_uin}",
            kind="bot_joined",
        )
    if isinstance(event, GroupAlbumUpdate):
        return GroupNotice(
            group_id=group_id,
            text="群相册有更新",
            timestamp=event.timestamp or now,
            key=f"album:{group_id}:{event.image_id}",
            kind="album",
        )
    return None
