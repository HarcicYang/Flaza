"""消息领域模型。"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from flaza.core.models.chat import ChatTarget


class TextElement(BaseModel):
    """纯文本消息元素。"""

    model_config = ConfigDict(frozen=True)

    kind: Literal["text"] = "text"
    text: str


# 目前只有文本元素；图片、At、合并转发等后续扩展此联合类型。
MessageElement = Annotated[TextElement, Field(discriminator="kind")]


class Message(BaseModel):
    """统一的领域消息模型。

    `elements` 是事实来源，`text` 只是为列表预览和搜索提供的派生文本。
    """

    model_config = ConfigDict(frozen=True)

    chat: ChatTarget
    sender_uin: int
    sender_uid: str
    sender_name: str = ""
    seq: int
    client_seq: int | None = None
    rand: int | None = None
    timestamp: int
    elements: list[MessageElement]
    from_self: bool = False

    @property
    def text(self) -> str:
        """消息预览文本，由元素派生。"""
        return "".join(element.text for element in self.elements)


class StoredMessage(BaseModel):
    """带本地自增 id 的消息，供分页和已读游标使用。"""

    model_config = ConfigDict(frozen=True)

    id: int
    message: Message
