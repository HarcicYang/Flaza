"""会话列表模型。"""

from pydantic import BaseModel, ConfigDict

from flaza.core.models.chat import ChatTarget


class Session(BaseModel):
    """由消息和联系人派生出来的会话摘要。"""

    model_config = ConfigDict(frozen=True)

    chat: ChatTarget
    title: str
    last_text: str = ""
    last_timestamp: int = 0
    last_message_id: int = 0
    message_count: int = 0
    unread_count: int = 0
