import hashlib
import hmac
import logging
import secrets

from backend.app.config import Settings
from backend.app.security import require_signing_key

logger = logging.getLogger(__name__)


def generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_reset_otp(patient_id: str, otp: str, settings: Settings) -> str:
    message = f"password-reset:{patient_id}:{otp}".encode("utf-8")
    return hmac.new(
        require_signing_key(settings).encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()


def send_development_otp(phone: str, otp: str, settings: Settings) -> None:
    if settings.password_reset_mode != "development":
        raise RuntimeError("Development OTP delivery is not enabled.")
    logger.warning(
        "DEVELOPMENT ONLY password-reset OTP for registered phone ending %s: %s",
        phone[-4:],
        otp,
    )
