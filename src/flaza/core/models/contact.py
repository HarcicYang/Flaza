"""联系人、群资料与群成员身份模型。"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class GroupMemberRole(StrEnum):
    """群成员在 UI 中展示的身份。"""

    OWNER = "owner"
    ADMIN = "admin"
    BOT = "bot"
    MEMBER = "member"


class Friend(BaseModel):
    """好友资料。"""

    model_config = ConfigDict(frozen=True)

    uin: int
    uid: str
    nickname: str = ""
    remark: str | None = None

    @property
    def display_name(self) -> str:
        """会话列表优先显示备注，其次昵称。"""
        return self.remark or self.nickname or str(self.uin)


class Group(BaseModel):
    """群资料。"""

    model_config = ConfigDict(frozen=True)

    group_id: int
    name: str = ""
    member_count: int = 0
    owner_uid: str | None = None

    @property
    def display_name(self) -> str:
        return self.name or str(self.group_id)


class GroupMember(BaseModel):
    """群成员身份缓存。"""

    model_config = ConfigDict(frozen=True)

    group_id: int
    uid: str
    uin: int = 0
    nickname: str = ""
    role: GroupMemberRole = GroupMemberRole.MEMBER
