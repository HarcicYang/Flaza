"""待处理的好友申请、入群申请与群邀请。"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class RequestKind(StrEnum):
    """申请/邀请类型。"""

    FRIEND = "friend"
    GROUP_JOIN = "group_join"
    GROUP_INVITE = "group_invite"


class PendingRequest(BaseModel):
    """通知中心里一条可处理的申请或邀请。"""

    model_config = ConfigDict(frozen=True)

    key: str
    kind: RequestKind
    title: str
    subtitle: str = ""
    target_uid: str = ""
    group_id: int = 0
    group_name: str = ""
    seq: int = 0
    event_type: int = 0
    timestamp: int = 0

    @property
    def can_respond(self) -> bool:
        """是否已经拿到足够的信息执行同意/拒绝。"""
        if self.kind is RequestKind.FRIEND:
            return bool(self.target_uid)
        return bool(self.group_id and self.seq)
