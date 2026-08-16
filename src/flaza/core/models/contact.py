"""联系人与群资料模型。"""

from pydantic import BaseModel, ConfigDict


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

    @property
    def display_name(self) -> str:
        return self.name or str(self.group_id)
