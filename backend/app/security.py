from datetime import datetime, timedelta, timezone
import re
import secrets
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from pwdlib import PasswordHash

from backend.app.config import Settings

password_hash = PasswordHash.recommended()
DUMMY_PASSWORD_HASH = password_hash.hash(secrets.token_urlsafe(32))
bearer_scheme = HTTPBearer(auto_error=False)
JWT_ALGORITHM = "HS256"
JWT_ISSUER = "digital-health-record"


def require_signing_key(settings: Settings) -> str:
    key = settings.jwt_secret_key
    if len(key) < 32 or key == "replace-with-a-random-secret-at-least-32-characters":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured. Set a private JWT_SECRET_KEY of at least 32 characters.",
        )
    return key


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    try:
        return password_hash.verify(password, hashed_password)
    except (ValueError, TypeError):
        return False


def normalize_phone(value: str) -> str:
    return re.sub(r"[\s()-]", "", value)


def create_access_token(patient_id: str, settings: Settings) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": patient_id,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_access_token_minutes),
        "iss": JWT_ISSUER,
    }
    return jwt.encode(payload, require_signing_key(settings), algorithm=JWT_ALGORITHM)


def create_face_challenge_token(patient_id: str, settings: Settings) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": patient_id,
            "type": "face-pending",
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "iss": JWT_ISSUER,
        },
        require_signing_key(settings),
        algorithm=JWT_ALGORITHM,
    )


def get_face_challenge_patient(token: str, settings: Settings) -> str:
    try:
        payload = jwt.decode(
            token,
            require_signing_key(settings),
            algorithms=[JWT_ALGORITHM],
            issuer=JWT_ISSUER,
            options={"require": ["exp", "iat", "iss", "sub", "type"]},
        )
    except InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Face verification session expired. Sign in again.") from exc
    if payload.get("type") != "face-pending" or not isinstance(payload.get("sub"), str):
        raise HTTPException(status_code=401, detail="Invalid face verification session.")
    return payload["sub"]


def create_qr_token(patient_id: str, settings: Settings) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": patient_id,
        "type": "health-id-qr",
        "iat": now,
        "exp": now + timedelta(days=365),
        "iss": JWT_ISSUER,
    }
    return jwt.encode(payload, require_signing_key(settings), algorithm=JWT_ALGORITHM)


def verify_qr_token(token: str, patient_id: str, settings: Settings) -> None:
    try:
        payload = jwt.decode(
            token,
            require_signing_key(settings),
            algorithms=[JWT_ALGORITHM],
            issuer=JWT_ISSUER,
            options={"require": ["exp", "iat", "iss", "sub", "type"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=400, detail="This QR code has expired. Generate a new Health ID QR.") from exc
    except InvalidTokenError as exc:
        raise HTTPException(status_code=400, detail="This QR code is invalid.") from exc

    if payload.get("type") != "health-id-qr" or payload.get("sub") != patient_id:
        raise HTTPException(status_code=400, detail="This QR code does not match the Health ID.")


def get_current_patient(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> str:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Please log in to continue.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = jwt.decode(
            credentials.credentials,
            require_signing_key(request.app.state.settings),
            algorithms=[JWT_ALGORITHM],
            issuer=JWT_ISSUER,
            options={"require": ["exp", "iat", "iss", "sub", "type"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your session has expired. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your session is invalid. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    if payload.get("type") != "access" or not isinstance(payload.get("sub"), str):
        raise HTTPException(status_code=401, detail="Your session is invalid.")
    return payload["sub"]
