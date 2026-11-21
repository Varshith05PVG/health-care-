from datetime import date
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PatientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    age: int = Field(strict=True, ge=0, le=125)
    gender: str = Field(min_length=1, max_length=40)
    blood_group: str = Field(min_length=1, max_length=10)
    language: str = Field(min_length=1, max_length=60)
    phone: str = Field(min_length=8, max_length=16)
    password: str = Field(min_length=12, max_length=128)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        normalized = re.sub(r"[\s()-]", "", value)
        if not re.fullmatch(r"\+?[1-9]\d{7,14}", normalized):
            raise ValueError("Enter a valid phone number with 8 to 15 digits.")
        return normalized

    @field_validator("name", "gender", "blood_group", "language")
    @classmethod
    def trim_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank.")
        return value


class PatientResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: Annotated[str, Field(min_length=1, max_length=40)]
    health_id: str | None = None
    name: str
    age: int
    gender: str
    blood_group: str
    language: str


class PatientSummary(PatientResponse):
    phone: str
    has_passkey: bool = False
    has_face_template: bool = False


class FaceEnrollment(BaseModel):
    descriptor: list[float] = Field(min_length=128, max_length=128)

    @field_validator("descriptor")
    @classmethod
    def validate_descriptor(cls, values: list[float]) -> list[float]:
        import math

        if not all(math.isfinite(value) for value in values):
            raise ValueError("Invalid face scan.")
        return values


class FaceLoginVerification(FaceEnrollment):
    face_token: str = Field(min_length=1, max_length=4096)


class AuthCredentials(BaseModel):
    identifier: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=128)


class PasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identifier: str = Field(min_length=1, max_length=120)

    @field_validator("identifier")
    @classmethod
    def trim_identifier(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Enter your phone number or Health ID.")
        return value


class PasswordResetConfirmation(PasswordResetRequest):
    otp: str = Field(pattern=r"^\d{6}$")
    new_password: str = Field(min_length=12, max_length=128)


class PasswordResetResult(BaseModel):
    message: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    patient: PatientSummary
    face_required: bool = False


class HealthRecordCreate(BaseModel):
    category: Literal["diagnosis", "medication", "allergy", "note"]
    title: str = Field(min_length=1, max_length=120)
    details: str = Field(min_length=1, max_length=3000)
    doctor_name: str = Field(min_length=1, max_length=120)
    doctor_specialization: Literal[
        "General Physician",
        "Cardiologist",
        "Dermatologist",
        "Pediatrician",
        "Gynecologist",
    ]
    recorded_on: str | None = Field(default=None, max_length=10)

    @field_validator("title", "details", "doctor_name")
    @classmethod
    def trim_record_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank.")
        return value

    @field_validator("recorded_on")
    @classmethod
    def validate_recorded_on(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("Enter a valid date in YYYY-MM-DD format.") from exc
        return value


class HealthRecordResponse(BaseModel):
    record_id: str
    category: Literal["diagnosis", "medication", "allergy", "note"]
    title: str
    details: str
    doctor_name: str | None = None
    doctor_specialization: str | None = None
    recorded_on: str


class QRLookupRequest(BaseModel):
    patient_id: str = Field(min_length=1, max_length=40)
    qr_token: str | None = Field(default=None, max_length=4096)


class AIQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=3, max_length=500)
    language: Literal["en", "te", "hi"] = "en"

    @field_validator("question")
    @classmethod
    def trim_question(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("Enter a question of at least 3 characters.")
        return value


class AISource(BaseModel):
    record_id: str
    category: Literal["diagnosis", "medication", "allergy", "note"]
    title: str
    recorded_on: str


class AIAnswer(BaseModel):
    answer: str
    sources: list[AISource]
    language: Literal["en", "te", "hi"]
    translated_question: str | None = None
    disclaimer: str = (
        "This information is based on your recorded health records and is not a medical diagnosis "
        "or a substitute for professional medical advice."
    )
