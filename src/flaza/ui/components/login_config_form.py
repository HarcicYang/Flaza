"""登录配置表单。"""

from __future__ import annotations

from typing import Literal, cast

from neony.application.elements import Input, Select, Text, VStack

from flaza.config import LoginConfig


class LoginConfigForm:
    """可复用的登录配置表单，供首次配置页和设置对话框使用。"""

    def __init__(self, initial: LoginConfig) -> None:
        self._uin_input = Input(value=str(initial.uin or ""))
        self._protocol_select = Select(
            "协议",
            options=[("linux", "linux"), ("macos", "macos"), ("windows", "windows"), ("custom", "custom")],
            value="custom" if initial.use_custom else initial.protocol,
        )
        self._signer_url_input = Input(value=initial.signer_url, placeholder="https://sign.example.com")
        self._signer_token_input = Input(value=initial.signer_token, type="password")
        self._appinfo_input = Input(value=initial.appinfo_path)
        self._error = Text("", role="danger")

        self.root = VStack(
            Text("uin"),
            self._uin_input,
            self._protocol_select,
            Text("签名服务地址"),
            self._signer_url_input,
            Text("签名服务 token"),
            self._signer_token_input,
            Text("appinfo 路径（custom 协议）"),
            self._appinfo_input,
            self._error,
            gap="12px",
            align="stretch",
        ).build()

    def values(self) -> LoginConfig:
        protocol = cast(
            Literal["linux", "macos", "windows", "custom"],
            self._protocol_select.value or "linux",
        )
        try:
            uin = int(self._uin_input.value or 0)
        except ValueError as exc:
            raise ValueError("uin 必须是数字") from exc

        return LoginConfig(
            uin=uin,
            protocol=protocol,
            signer_url=self._signer_url_input.value.strip(),
            signer_token=self._signer_token_input.value.strip(),
            use_custom=protocol == "custom",
            appinfo_path=self._appinfo_input.value.strip() or "./appinfo.json",
        )

    def set_error(self, message: str) -> None:
        self._error.text = message
