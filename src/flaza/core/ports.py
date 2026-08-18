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
    QrCodeData,
    QrCodeState,
    SelfInfo,
    SilentLoginResult,
)


class QQClient(Protocol):
    """lagrange-python 协议能力的抽象。

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

    async def fetch_missing_messages(self, chat: ChatTarget, after_seq: int, limit: int = 500) -> list[Message]:
        """补拉指定会话在 after_seq 之后的消息。"""
