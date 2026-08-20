"""群成员 @ 选择器测试。"""

import asyncio

from flaza.core.models import GroupMember
from flaza.ui.components.member_picker import MemberPicker


def test_filter_preserves_keyboard_active_member() -> None:
    async def scenario() -> None:
        picker = MemberPicker(
            10001,
            [
                GroupMember(group_id=10001, uid="u_1", uin=10001, nickname="Alice"),
                GroupMember(group_id=10001, uid="u_2", uin=10002, nickname="Bob"),
                GroupMember(group_id=10001, uid="u_3", uin=10003, nickname="Carol"),
            ],
        )
        picker.show_above()
        await picker.move_selection(1)
        assert picker._filtered[picker._active_index].uid == "u_2"

        picker.filter("")
        assert picker._filtered[picker._active_index].uid == "u_2"

    asyncio.run(scenario())
