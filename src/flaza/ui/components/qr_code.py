"""二维码展示组件。"""

from __future__ import annotations

import base64

from neony.dom import Color, Computed, Div, Img, Styles

from flaza.ui.state import UiStateStore


class QrCodeView:
    """把 UiStateStore.qr_image 的 bytes 展示为内嵌 PNG。"""

    def __init__(self, state: UiStateStore) -> None:
        qr_src = Computed(lambda: _to_data_url(state.qr_image()))
        image = Img(
            alt="登录二维码",
            styles=Styles(width="100%", height="100%", object_fit="contain", display="block"),
        )
        image.bind_attr(qr_src, "src")
        self.root = Div(
            styles=Styles(
                width="220px",
                height="220px",
                padding="8px",
                border_radius="12px",
                background_color=Color(name="white"),
                overflow="hidden",
            ),
            container=[image],
        )
        self.root.bind_visible(state.qr_image)


def _to_data_url(image: bytes | None) -> str | None:
    if image is None:
        return None
    encoded = base64.b64encode(image).decode("ascii")
    return f"data:image/png;base64,{encoded}"
