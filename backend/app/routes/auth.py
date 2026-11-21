import logging
import re
import hmac
import secrets
import base64
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError, PyMongoError

from backend.app.config import Settings, get_request_settings
from backend.app.db import get_patients_collection
from backend.app.schemas import (
    AuthCredentials,
    AuthResponse,
    FaceEnrollment,
    FaceLoginVerification,
    PatientCreate,
    PasswordResetConfirmation,
    PasswordResetRequest,
    PasswordResetResult,
)
from backend.app.security import (
    create_access_token,
    create_face_challenge_token,
    DUMMY_PASSWORD_HASH,
    get_current_patient,
    get_face_challenge_patient,
    hash_password,
    normalize_phone,
    require_signing_key,
    verify_password,
)
from backend.app.services.health_id import next_health_id
from backend.app.services.password_reset import generate_otp, hash_reset_otp, send_development_otp
from backend.app.services.passkeys import server_for, serialize_options

logger = logging.getLogger(__name__)
router = APIRouter(tags=["authentication"])
PHONE_PATTERN = re.compile(r"^\+?[1-9]\d{7,14}$")


def patient_summary(document: dict) -> dict:
    patient_id = patient_identity(document)
    return {
        "patient_id": patient_id,
        "health_id": document.get("health_id") or patient_id,
        "name": document["name"],
        "age": document["age"],
        "gender": document["gender"],
        "blood_group": document.get("blood_group", "Unknown"),
        "language": document.get("language", "English"),
        "phone": document.get("phone", ""),
        "has_passkey": bool(document.get("passkey_credential")),
        "has_face_template": bool(document.get("face_template")),
    }


def patient_identity(document: dict) -> str:
    identity = document.get("patient_id") or document.get("health_id") or document.get("_id")
    return str(identity)


def find_patient_by_identifier(collection: Collection, identifier: str) -> dict | None:
    normalized = normalize_phone(identifier)
    if PHONE_PATTERN.fullmatch(normalized):
        document = collection.find_one({"phone": normalized})
        if document is not None:
            return document
    normalized_health_id = identifier.strip().upper()
    if normalized_health_id.startswith("HI-"):
        document = collection.find_one({"health_id": normalized_health_id})
        if document is not None:
            return document
    return collection.find_one({"patient_id": normalized_health_id})


def auth_response(document: dict, settings: Settings) -> dict:
    return {
        "access_token": create_access_token(patient_identity(document), settings),
        "token_type": "bearer",
        "patient": patient_summary(document),
    }


@router.post("/api/auth/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
@router.post("/api/patients", response_model=AuthResponse, status_code=status.HTTP_201_CREATED, include_in_schema=False)
def register_patient(
    patient: PatientCreate,
    request: Request,
    collection: Collection = Depends(get_patients_collection),
    settings: Settings = Depends(get_request_settings),
) -> dict:
    require_signing_key(settings)
    document = patient.model_dump(exclude={"password"})
    document["patient_id"] = f"MW{uuid4().hex.upper()}"
    document["qr_path"] = f"/patient/{document['patient_id']}"
    document["password_hash"] = hash_password(patient.password)

    try:
        document["health_id"] = next_health_id(collection, request.app.state.health_id_counters)
        collection.insert_one(document)
    except DuplicateKeyError as exc:
        logger.info("Patient registration rejected because the phone number is already registered.")
        raise HTTPException(status_code=409, detail="A patient account with this phone number already exists.") from exc
    except PyMongoError as exc:
        logger.exception("MongoDB failed while registering a patient.")
        raise HTTPException(status_code=503, detail="Patient storage is currently unavailable.") from exc

    return auth_response(document, settings)


@router.post("/api/auth/login", response_model=AuthResponse)
def login(
    credentials: AuthCredentials,
    collection: Collection = Depends(get_patients_collection),
    settings: Settings = Depends(get_request_settings),
) -> dict:
    identifier = credentials.identifier.strip()

    try:
        document = find_patient_by_identifier(collection, identifier)
    except PyMongoError as exc:
        logger.exception("MongoDB failed while authenticating a patient.")
        raise HTTPException(status_code=503, detail="Patient storage is currently unavailable.") from exc

    stored_hash = document.get("password_hash") if document else None
    if not isinstance(stored_hash, str) or not stored_hash.startswith("$argon2"):
        stored_hash = DUMMY_PASSWORD_HASH
    password_matches = verify_password(credentials.password, stored_hash)
    if document is None or not password_matches:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="The Health ID/phone number or password is incorrect.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if document.get("face_template"):
        return {
            "access_token": create_face_challenge_token(patient_identity(document), settings),
            "token_type": "bearer",
            "patient": patient_summary(document),
            "face_required": True,
        }
    return auth_response(document, settings)


@router.post("/api/auth/face/enroll")
def enroll_face(
    payload: FaceEnrollment,
    patient_id: str = Depends(get_current_patient),
    collection: Collection = Depends(get_patients_collection),
) -> dict:
    try:
        result = collection.update_one(
            {"patient_id": patient_id},
            {"$set": {"face_template": payload.descriptor}},
        )
    except PyMongoError as exc:
        logger.exception("MongoDB failed while storing face verification data.")
        raise HTTPException(status_code=503, detail="Patient storage is currently unavailable.") from exc
    if result.matched_count != 1:
        raise HTTPException(status_code=401, detail="This patient account no longer exists.")
    return {"message": "Camera face verification is set up."}


@router.post("/api/auth/face/verify", response_model=AuthResponse)
def verify_face(
    payload: FaceLoginVerification,
    collection: Collection = Depends(get_patients_collection),
    settings: Settings = Depends(get_request_settings),
) -> dict:
    patient_id = get_face_challenge_patient(payload.face_token, settings)
    try:
        document = collection.find_one({"patient_id": patient_id})
    except PyMongoError as exc:
        logger.exception("MongoDB failed while verifying face data.")
        raise HTTPException(status_code=503, detail="Patient storage is currently unavailable.") from exc
    stored = document.get("face_template") if document else None
    if not isinstance(stored, list) or len(stored) != 128:
        raise HTTPException(status_code=401, detail="Face verification is not configured for this account.")
    distance = sum((left - right) ** 2 for left, right in zip(stored, payload.descriptor)) ** 0.5
    if distance > 0.55:
        raise HTTPException(status_code=401, detail="Face did not match. Please try again.")
    return auth_response(document, settings)


@router.post("/api/auth/passkey/register/options")
def passkey_register_options(
    request: Request,
    patient_id: str = Depends(get_current_patient),
    collection: Collection = Depends(get_patients_collection),
    settings: Settings = Depends(get_request_settings),
) -> dict:
    document = collection.find_one({"patient_id": patient_id})
    if document is None:
        raise HTTPException(status_code=401, detail="This patient account no longer exists.")
    origin = (request.headers.get("origin") or settings.frontend_base_url).rstrip("/")
    server = server_for(origin)
    user = {
        "id": patient_id.encode(),
        "name": document.get("phone", patient_id),
        "display_name": document["name"],
    }
    from fido2.webauthn import PublicKeyCredentialUserEntity
    options, state = server.register_begin(
        PublicKeyCredentialUserEntity(**user),
        user_verification="required",
        authenticator_attachment="platform",
    )
    collection.update_one({"patient_id": patient_id}, {"$set": {"passkey_registration_state": state}})
    return serialize_options(options)


@router.post("/api/auth/passkey/register")
def passkey_register(
    payload: dict,
    request: Request,
    patient_id: str = Depends(get_current_patient),
    collection: Collection = Depends(get_patients_collection),
    settings: Settings = Depends(get_request_settings),
) -> dict:
    document = collection.find_one({"patient_id": patient_id})
    state = document.get("passkey_registration_state") if document else None
    if not document or not isinstance(state, dict):
        raise HTTPException(status_code=400, detail="Start Face ID setup again.")
    try:
        origin = (request.headers.get("origin") or settings.frontend_base_url).rstrip("/")
        auth_data = server_for(origin).register_complete(state, response=payload)
        credential_data = auth_data.credential_data
        collection.update_one(
            {"patient_id": patient_id},
            {"$set": {"passkey_credential": base64.urlsafe_b64encode(bytes(credential_data)).decode()},
             "$unset": {"passkey_registration_state": ""}},
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Face ID setup could not be verified.") from exc
    return {"message": "Face ID is ready for this account."}


@router.post("/api/auth/passkey/login/options")
def passkey_login_options(
    credentials: AuthCredentials,
    request: Request,
    collection: Collection = Depends(get_patients_collection),
    settings: Settings = Depends(get_request_settings),
) -> dict:
    document = find_patient_by_identifier(collection, credentials.identifier.strip())
    stored_hash = document.get("password_hash") if document else None
    if not isinstance(stored_hash, str) or not verify_password(credentials.password, stored_hash):
        raise HTTPException(status_code=401, detail="The Health ID/phone number or password is incorrect.")
    credential_blob = document.get("passkey_credential")
    if not isinstance(credential_blob, str):
        raise HTTPException(status_code=400, detail="Face ID has not been set up for this account.")
    from fido2.webauthn import AttestedCredentialData
    credential, _ = AttestedCredentialData.unpack_from(base64.urlsafe_b64decode(credential_blob))
    origin = (request.headers.get("origin") or settings.frontend_base_url).rstrip("/")
    options, state = server_for(origin).authenticate_begin(
        [credential],
        user_verification="required",
    )
    collection.update_one(
        {"patient_id": patient_identity(document)},
        {"$set": {"passkey_login_state": state}},
    )
    return serialize_options(options)


@router.post("/api/auth/passkey/login", response_model=AuthResponse)
def passkey_login(
    payload: dict,
    request: Request,
    collection: Collection = Depends(get_patients_collection),
    settings: Settings = Depends(get_request_settings),
) -> dict:
    identifier = payload.get("identifier")
    response = payload.get("response")
    document = find_patient_by_identifier(collection, identifier) if isinstance(identifier, str) else None
    state = document.get("passkey_login_state") if document else None
    credential_blob = document.get("passkey_credential") if document else None
    if not document or not isinstance(state, dict) or not isinstance(credential_blob, str) or not isinstance(response, dict):
        raise HTTPException(status_code=401, detail="Face ID verification could not be started.")
    from fido2.webauthn import AttestedCredentialData
    credential, _ = AttestedCredentialData.unpack_from(base64.urlsafe_b64decode(credential_blob))
    try:
        origin = (request.headers.get("origin") or settings.frontend_base_url).rstrip("/")
        server_for(origin).authenticate_complete(
            state,
            [credential],
            response=response,
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=401, detail="Face ID verification failed.") from exc
    collection.update_one({"patient_id": patient_identity(document)}, {"$unset": {"passkey_login_state": ""}})
    return auth_response(document, settings)


RESET_REQUEST_MESSAGE = (
    "If an account matches that phone number or Health ID, password-reset instructions "
    "will be sent to its registered phone number when reset delivery is enabled."
)
RESET_FAILURE_MESSAGE = "The reset code is invalid or expired. Request a new code and try again."


@router.post("/api/auth/forgot-password", response_model=PasswordResetResult, status_code=202)
def request_password_reset(
    payload: PasswordResetRequest,
    collection: Collection = Depends(get_patients_collection),
    settings: Settings = Depends(get_request_settings),
) -> dict:
    if settings.password_reset_mode != "development":
        return {"message": RESET_REQUEST_MESSAGE}

    try:
        document = find_patient_by_identifier(collection, payload.identifier)
        phone = document.get("phone") if document else None
        if document is not None and isinstance(phone, str) and phone:
            otp = generate_otp()
            now = datetime.now(timezone.utc)
            identity = patient_identity(document)
            collection.update_one(
                {"_id": document["_id"]} if "_id" in document else {"patient_id": identity},
                {
                    "$set": {
                        "password_reset_otp_hash": hash_reset_otp(identity, otp, settings),
                        "password_reset_otp_expires_at": now
                        + timedelta(minutes=settings.password_reset_otp_minutes),
                        "password_reset_otp_attempts": 0,
                    }
                },
            )
            send_development_otp(phone, otp, settings)
    except PyMongoError as exc:
        logger.exception("MongoDB failed while requesting a password reset.")
        raise HTTPException(status_code=503, detail="Patient storage is currently unavailable.") from exc

    return {"message": RESET_REQUEST_MESSAGE}


@router.post("/api/auth/reset-password", response_model=PasswordResetResult)
def reset_password(
    payload: PasswordResetConfirmation,
    collection: Collection = Depends(get_patients_collection),
    settings: Settings = Depends(get_request_settings),
) -> dict:
    if settings.password_reset_mode != "development":
        raise HTTPException(status_code=400, detail=RESET_FAILURE_MESSAGE)
    now = datetime.now(timezone.utc)
    try:
        document = find_patient_by_identifier(collection, payload.identifier)
        if document is not None:
            identity = patient_identity(document)
            expected_hash = hash_reset_otp(identity, payload.otp, settings)
            stored_otp_hash = document.get("password_reset_otp_hash")
            expires_at = document.get("password_reset_otp_expires_at")
            if isinstance(expires_at, datetime) and expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            attempts = document.get("password_reset_otp_attempts", 0)
            otp_matches = (
                isinstance(stored_otp_hash, str)
                and hmac.compare_digest(stored_otp_hash, expected_hash)
                and expires_at is not None
                and expires_at > now
                and isinstance(attempts, int)
                and attempts < settings.password_reset_max_attempts
            )
            patient_filter = (
                {"_id": document["_id"]}
                if "_id" in document
                else {"patient_id": identity}
            )
            if otp_matches:
                updated = collection.update_one(
                    {
                        **patient_filter,
                        "password_reset_otp_hash": expected_hash,
                        "password_reset_otp_expires_at": {"$gt": now},
                        "password_reset_otp_attempts": {
                            "$lt": settings.password_reset_max_attempts
                        },
                    },
                    {
                        "$set": {"password_hash": hash_password(payload.new_password)},
                        "$unset": {
                            "password_reset_otp_hash": "",
                            "password_reset_otp_expires_at": "",
                            "password_reset_otp_attempts": "",
                        },
                    },
                )
                if updated.modified_count == 1:
                    return {"message": "Your password has been reset. You can now sign in."}

            reset_filter = {
                "_id": document["_id"],
                "password_reset_otp_expires_at": {"$gt": now},
                "password_reset_otp_attempts": {"$lt": settings.password_reset_max_attempts},
            } if "_id" in document else {
                "patient_id": identity,
                "password_reset_otp_expires_at": {"$gt": now},
                "password_reset_otp_attempts": {"$lt": settings.password_reset_max_attempts},
            }
            collection.update_one(
                reset_filter,
                {"$inc": {"password_reset_otp_attempts": 1}},
            )
        else:
            hmac.compare_digest(
                hash_reset_otp("unknown-patient", payload.otp, settings),
                secrets.token_hex(32),
            )
    except PyMongoError as exc:
        logger.exception("MongoDB failed while resetting a patient password.")
        raise HTTPException(status_code=503, detail="Patient storage is currently unavailable.") from exc

    raise HTTPException(status_code=400, detail=RESET_FAILURE_MESSAGE)


@router.get("/api/auth/me")
def current_account(
    patient_id: str = Depends(get_current_patient),
    collection: Collection = Depends(get_patients_collection),
) -> dict:
    try:
        document = collection.find_one(
            {"$or": [{"patient_id": patient_id}, {"health_id": patient_id}]}
        )
    except PyMongoError as exc:
        logger.exception("MongoDB failed while retrieving the current patient account.")
        raise HTTPException(status_code=503, detail="Patient storage is currently unavailable.") from exc

    if document is None:
        raise HTTPException(status_code=401, detail="This patient account no longer exists.")
    return patient_summary(document)
