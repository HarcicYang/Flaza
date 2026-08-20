"""消息领域模型。"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from flaza.core.models.chat import ChatTarget
from flaza.core.models.contact import GroupMemberRole


class TextElement(BaseModel):
    """纯文本消息元素。"""

    model_config = ConfigDict(frozen=True)

    kind: Literal["text"] = "text"
    text: str

    @property
    def preview_text(self) -> str:
        """会话列表等场景使用的派生预览文本。"""
        return self.text


class AtElement(BaseModel):
    """群消息中的 @成员。"""

    model_config = ConfigDict(frozen=True)

    kind: Literal["at"] = "at"
    text: str
    uin: int
    uid: str = ""

    @property
    def preview_text(self) -> str:
        return self.text


class AtAllElement(BaseModel):
    """群消息中的 @全体成员。"""

    model_config = ConfigDict(frozen=True)

    kind: Literal["at_all"] = "at_all"
    text: str

    @property
    def preview_text(self) -> str:
        return self.text


class ImageElement(BaseModel):
    """图片消息元素。

    ``url`` 为 lagrange 解码时解析出的预览地址；``cached_path`` 是接收
    消息下载到本地后的缓存路径，发送成功后会短暂指向本地原图以便立即
    渲染；``local_path`` 仅用于发送：指向待上传的本地图片，发送成功后
    会被替换为协议返回的图片信息，不会持久化。
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["image"] = "image"
    url: str = ""
    name: str = ""
    size: int = 0
    md5: bytes = b""
    width: int = 0
    height: int = 0
    is_emoji: bool = False
    display_name: str = ""
    cached_path: str = ""
    local_path: str = ""

    @property
    def preview_text(self) -> str:
        return "[动画表情]" if self.is_emoji else "[图片]"


class EmojiElement(BaseModel):
    """QQ 内置黄脸 / 超级表情。"""

    model_config = ConfigDict(frozen=True)

    kind: Literal["emoji"] = "emoji"
    id: int

    @property
    def preview_text(self) -> str:
        return "[表情]"


class MarketFaceElement(BaseModel):
    """商城表情，url 由 face_id 派生。"""

    model_config = ConfigDict(frozen=True)

    kind: Literal["market_face"] = "market_face"
    name: str
    face_id: bytes
    tab_id: int
    width: int
    height: int
    cached_path: str = ""

    @property
    def url(self) -> str:
        """lagrange 使用的商城表情 CDN 地址。"""
        if not self.face_id:
            return ""
        pic_id = self.face_id.hex()
        return f"https://i.gtimg.cn/club/item/parcel/item/{pic_id[:2]}/{pic_id}/{self.width}x{self.height}.png"

    @property
    def preview_text(self) -> str:
        return "[动画表情]"


class AudioElement(BaseModel):
    """语音消息元素。"""

    model_config = ConfigDict(frozen=True)

    kind: Literal["audio"] = "audio"
    url: str = ""
    time: int = 0
    file_key: str = ""
    name: str = ""
    size: int = 0
    md5: bytes = b""
    cached_path: str = ""

    @property
    def preview_text(self) -> str:
        return "[语音]"


class VideoElement(BaseModel):
    """短视频消息元素。"""

    model_config = ConfigDict(frozen=True)

    kind: Literal["video"] = "video"
    url: str = ""
    name: str = ""
    size: int = 0
    width: int = 0
    height: int = 0
    time: int = 0
    file_key: str = ""
    md5: bytes = b""
    cached_path: str = ""

    @property
    def preview_text(self) -> str:
        return "[视频]"


class FileElement(BaseModel):
    """文件消息元素。"""

    model_config = ConfigDict(frozen=True)

    kind: Literal["file"] = "file"
    file_name: str
    file_size: int = 0
    file_url: str | None = None
    file_id: str | None = None
    file_uuid: str | None = None
    file_hash: str | None = None
    md5: bytes = b""
    cached_path: str = ""

    @property
    def preview_text(self) -> str:
        return f"[文件] {self.file_name}"


class PokeElement(BaseModel):
    """戳一戳消息元素。"""

    model_config = ConfigDict(frozen=True)

    kind: Literal["poke"] = "poke"
    id: int

    @property
    def preview_text(self) -> str:
        return "[戳一戳]"


class QuoteElement(BaseModel):
    """回复引用元素。"""

    model_config = ConfigDict(frozen=True)

    kind: Literal["quote"] = "quote"
    seq: int
    uin: int
    timestamp: int
    uid: str = ""
    msg: str = ""
    sender_name: str = ""

    @property
    def preview_text(self) -> str:
        if not self.msg:
            return "[回复]"
        excerpt = self.msg if len(self.msg) <= 30 else f"{self.msg[:30]}…"
        return f"[回复] {excerpt}"


class ForwardElement(BaseModel):
    """合并转发消息卡片。本期只保存摘要，不拉取转发内容。"""

    model_config = ConfigDict(frozen=True)

    kind: Literal["forward"] = "forward"
    resid: str = ""
    file_name: str = ""

    @property
    def preview_text(self) -> str:
        return "[聊天记录]"


class UnknownElement(BaseModel):
    """暂不展开或无法识别的消息元素，保留原始类型名与显示摘要。"""

    model_config = ConfigDict(frozen=True)

    kind: Literal["unknown"] = "unknown"
    original_kind: str = ""
    display: str = "[未知消息]"

    @property
    def preview_text(self) -> str:
        return self.display or "[未知消息]"


# 元素联合类型。旧数据库中的 TextElement 仍可被新联合正常解析，
# 因此这是一次向后兼容的模型扩展，暂不提升 payload schema version。
MessageElement = Annotated[
    TextElement
    | AtElement
    | AtAllElement
    | ImageElement
    | EmojiElement
    | MarketFaceElement
    | AudioElement
    | VideoElement
    | FileElement
    | PokeElement
    | QuoteElement
    | ForwardElement
    | UnknownElement,
    Field(discriminator="kind"),
]


class MessageReaction(BaseModel):
    """消息表情回应。"""

    model_config = ConfigDict(frozen=True)

    emoji_id: str
    emoji_type: int = 2  # 1=QQ内置, 2=Unicode
    count: int = 0
    users: list[str] = []  # uid 列表


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
    recalled: bool = False
    sender_is_bot: bool = False
    sender_role: GroupMemberRole = GroupMemberRole.MEMBER
    reactions: list[MessageReaction] = []

    @property
    def text(self) -> str:
        """消息预览文本，由元素派生。"""
        return "".join(element.preview_text for element in self.elements)


class StoredMessage(BaseModel):
    """带本地自增 id 的消息，供分页和已读游标使用。"""

    model_config = ConfigDict(frozen=True)

    id: int
    message: Message
