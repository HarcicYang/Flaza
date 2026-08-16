"""账号与登录相关的领域模型。"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class LoginPhase(StrEnum):
    """登录流程阶段。"""

    IDLE = "idle"
    SILENT_LOGGING_IN = "silent_logging_in"
    QR_READY = "qr_ready"
    WAITING_SCAN = "waiting_scan"
    WAITING_CONFIRM = "waiting_confirm"
    CONFIRMED = "confirmed"
    ONLINE = "online"
    FAILED = "failed"


class ConnectionState(StrEnum):
    """QQ 连接状态。"""

    CONNECTING = "connecting"
    ONLINE = "online"
    RECONNECTING = "reconnecting"
    OFFLINE = "offline"
    KICKED = "kicked"


class SilentLoginResult(StrEnum):
    """静默登录尝试结果。"""

    NO_SESSION = "no_session"
    OK = "ok"
    FAILED = "failed"


class QrCodeState(StrEnum):
    """二维码轮询状态，与 lagrange 的 QrCodeResult 一一对应。"""

    WAITING_FOR_SCAN = "waiting_for_scan"
    WAITING_FOR_CONFIRM = "waiting_for_confirm"
    CONFIRMED = "confirmed"
    EXPIRED = "expired"
    CANCELED = "canceled"


class QrCodeData(BaseModel):
    """待展示的登录二维码。"""

    model_config = ConfigDict(frozen=True)

    image: bytes
    url: str


class SelfInfo(BaseModel):
    """当前登录账号信息。"""

    model_config = ConfigDict(frozen=True)

    uin: int
    uid: str
    nickname: str = ""
