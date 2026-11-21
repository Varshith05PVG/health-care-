import base64
from collections.abc import Mapping
from enum import Enum
from urllib.parse import urlparse

from fido2.server import Fido2Server
from fido2.webauthn import PublicKeyCredentialRpEntity


def _encode(value):
    if isinstance(value, bytes):
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {key: _encode(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return {key: _encode(getattr(value, key)) for key in value.__dataclass_fields__}
    return value


def server_for(origin: str) -> Fido2Server:
    parsed = urlparse(origin)
    hostname = parsed.hostname or "localhost"
    if hostname in {"127.0.0.1", "::1"}:
        hostname = "localhost"
    return Fido2Server(
        PublicKeyCredentialRpEntity(
            id=hostname,
            name="CareRecord",
        )
    )


def serialize_options(options) -> dict:
    return _encode(options)
