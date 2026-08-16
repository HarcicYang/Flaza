"""头像 URL 生成测试。"""

from flaza.core.models import FriendChat, GroupChat
from flaza.ui.avatars import chat_avatar_url, friend_avatar_url, group_avatar_url


def test_avatar_urls() -> None:
    assert friend_avatar_url(10001) == "https://q1.qlogo.cn/g?b=qq&nk=10001&s=100"
    assert group_avatar_url(20002) == "https://p.qlogo.cn/gh/20002/20002/100/"
    assert chat_avatar_url(FriendChat(uid="u_1", uin=10001)) == friend_avatar_url(10001)
    assert chat_avatar_url(GroupChat(group_id=20002)) == group_avatar_url(20002)
