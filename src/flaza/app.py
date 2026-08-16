"""Flaza 桌面应用入口。"""

from neony.application import Page, launch
from neony.application.elements import Heading, Text, VStack


def create_page() -> Page:
    """构建占位主窗口。"""
    return Page(gap="16px").add(
        VStack(
            Heading("Flaza", level=1),
            Text("基于 lagrange-python 与 Neony 的 QQ 桌面客户端。", role="secondary"),
            gap="12px",
        )
    )


def main() -> None:
    """启动 Flaza 桌面应用。"""
    launch(create_page(), title="Flaza", width=480, height=360, devtools=True)
