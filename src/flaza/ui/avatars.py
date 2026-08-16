"""头像 URL 生成。

QQ 公开头像服务支持按 uin / group_id 直接取图，因此头像地址不需要进入领域模型或数据库。
"""

from flaza.core.models import ChatTarget, FriendChat, GroupChat

_QQ_AVATAR_SIZE = 100


def friend_avatar_url(uin: int) -> str:
    """QQ 用户头像。"""
    return f"https://q1.qlogo.cn/g?b=qq&nk={uin}&s={_QQ_AVATAR_SIZE}"


def group_avatar_url(group_id: int) -> str:
    """QQ 群头像。"""
    return f"https://p.qlogo.cn/gh/{group_id}/{group_id}/{_QQ_AVATAR_SIZE}/"


def chat_avatar_url(chat: ChatTarget) -> str:
    """按会话目标返回头像地址。"""
    if isinstance(chat, FriendChat):
        return friend_avatar_url(chat.uin)
    if isinstance(chat, GroupChat):
        return group_avatar_url(chat.group_id)
    raise TypeError(f"未知会话目标: {chat!r}")
