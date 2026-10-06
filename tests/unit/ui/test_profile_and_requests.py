"""通知中心、资料卡与群管理对话框构建测试。"""

from neony.dom import DOMElement

from flaza.config import LoginConfig, PathsConfig, WindowSettings
from flaza.core.models import (
    Friend,
    GroupChat,
    GroupMember,
    GroupMemberRole,
    ImageElement,
    Message,
    OnlineClient,
    PendingRequest,
    RequestKind,
    TextElement,
    UserProfile,
)
from flaza.core.storage import Storage
from flaza.ui.components.forward_dialog import ForwardDialog
from flaza.ui.components.group_manage import GroupManageDialog
from flaza.ui.components.profile_dialog import ProfileDialog
from flaza.ui.components.request_center import RequestCenterDialog
from flaza.ui.pages.settings import SettingsPage
from flaza.ui.state import UiStateStore


async def _noop(*_args: object, **_kwargs: object) -> None:
    return None


async def _noop_group(_group_id: int) -> None:
    return None


class _DummyActions:
    async def respond_request(self, request: PendingRequest, accept: bool) -> None:
        return None

    async def refresh_requests(self) -> None:
        return None

    async def like_friend(self, uid: str) -> int:
        return 1


def test_request_center_builds_rows_for_all_kinds() -> None:
    state = UiStateStore(Storage())
    state.upsert_request(
        PendingRequest(
            key="friend:u_1",
            kind=RequestKind.FRIEND,
            title="u_1 请求添加你为好友",
            subtitle="你好",
            target_uid="u_1",
            timestamp=1,
        )
    )
    state.upsert_request(
        PendingRequest(
            key="group-invite:2",
            kind=RequestKind.GROUP_INVITE,
            title="邀请你加入群聊",
            group_id=2,
            timestamp=2,
        )
    )

    dialog = RequestCenterDialog(state, _DummyActions(), on_changed=_noop, on_error=_noop)  # type: ignore[arg-type]
    element = dialog.dialog.build()
    content = dialog._build_content()

    assert element is not None
    assert len(content.container) == 2


def test_profile_dialog_builds_with_detail_fields() -> None:
    profile = UserProfile(
        uid="u_1",
        uin=10001,
        nickname="小明",
        bio="你好",
        location="四川 成都",
        qid="qid1",
        sex="male",
        age=18,
    )

    dialog = ProfileDialog(
        profile,
        _DummyActions(),  # type: ignore[arg-type]
        on_like_result=_noop,
        on_error=_noop,
    )
    element = dialog.dialog.build()

    assert element is not None


def test_group_manage_dialog_builds_and_gates_member_actions() -> None:
    owner = GroupMember(group_id=1, uid="u_self", uin=10001, nickname="我", role=GroupMemberRole.OWNER)
    member = GroupMember(group_id=1, uid="u_2", uin=10002, nickname="小明", role=GroupMemberRole.MEMBER)
    dialog = GroupManageDialog(
        _DummyActions(),  # type: ignore[arg-type]
        group_id=1,
        group_name="测试群",
        self_uid="u_self",
        self_role=GroupMemberRole.OWNER,
        members=[owner, member],
        friends=[Friend(uid="u_3", uin=10003, nickname="好友")],
        on_message=_noop,
        on_error=_noop,
        on_left=_noop_group,
    )

    element = dialog.dialog.build()
    dialog._select(member, dialog._rows["u_2"])

    assert element is not None
    assert dialog._mute_button.disabled is False
    assert dialog._admin_button.disabled is False
    assert dialog._kick_button.disabled is False
    assert dialog._title_button.disabled is False
    assert "u_3" in dialog._friend_checks


def test_group_manage_dialog_rows_do_not_shrink() -> None:
    owner = GroupMember(group_id=1, uid="u_self", uin=10001, nickname="我", role=GroupMemberRole.OWNER)
    dialog = GroupManageDialog(
        _DummyActions(),  # type: ignore[arg-type]
        group_id=1,
        group_name="测试群",
        self_uid="u_self",
        self_role=GroupMemberRole.OWNER,
        members=[owner],
        friends=[Friend(uid="u_3", uin=10003, nickname="好友")],
        on_message=_noop,
        on_error=_noop,
        on_left=_noop_group,
    )

    content = dialog._content

    assert content.styles.overflow_y == "auto"
    direct_children = [child for child in content.container if isinstance(child, DOMElement)]
    assert direct_children
    assert all(child.styles.flex_shrink == "0" for child in direct_children)


def test_settings_page_builds_profile_and_other_clients() -> None:
    page = SettingsPage(
        _DummyActions(),  # type: ignore[arg-type]
        LoginConfig(),
        WindowSettings(),
        PathsConfig(),
        _noop,
        _noop,
        _noop,
        initial_profile=UserProfile(uid="u_1", uin=10001, nickname="我", bio="你好"),
        initial_other_clients=[OnlineClient(sub_id=1, os_name="Windows", device_name="我的电脑")],
    )

    assert page.root is not None


def test_forward_dialog_builds_transcript_rows() -> None:
    message = Message(
        chat=GroupChat(group_id=1),
        sender_uin=10001,
        sender_uid="u_1",
        sender_name="小明",
        seq=0,
        rand=0,
        timestamp=1700000000,
        elements=[TextElement(text="你好"), ImageElement(url="https://example.com/pic.png")],
    )

    dialog = ForwardDialog([message])
    content = dialog._build_content([message])

    assert dialog.dialog.build() is not None
    assert len(content.container) == 1
