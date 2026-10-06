"""协议端口定义。

这是 core 与 qq 之间唯一的依赖方向：core 定义接口，qq 负责实现。
"""

from collections.abc import Sequence
from typing import Protocol

from flaza.core.models import (
    ChatTarget,
    Friend,
    Group,
    GroupMember,
    Message,
    MessageElement,
    PendingRequest,
    QrCodeData,
    QrCodeState,
    SelfInfo,
    SilentLoginResult,
    UserProfile,
)


class QQClient(Protocol):
    """hiro-qq 协议能力的抽象。

    所有方法语义由具体实现保证；core 服务和 UI 只依赖此接口。
    """

    async def start(self) -> None:
        """加载设备与签名信息，创建底层客户端并启动网络任务。"""

    async def stop(self) -> None:
        """停止网络任务并保存设备/签名信息。"""

    # ---- 登录 ----

    async def try_silent_login(self) -> SilentLoginResult:
        """尝试使用已有会话静默登录。"""

    async def fetch_qrcode(self) -> QrCodeData:
        """获取登录二维码。"""

    async def poll_qrcode(self) -> QrCodeState:
        """查询当前二维码状态。"""

    async def complete_qrcode_login(self) -> None:
        """在二维码确认后完成最终登录与注册。"""

    async def cancel_login(self) -> None:
        """取消当前登录流程。"""

    # ---- 在线后的基础能力 ----

    async def get_self_info(self) -> SelfInfo:
        """返回当前账号信息。"""

    async def fetch_friends(self) -> list[Friend]:
        """拉取好友列表。"""

    async def fetch_groups(self) -> list[Group]:
        """拉取群列表。"""

    async def fetch_group_members(self, group_id: int) -> list[GroupMember]:
        """拉取指定群的成员身份列表。"""

    async def fetch_group_member(self, group_id: int, uid: str) -> GroupMember | None:
        """查询指定群成员的即时身份。"""

    async def send_message(self, target: ChatTarget, elements: Sequence[MessageElement]) -> Message:
        """发送一条消息并返回领域消息模型。"""

    async def send_file(self, target: ChatTarget, path: str, filename: str | None = None) -> Message:
        """发送本地文件并返回领域消息模型。"""

    async def recall_message(self, target: ChatTarget, seq: int) -> None:
        """撤回自己发送的指定 seq 消息。"""

    async def send_reaction(
        self, chat: ChatTarget, seq: int, emoji_id: str, emoji_type: int = 2, is_cancel: bool = False
    ) -> None:
        """对消息发送表情回应；仅群聊支持。"""

    async def send_nudge(self, target: ChatTarget, uin: int) -> None:
        """向好友或群成员发送戳一戳。"""

    async def respond_friend_request(self, uid: str, accept: bool) -> None:
        """同意或拒绝一条好友申请。"""

    async def fetch_group_requests(self) -> list[PendingRequest]:
        """拉取待处理的入群申请与群邀请。"""

    async def respond_group_request(self, group_id: int, seq: int, event_type: int, accept: bool) -> None:
        """同意或拒绝一条入群申请/群邀请。"""

    async def fetch_user_profile(self, uid: str = "", uin: int = 0) -> UserProfile:
        """拉取好友或群成员的资料卡。"""

    async def like_friend(self, uid: str) -> int:
        """给好友名片点赞，返回本次新增的赞数。"""

    async def set_self_nickname(self, nickname: str) -> None:
        """修改当前账号昵称。"""

    async def set_self_bio(self, bio: str) -> None:
        """修改当前账号个性签名。"""

    async def set_self_avatar(self, path: str) -> None:
        """上传并修改当前账号头像。"""

    # ---- 群管理 ----

    async def rename_group(self, group_id: int, name: str) -> None:
        """修改群名称。"""

    async def rename_group_member(self, group_id: int, uid: str, name: str) -> None:
        """修改指定成员的群名片。"""

    async def kick_group_member(self, group_id: int, uin: int) -> None:
        """把成员移出群聊。"""

    async def set_group_admin(self, group_id: int, uid: str, is_set: bool) -> None:
        """设置或取消群管理员。"""

    async def set_group_special_title(self, group_id: int, uid: str, title: str) -> None:
        """设置群成员专属头衔。"""

    async def set_group_mute(self, group_id: int, enable: bool) -> None:
        """开启或解除全员禁言。"""

    async def mute_group_member(self, group_id: int, uin: int, duration: int) -> None:
        """禁言指定成员，duration 为秒。"""

    async def leave_group(self, group_id: int) -> None:
        """退出群聊。"""

    async def invite_group_members(self, group_id: int, uids: list[str] | dict[str, int]) -> None:
        """邀请好友加入群聊。"""

    async def set_group_essence(self, group_id: int, seq: int, rand: int, is_remove: bool = False) -> None:
        """设置或取消群精华消息。"""

    async def fetch_forward_messages(self, chat: ChatTarget, resid: str) -> list[Message]:
        """拉取合并转发卡片中的消息内容。"""

    async def fetch_message(self, chat: ChatTarget, seq: int) -> Message | None:
        """按 seq 重新拉取单条消息（用于刷新失效的媒体地址）。"""

    async def forward_messages(self, target: ChatTarget, messages: list[Message]) -> None:
        """把消息作为合并转发卡片发送到目标会话。"""

    async def fetch_missing_messages(self, chat: ChatTarget, after_seq: int, limit: int = 500) -> list[Message]:
        """补拉指定会话在 after_seq 之后的消息。"""
