"""会话目标模型。"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class FriendChat(BaseModel):
    """好友会话目标。"""

    model_config = ConfigDict(frozen=True)

    kind: Literal["friend"] = "friend"
    uid: str
    uin: int

    @property
    def key(self) -> str:
        """跨窗口和存储使用的稳定会话键。"""
        return f"friend:{self.uid}"

    @property
    def storage_id(self) -> str:
        """存储层使用的 chat_id。"""
        return self.uid


class GroupChat(BaseModel):
    """群会话目标。"""

    model_config = ConfigDict(frozen=True)

    kind: Literal["group"] = "group"
    group_id: int

    @property
    def key(self) -> str:
        """跨窗口和存储使用的稳定会话键。"""
        return f"group:{self.group_id}"

    @property
    def storage_id(self) -> str:
        """存储层使用的 chat_id。"""
        return str(self.group_id)


ChatTarget = Annotated[FriendChat | GroupChat, Field(discriminator="kind")]
