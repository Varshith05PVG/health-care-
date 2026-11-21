import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import re
import secrets
from types import SimpleNamespace

import httpx
import jwt
from fastapi.testclient import TestClient
from pymongo.errors import DuplicateKeyError, ServerSelectionTimeoutError

from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.security import JWT_ALGORITHM, JWT_ISSUER
from backend.app.services.ai_provider import OllamaModelUnavailable, OllamaProvider, OllamaUnavailable
from backend.app.services.retrieval import build_record_context, validate_extractive_answer
from backend.app.services.translation_service import BhashiniUnavailable, TranslationService


class InMemoryCursor(list):
    def sort(self, key: str, direction: int = 1) -> "InMemoryCursor":
        super().sort(key=lambda record: record.get(key, ""), reverse=direction < 0)
        return self


class InMemoryCollection:
    def __init__(self) -> None:
        self.documents: list[dict] = []

    def create_index(self, *args, **kwargs) -> str:
        return "test_index"

    def insert_one(self, document: dict) -> None:
        unique_keys = ("patient_id", "health_id", "phone", "record_id")
        if any(
            key in document and any(existing.get(key) == document[key] for existing in self.documents)
            for key in unique_keys
        ):
            raise DuplicateKeyError("duplicate unique key")
        self.documents.append(document.copy())

    def find_one(self, query: dict, projection: dict | None = None) -> dict | None:
        found = next((item for item in self.documents if self._matches(item, query)), None)
        if found is None:
            return None
        result = found.copy()
        if projection:
            included = {key for key, include in projection.items() if include}
            if included:
                result = {key: value for key, value in result.items() if key in included}
            for key, include in projection.items():
                if include == 0:
                    result.pop(key, None)
        return result

    def find(self, query: dict, projection: dict | None = None) -> InMemoryCursor:
        found = (item.copy() for item in self.documents if self._matches(item, query))
        if not projection:
            return InMemoryCursor(found)
        included = {key for key, value in projection.items() if value}
        return InMemoryCursor(
            {key: value for key, value in item.items() if key in included or key == "_id"}
            for item in found
        )

    def find_one_and_update(
        self,
        query: dict,
        update: dict,
        upsert: bool = False,
        return_document=None,
    ) -> dict | None:
        document = next((item for item in self.documents if self._matches(item, query)), None)
        if document is None:
            if not upsert:
                return None
            document = {key: value for key, value in query.items() if not key.startswith("$")}
            self.documents.append(document)
        self._apply_update(document, update)
        return document.copy()

    def update_one(self, query: dict, update: dict):
        document = next((item for item in self.documents if self._matches(item, query)), None)
        if document is None:
            return SimpleNamespace(matched_count=0, modified_count=0)
        self._apply_update(document, update)
        return SimpleNamespace(matched_count=1, modified_count=1)

    @staticmethod
    def _apply_update(document: dict, update: dict) -> None:
        for key, value in update.get("$set", {}).items():
            document[key] = value
        for key in update.get("$unset", {}):
            document.pop(key, None)
        for key, value in update.get("$inc", {}).items():
            document[key] = document.get(key, 0) + value
        for key, value in update.get("$max", {}).items():
            document[key] = max(document.get(key, value), value)

    @staticmethod
    def _matches(document: dict, query: dict) -> bool:
        if "$or" in query:
            if not any(InMemoryCollection._matches(document, clause) for clause in query["$or"]):
                return False
        for key, expected in query.items():
            if key == "$or":
                continue
            actual = document.get(key)
            if isinstance(expected, dict):
                for operator, value in expected.items():
                    if operator == "$gt" and not (actual is not None and actual > value):
                        return False
                    if operator == "$lt" and not (actual is not None and actual < value):
                        return False
                    if operator == "$regex" and not (
                        isinstance(actual, str) and re.search(value, actual)
                    ):
                        return False
                    if operator == "$type" and value == "string" and not isinstance(actual, str):
                        return False
            elif actual != expected:
                return False
        return True


class FakeAIProvider:
    def __init__(self) -> None:
        self.context = ""
        self.translations: list[tuple[str, str]] = []
        self.interpretations: list[tuple[str, str, str]] = []

    async def health(self) -> tuple[bool, bool]:
        return True, True

    async def ensure_model_available(self) -> None:
        return None

    async def ensure_translation_model_available(self) -> None:
        return None

    async def answer(self, question: str, context: str) -> str:
        self.context = context
        excerpt = json.loads(context)[0]
        return json.dumps(
            {"selections": [{"record_id": excerpt["record_id"], "quote": excerpt["details"]}]}
        )

    async def translate(self, text: str, source_language: str, target_language: str) -> str:
        self.interpretations.append((text, source_language, target_language))
        return f"{target_language}:{text}"


class LocalTranslationAIProvider(FakeAIProvider):
    async def translate(self, text: str, source_language: str, target_language: str) -> str:
        self.interpretations.append((text, source_language, target_language))
        if target_language == "en":
            return "What medicines are recorded?"
        return f"{target_language}:{text}"


class FakeTranslationService:
    bhashini_configured = True
    google_configured = False
    configured = True

    def __init__(self, translations: list[tuple[str, str]]) -> None:
        self.translations = translations

    async def check_bhashini(self) -> bool:
        return True

    async def check_google(self) -> bool:
        return False

    async def translate(self, text: str, source: str, target: str) -> str:
        if source == target:
            return text
        self.translations.append((text, target))
        if target == "en":
            return "What medicines are recorded?"
        return "మందుల వివరాలు రికార్డుల్లో ఉన్నాయి."


class UnavailableTranslationService(FakeTranslationService):
    bhashini_configured = False
    configured = False

    async def check_bhashini(self) -> bool:
        return False

    async def check_google(self) -> bool:
        return False

    async def translate(self, text: str, source: str, target: str) -> str:
        if source == target:
            return text
        raise BhashiniUnavailable("Bhashini is not configured.")


class OllamaUnavailableProvider(FakeAIProvider):
    async def health(self) -> tuple[bool, bool]:
        return False, False

    async def ensure_model_available(self) -> None:
        raise OllamaUnavailable("test-only Ollama outage")


class OllamaModelMissingProvider(FakeAIProvider):
    async def health(self) -> tuple[bool, bool]:
        return True, False

    async def ensure_model_available(self) -> None:
        raise OllamaModelUnavailable("test-only missing model")


class OllamaTranslationModelMissingProvider(FakeAIProvider):
    async def ensure_translation_model_available(self) -> None:
        raise OllamaModelUnavailable("test-only missing translation model")


class BrokenAIProvider(FakeAIProvider):
    async def answer(self, question: str, context: str) -> str:
        raise httpx.ConnectError("test-only unavailable model")


class InventingAIProvider(FakeAIProvider):
    async def answer(self, question: str, context: str) -> str:
        excerpt = json.loads(context)[0]
        return json.dumps(
            {
                "selections": [
                    {"record_id": excerpt["record_id"], "quote": "Unrecorded diagnosis invented by model."}
                ]
            }
        )


class BrokenCollection(InMemoryCollection):
    def find_one(self, query: dict, projection: dict | None = None) -> dict | None:
        raise ServerSelectionTimeoutError("test-only MongoDB outage")


@contextmanager
def make_client(
    password_reset_mode: str = "disabled",
    translation_service: object | None = None,
    ai_provider: FakeAIProvider | None = None,
) -> Iterator[tuple[TestClient, InMemoryCollection, InMemoryCollection, FakeAIProvider]]:
    patients = InMemoryCollection()
    records = InMemoryCollection()
    counters = InMemoryCollection()
    provider = ai_provider or FakeAIProvider()
    translation_service = translation_service or FakeTranslationService(provider.translations)
    settings = Settings(
        frontend_base_url="http://localhost:5173",
        jwt_secret_key=secrets.token_urlsafe(48),
        password_reset_mode=password_reset_mode,
    )
    with TestClient(
        create_app(
            settings=settings,
            patients_collection=patients,
            health_records_collection=records,
            ai_provider=provider,
            health_id_counter_collection=counters,
            translation_service=translation_service,
        )
    ) as client:
        yield client, patients, records, provider


def registration_payload(**overrides) -> dict:
    return {
        "name": "Maya Rao",
        "age": 31,
        "gender": "Female",
        "blood_group": "O+",
        "language": "Marathi",
        "phone": "+919876543210",
        "password": "correct horse battery staple",
        **overrides,
    }


def register(client: TestClient, **overrides) -> dict:
    response = client.post("/api/auth/register", json=registration_payload(**overrides))
    assert response.status_code == 201
    return response.json()


def bearer(auth: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth['access_token']}"}


def test_registration_login_by_phone_or_health_id_and_password_hashing() -> None:
    with make_client() as (client, patients, _, _):
        created = register(client)
        patient_id = created["patient"]["patient_id"]
        stored = patients.find_one({"patient_id": patient_id})

        assert created["patient"]["name"] == "Maya Rao"
        assert created["patient"]["health_id"] == "HI-P01V01G"
        assert stored["password_hash"] != registration_payload()["password"]
        assert stored["health_id"] == "HI-P01V01G"
        assert stored["qr_path"] == f"/patient/{patient_id}"
        assert "password_hash" not in created["patient"]
        assert client.get("/api/patients/me", headers=bearer(created)).status_code == 200

        phone_login = client.post(
            "/api/auth/login",
            json={"identifier": "+919876543210", "password": registration_payload()["password"]},
        )
        id_login = client.post(
            "/api/auth/login",
            json={"identifier": patient_id.lower(), "password": registration_payload()["password"]},
        )
        assert phone_login.status_code == 200
        assert id_login.status_code == 200
        health_id_login = client.post(
            "/api/auth/login",
            json={"identifier": "hi-p01v01g", "password": registration_payload()["password"]},
        )
        assert health_id_login.status_code == 200
        assert health_id_login.json()["patient"]["health_id"] == "HI-P01V01G"


def test_new_patients_receive_incrementing_health_ids() -> None:
    with make_client() as (client, _, _, _):
        first = register(client, phone="+919876543210")
        second = register(client, phone="+919876543211")

        assert first["patient"]["health_id"] == "HI-P01V01G"
        assert second["patient"]["health_id"] == "HI-P02V02G"


def test_existing_patient_fields_authenticate_with_health_id_and_remain_intact() -> None:
    from backend.app.security import hash_password

    with make_client() as (client, patients, _, _):
        patients.documents.append(
            {
                "_id": "legacy-document-id",
                "name": "Legacy Patient",
                "age": 42,
                "gender": "Female",
                "phone": "+919876543210",
                "health_id": "HI-P03V03G",
                "qr_path": "/existing/health-id.png",
                "password_hash": hash_password("existing password phrase"),
            }
        )
        response = client.post(
            "/api/auth/login",
            json={"identifier": "HI-P03V03G", "password": "existing password phrase"},
        )

        assert response.status_code == 200
        assert response.json()["patient"]["health_id"] == "HI-P03V03G"
        stored = patients.find_one({"health_id": "HI-P03V03G"})
        assert stored["_id"] == "legacy-document-id"
        assert stored["qr_path"] == "/existing/health-id.png"


def test_duplicate_phone_invalid_input_and_bad_login_are_rejected() -> None:
    with make_client() as (client, _, _, _):
        register(client)
        duplicate = client.post("/api/auth/register", json=registration_payload(name="Second account"))
        assert duplicate.status_code == 409

        invalid = client.post(
            "/api/auth/register",
            json=registration_payload(phone="not-a-phone", age=250),
        )
        assert invalid.status_code == 422
        assert client.post(
            "/api/auth/login",
            json={"identifier": "+919876543210", "password": "not-the-password"},
        ).status_code == 401
        assert client.post("/api/auth/login", json={"identifier": "missing", "password": "no"}).status_code == 401


def test_password_reset_uses_registered_phone_and_changes_password(caplog) -> None:
    with make_client(password_reset_mode="development") as (client, patients, _, _):
        account = register(client, phone="+919876543210")
        reset_request = client.post(
            "/api/auth/forgot-password",
            json={"identifier": account["patient"]["health_id"]},
        )
        code_match = re.search(r"OTP .*: (\d{6})$", caplog.text, re.MULTILINE)

        assert reset_request.status_code == 202
        assert "if an account matches" in reset_request.json()["message"].lower()
        assert code_match is not None
        assert code_match.group(1) not in reset_request.text
        patient = patients.find_one({"health_id": account["patient"]["health_id"]})
        assert patient["phone"] == "+919876543210"
        assert patient["password_reset_otp_hash"] != code_match.group(1)

        reset = client.post(
            "/api/auth/reset-password",
            json={
                "identifier": account["patient"]["health_id"],
                "otp": code_match.group(1),
                "new_password": "replacement password phrase",
            },
        )
        assert reset.status_code == 200
        assert "reset" in reset.json()["message"].lower()
        patient = patients.find_one({"health_id": account["patient"]["health_id"]})
        assert "password_reset_otp_hash" not in patient
        assert client.post(
            "/api/auth/login",
            json={"identifier": account["patient"]["health_id"], "password": "replacement password phrase"},
        ).status_code == 200
        assert client.post(
            "/api/auth/login",
            json={"identifier": account["patient"]["health_id"], "password": registration_payload()["password"]},
        ).status_code == 401


def test_password_reset_has_generic_responses_and_limited_otp_attempts(caplog) -> None:
    with make_client(password_reset_mode="development") as (client, patients, _, _):
        account = register(client)
        valid_patient_response = client.post(
            "/api/auth/forgot-password",
            json={"identifier": account["patient"]["health_id"]},
        )
        valid_message = valid_patient_response.json()["message"]
        missing_patient_response = client.post(
            "/api/auth/forgot-password",
            json={"identifier": "HI-P99V99G"},
        )
        assert missing_patient_response.json()["message"] == valid_message
        assert "HI-P99V99G" not in missing_patient_response.text

        for _ in range(5):
            failed = client.post(
                "/api/auth/reset-password",
                json={
                    "identifier": account["patient"]["health_id"],
                    "otp": "000000",
                    "new_password": "replacement password phrase",
                },
            )
            assert failed.status_code == 400
            assert failed.json()["detail"] == "The reset code is invalid or expired. Request a new code and try again."
        patient = patients.find_one({"health_id": account["patient"]["health_id"]})
        assert patient["password_reset_otp_attempts"] == 5


def test_password_reset_is_disabled_outside_development_mode() -> None:
    with make_client() as (client, patients, _, _):
        account = register(client)
        response = client.post(
            "/api/auth/reset-password",
            json={
                "identifier": account["patient"]["health_id"],
                "otp": "123456",
                "new_password": "replacement password phrase",
            },
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "The reset code is invalid or expired. Request a new code and try again."
        assert patients.find_one({"health_id": account["patient"]["health_id"]})["password_hash"]


def test_protected_patient_access_and_qr_lookup_are_owner_scoped() -> None:
    with make_client() as (client, _, _, _):
        assert client.get("/api/patients/me").status_code == 401
        first = register(client, phone="+919876543210")
        second = register(client, name="Arun Das", phone="+919876543211")
        first_id = first["patient"]["patient_id"]
        second_id = second["patient"]["patient_id"]

        assert client.get(f"/api/patients/{first_id}").status_code == 401
        assert client.get(f"/api/patients/{second_id}", headers=bearer(first)).status_code == 403
        assert client.post(
            "/api/qr/lookup",
            headers=bearer(first),
            json={"patient_id": second_id},
        ).status_code == 403

        qr_response = client.get("/api/patients/me/qr", headers=bearer(first))
        assert qr_response.status_code == 200
        assert qr_response.headers["content-type"] == "image/png"
        assert qr_response.content.startswith(b"\x89PNG\r\n\x1a\n")

        own_record = client.post(
            "/api/qr/lookup",
            headers=bearer(first),
            json={"patient_id": first_id},
        )
        assert own_record.status_code == 200
        assert own_record.json()["patient_id"] == first_id


def test_invalid_expired_and_mismatched_tokens_are_rejected() -> None:
    with make_client() as (client, _, _, _):
        account = register(client)
        patient_id = account["patient"]["patient_id"]
        settings = client.app.state.settings
        expired = jwt.encode(
            {
                "sub": patient_id,
                "type": "health-id-qr",
                "iat": datetime.now(timezone.utc) - timedelta(days=2),
                "exp": datetime.now(timezone.utc) - timedelta(days=1),
                "iss": JWT_ISSUER,
            },
            settings.jwt_secret_key,
            algorithm=JWT_ALGORITHM,
        )
        expired_response = client.post(
            "/api/qr/lookup",
            headers=bearer(account),
            json={"patient_id": patient_id, "qr_token": expired},
        )
        assert expired_response.status_code == 400
        assert expired_response.json()["detail"] == "This QR code has expired. Generate a new Health ID QR."

        invalid = client.post(
            "/api/qr/lookup",
            headers=bearer(account),
            json={"patient_id": patient_id, "qr_token": "not-a-valid-token"},
        )
        assert invalid.status_code == 400


def test_health_record_crud_and_cross_patient_isolation() -> None:
    with make_client() as (client, _, records, _):
        first = register(client, phone="+919876543210")
        second = register(client, phone="+919876543211")
        payload = {
            "category": "diagnosis",
            "title": "Seasonal allergy",
            "details": "A clinician recorded seasonal allergic rhinitis.",
            "doctor_name": "Dr. Ananya Rao",
            "doctor_specialization": "General Physician",
        }
        saved = client.post("/api/records", headers=bearer(first), json=payload)
        assert saved.status_code == 201
        assert "patient_id" not in saved.json()
        assert saved.json()["doctor_name"] == "Dr. Ananya Rao"
        assert saved.json()["doctor_specialization"] == "General Physician"
        assert len(records.documents) == 1
        assert records.documents[0]["doctor_name"] == "Dr. Ananya Rao"
        assert records.documents[0]["doctor_specialization"] == "General Physician"

        first_records = client.get("/api/records", headers=bearer(first))
        second_records = client.get("/api/records", headers=bearer(second))
        assert len(first_records.json()) == 1
        assert second_records.json() == []
        assert client.get("/api/records").status_code == 401


def test_camera_face_check_is_required_after_password_login() -> None:
    with make_client() as (client, _, _, _):
        account = register(client)
        descriptor = [0.0] * 128
        enrolled = client.post(
            "/api/auth/face/enroll",
            headers=bearer(account),
            json={"descriptor": descriptor},
        )
        assert enrolled.status_code == 200

        password_login = client.post(
            "/api/auth/login",
            json={"identifier": "+919876543210", "password": registration_payload()["password"]},
        )
        assert password_login.status_code == 200
        challenge = password_login.json()
        assert challenge["face_required"] is True

        rejected = client.post(
            "/api/auth/face/verify",
            json={"face_token": challenge["access_token"], "descriptor": [1.0] + descriptor[1:]},
        )
        assert rejected.status_code == 401

        verified = client.post(
            "/api/auth/face/verify",
            json={"face_token": challenge["access_token"], "descriptor": descriptor},
        )
        assert verified.status_code == 200
        assert verified.json()["face_required"] is False


def test_ai_retrieves_only_authorized_minimized_record_context() -> None:
    with make_client() as (client, _, records, provider):
        first = register(client, phone="+919876543210")
        second = register(client, phone="+919876543211")
        records.insert_one(
            {
                "record_id": "rec-diagnosis",
                "patient_id": first["patient"]["patient_id"],
                "category": "diagnosis",
                "title": "Seasonal allergy",
                "details": "Clinician recorded allergic rhinitis.",
                "recorded_on": "2026-01-02",
            }
        )
        records.insert_one(
            {
                "record_id": "rec-private",
                "patient_id": second["patient"]["patient_id"],
                "category": "diagnosis",
                "title": "Private record",
                "details": "Must not enter another patient's model context.",
                "recorded_on": "2026-01-03",
            }
        )

        response = client.post(
            "/api/ai/query",
            headers=bearer(first),
            json={"question": "What previous diagnoses are recorded?"},
        )
        assert response.status_code == 200
        assert response.json()["sources"][0]["record_id"] == "rec-diagnosis"
        assert "rec-diagnosis" in provider.context
        assert "rec-private" not in provider.context
        assert "Maya Rao" not in provider.context
        assert "+919876543210" not in provider.context

        unauthenticated = client.post("/api/ai/query", json={"question": "What is recorded?"})
        assert unauthenticated.status_code == 401


def test_local_speech_transcription_uses_selected_language_and_requires_auth(monkeypatch) -> None:
    from backend.app.routes import ai

    calls = []
    transcripts = {
        "te": "మందుల వివరాలు ఏమిటి?",
        "hi": "दवाइयाँ क्या हैं?",
    }

    def transcribe(audio_file, language, model_name):
        calls.append((audio_file.read(), language, model_name))
        return transcripts[language]

    monkeypatch.setattr(ai, "transcribe_audio", transcribe)
    with make_client() as (client, _, _, _):
        account = register(client)
        for language in ("te", "hi"):
            response = client.post(
                "/api/ai/transcribe",
                headers=bearer(account),
                files={"audio": ("voice-question.webm", b"recorded-audio", "audio/webm")},
                data={"language": language},
            )
            assert response.status_code == 200
            assert response.json() == {"text": transcripts[language]}
        assert calls == [
            (b"recorded-audio", "te", "tiny"),
            (b"recorded-audio", "hi", "tiny"),
        ]

        unauthenticated = client.post(
            "/api/ai/transcribe",
            files={"audio": ("voice-question.webm", b"recorded-audio", "audio/webm")},
            data={"language": "te"},
        )
        assert unauthenticated.status_code == 401


def test_interpreter_transcribes_and_translates_selected_language_pair(monkeypatch) -> None:
    from backend.app.routes import ai

    transcriptions = []

    def transcribe(audio_file, language, model_name):
        transcriptions.append((audio_file.read(), language, model_name))
        return {"en": "I have pain.", "te": "నాకు నొప్పిగా ఉంది."}[language]

    monkeypatch.setattr(ai, "transcribe_audio", transcribe)
    with make_client() as (client, _, _, provider):
        account = register(client)
        for source, target, expected_text in [
            ("en", "te", "I have pain."),
            ("te", "hi", "నాకు నొప్పిగా ఉంది."),
        ]:
            response = client.post(
                "/api/ai/interpret",
                headers=bearer(account),
                files={"audio": ("turn.webm", b"voice-audio", "audio/webm")},
                data={"source_language": source, "target_language": target},
            )
            assert response.status_code == 200
            assert response.json() == {
                "transcript": expected_text,
                "translation": f"{target}:{expected_text}",
            }

        assert transcriptions == [
            (b"voice-audio", "en", "tiny"),
            (b"voice-audio", "te", "tiny"),
        ]
        assert provider.interpretations == [
            ("I have pain.", "en", "te"),
            ("నాకు నొప్పిగా ఉంది.", "te", "hi"),
        ]
        same_language = client.post(
            "/api/ai/interpret",
            headers=bearer(account),
            files={"audio": ("turn.webm", b"voice-audio", "audio/webm")},
            data={"source_language": "hi", "target_language": "hi"},
        )
        assert same_language.status_code == 422

        unauthenticated = client.post(
            "/api/ai/interpret",
            files={"audio": ("turn.webm", b"voice-audio", "audio/webm")},
            data={"source_language": "en", "target_language": "te"},
        )
        assert unauthenticated.status_code == 401


def test_record_assistant_uses_local_translation_when_external_translation_is_unavailable() -> None:
    local_provider = LocalTranslationAIProvider()
    with make_client(
        translation_service=UnavailableTranslationService([]),
        ai_provider=local_provider,
    ) as (client, _, records, provider):
        account = register(client)
        records.insert_one(
            {
                "record_id": "rec-med",
                "patient_id": account["patient"]["patient_id"],
                "category": "medication",
                "title": "Medicine",
                "details": "Take one tablet daily.",
                "recorded_on": "2026-01-02",
            }
        )

        response = client.post(
            "/api/ai/query",
            headers=bearer(account),
            json={"question": "ఏ మందులు?", "language": "te"},
        )

        assert response.status_code == 200
        assert response.json()["answer"].startswith("te:")
        assert response.json()["translated_question"] == "What medicines are recorded?"
        assert provider.interpretations == [
            ("ఏ మందులు?", "te", "en"),
            ("Medication (2026-01-02): “Take one tablet daily.” [rec-med]", "en", "te"),
        ]


def test_record_assistant_reports_missing_local_translation_model() -> None:
    with make_client(
        translation_service=UnavailableTranslationService([]),
        ai_provider=OllamaTranslationModelMissingProvider(),
    ) as (client, _, _, _):
        account = register(client)
        response = client.post(
            "/api/ai/query",
            headers=bearer(account),
            json={"question": "ఏ మందులు?", "language": "te"},
        )

        assert response.status_code == 503
        assert "local translation model" in response.json()["detail"]
        assert "Install it" in response.json()["detail"]


def test_ai_translates_telugu_question_and_answer_using_selected_language() -> None:
    with make_client() as (client, _, records, provider):
        account = register(client)
        records.insert_one(
            {
                "record_id": "rec-med",
                "patient_id": account["patient"]["patient_id"],
                "category": "medication",
                "title": "Medicine",
                "details": "Take one tablet daily.",
                "recorded_on": "2026-01-02",
            }
        )

        response = client.post(
            "/api/ai/query",
            headers=bearer(account),
            json={"question": "ఏ మందులు నమోదు చేయబడ్డాయి?", "language": "te"},
        )

        assert response.status_code == 200
        assert response.json()["language"] == "te"
        assert response.json()["answer"] == "మందుల వివరాలు రికార్డుల్లో ఉన్నాయి."
        assert response.json()["disclaimer"] == (
            "This information is based on your recorded health records and is not a medical diagnosis "
            "or a substitute for professional medical advice."
        )
        assert provider.translations == [
            ("ఏ మందులు నమోదు చేయబడ్డాయి?", "en"),
            ("Medication (2026-01-02): “Take one tablet daily.” [rec-med]", "te"),
        ]


def test_ai_health_reports_configured_services_without_credentials() -> None:
    with make_client() as (client, _, _, _):
        response = client.get("/api/ai/health")
        assert response.status_code == 200
        assert response.json() == {
            "ollama": True,
            "model": "llama3.2:3b",
            "model_available": True,
            "translation": True,
            "local_translation_model": "translategemma:4b",
            "local_translation_model_available": True,
            "bhashini": True,
            "bhashini_configured": True,
            "google_translation": False,
            "google_translation_configured": False,
        }
        assert "api_key" not in response.text.lower()


def test_ollama_translation_uses_translate_gemma_prompt(monkeypatch) -> None:
    calls = []

    class MockAsyncClient:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def post(self, url: str, **kwargs) -> httpx.Response:
            calls.append((url, kwargs["json"]))
            return httpx.Response(
                200,
                json={"message": {"content": "నాకు ఛాతీలో నొప్పిగా ఉంది."}},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)
    provider = OllamaProvider(Settings(ollama_translation_model="translategemma:4b"))

    translated = asyncio.run(provider.translate("I have chest pain.", "en", "te"))

    assert translated == "నాకు ఛాతీలో నొప్పిగా ఉంది."
    assert calls == [
        (
            "http://localhost:11434/api/chat",
            {
                "model": "translategemma:4b",
                "stream": False,
                "options": {"temperature": 0, "num_predict": 192},
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "You are a professional English (en) to Telugu (te) translator. "
                            "Your goal is to accurately convey the meaning and nuances of the original "
                            "English text while adhering to Telugu grammar, vocabulary, and cultural "
                            "sensitivities. Produce only the Telugu translation, without any additional "
                            "explanations or commentary. Please translate the following English text into "
                            "Telugu:\n\nI have chest pain."
                        ),
                    }
                ],
            },
        )
    ]


def test_ai_returns_specific_ollama_and_translation_errors() -> None:
    patients = InMemoryCollection()
    records = InMemoryCollection()
    counters = InMemoryCollection()
    settings = Settings(jwt_secret_key=secrets.token_urlsafe(48))
    app = create_app(
        settings=settings,
        patients_collection=patients,
        health_records_collection=records,
        ai_provider=OllamaUnavailableProvider(),
        health_id_counter_collection=counters,
        translation_service=UnavailableTranslationService([]),
    )
    with TestClient(app) as client:
        account = register(client)
        ollama_response = client.post(
            "/api/ai/query",
            headers=bearer(account),
            json={"question": "What medicines are recorded?"},
        )
        translation_response = client.post(
            "/api/ai/query",
            headers=bearer(account),
            json={"question": "ఏ మందులు నమోదు చేయబడ్డాయి?", "language": "te"},
        )
        assert ollama_response.status_code == 503
        assert "Ollama is unavailable" in ollama_response.json()["detail"]
        assert translation_response.status_code == 503
        assert "Ollama is unavailable" in translation_response.json()["detail"]

    app = create_app(
        settings=settings,
        patients_collection=patients,
        health_records_collection=records,
        ai_provider=OllamaModelMissingProvider(),
        health_id_counter_collection=counters,
    )
    with TestClient(app) as client:
        account = register(client, phone="+919876543212")
        response = client.post(
            "/api/ai/query",
            headers=bearer(account),
            json={"question": "What medicines are recorded?"},
        )
        assert response.status_code == 503
        assert "configured Ollama model" in response.json()["detail"]


def test_bhashini_translation_uses_configured_credentials_and_minimal_text(monkeypatch) -> None:
    from backend.app.services.translation_service import BHASHINI_INFERENCE_URL

    settings = Settings(
        bhashini_api_url="https://example.test/pipeline",
        bhashini_user_id="test-user",
        bhashini_api_key="test-ulca-key",
        bhashini_pipeline_id="test-pipeline",
    )
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/pipeline":
            return httpx.Response(
                200,
                json={
                    "pipelineInferenceAPIEndPoint": {
                        "callbackUrl": BHASHINI_INFERENCE_URL,
                        "inferenceApiKey": {"name": "Authorization", "value": "ephemeral-token"},
                    },
                    "pipelineResponseConfig": [
                        {
                            "taskType": "translation",
                            "config": [
                                {
                                    "language": {"sourceLanguage": "te", "targetLanguage": "en"},
                                    "serviceId": "translation-service",
                                }
                            ],
                        }
                    ],
                },
            )
        return httpx.Response(
            200,
            json={"pipelineResponse": [{"output": [{"target": ["What medicines are listed?"]}]}]},
        )

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        "backend.app.services.translation_service.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    translator = TranslationService(settings)

    import asyncio

    translated = asyncio.run(translator.translate("ఏ మందులు?", "te", "en"))
    assert translated == "What medicines are listed?"
    assert calls[0].headers["userID"] == "test-user"
    assert calls[0].headers["ulcaApiKey"] == "test-ulca-key"
    assert "patient" not in calls[1].content.decode().lower()
    assert calls[1].headers["authorization"] == "ephemeral-token"


def test_ai_rejects_client_supplied_patient_id_and_unsupported_language() -> None:
    with make_client() as (client, _, _, _):
        account = register(client)

        supplied_patient = client.post(
            "/api/ai/query",
            headers=bearer(account),
            json={"question": "What is recorded?", "patient_id": "another-patient"},
        )
        unsupported_language = client.post(
            "/api/ai/query",
            headers=bearer(account),
            json={"question": "What is recorded?", "language": "fr"},
        )
        empty_question = client.post(
            "/api/ai/query",
            headers=bearer(account),
            json={"question": "   "},
        )

        assert supplied_patient.status_code == 422
        assert unsupported_language.status_code == 422
        assert empty_question.status_code == 422


def test_ai_does_not_call_model_when_information_is_missing() -> None:
    with make_client() as (client, _, records, provider):
        account = register(client)
        records.insert_one(
            {
                "record_id": "rec-note",
                "patient_id": account["patient"]["patient_id"],
                "category": "note",
                "title": "Visit note",
                "details": "Patient attended a routine appointment.",
                "recorded_on": "2026-01-02",
            }
        )

        response = client.post(
            "/api/ai/query",
            headers=bearer(account),
            json={"question": "What medications are listed?"},
        )
        assert response.status_code == 200
        assert response.json()["sources"] == []
        assert response.json()["answer"] == "I could not find that information in your recorded health records."
        assert provider.context == ""


def test_ai_invented_excerpt_is_rejected_and_direct_identifiers_are_redacted() -> None:
    with make_client() as (client, _, records, _):
        account = register(client)
        records.insert_one(
            {
                "record_id": "rec-private-info",
                "patient_id": account["patient"]["patient_id"],
                "category": "note",
                "title": "Visit note",
                "details": "Call 555-123-4567 or maya@example.org about recorded follow-up.",
                "recorded_on": "2026-01-02",
            }
        )

        context = build_record_context(records.documents)
        assert "555-123-4567" not in context
        assert "maya@example.org" not in context
        assert "[REDACTED]" in context

        answer, sources = validate_extractive_answer(
            json.dumps(
                {
                    "selections": [
                        {"record_id": "rec-private-info", "quote": "An invented appointment was recorded."}
                    ]
                }
            ),
            records.documents,
        )
        assert "couldn't select an exact passage" in answer
        assert sources == []


def test_ai_rejects_unavailable_or_unverified_model_output() -> None:
    patients = InMemoryCollection()
    records = InMemoryCollection()
    counters = InMemoryCollection()
    settings = Settings(
        frontend_base_url="http://localhost:5173",
        jwt_secret_key=secrets.token_urlsafe(48),
    )
    with TestClient(
        create_app(
            settings=settings,
            patients_collection=patients,
            health_records_collection=records,
            ai_provider=InventingAIProvider(),
            health_id_counter_collection=counters,
        )
    ) as client:
        account = register(client)
        records.insert_one(
            {
                "record_id": "rec-diagnosis",
                "patient_id": account["patient"]["patient_id"],
                "category": "diagnosis",
                "title": "Seasonal allergy",
                "details": "Clinician recorded allergic rhinitis.",
                "recorded_on": "2026-01-02",
            }
        )
        response = client.post(
            "/api/ai/query",
            headers=bearer(account),
            json={"question": "What previous diagnoses are recorded?"},
        )
        assert response.status_code == 200
        assert "couldn't select an exact passage" in response.json()["answer"]
        assert response.json()["sources"] == []


def test_legacy_patient_url_redirect_does_not_check_record_existence() -> None:
    with make_client() as (client, _, _, _):
        response = client.get("/patient/MW001", follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"] == "http://localhost:5173/patients/MW001"


def test_cors_allows_vite_origin_and_blocks_other_origins() -> None:
    with make_client() as (client, _, _, _):
        allowed = client.options(
            "/api/auth/login",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        authenticated = client.options(
            "/api/patients/me",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        denied = client.options(
            "/api/auth/login",
            headers={
                "Origin": "https://untrusted.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
        assert authenticated.status_code == 200
        assert authenticated.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
        assert "authorization" in authenticated.headers["access-control-allow-headers"].lower()
        assert "access-control-allow-origin" not in denied.headers


def test_invalid_bearer_token_is_rejected() -> None:
    with make_client() as (client, _, _, _):
        response = client.get("/api/patients/me", headers={"Authorization": "Bearer invalid"})
        assert response.status_code == 401


def test_health_endpoint_reports_test_database_status() -> None:
    with make_client() as (client, _, _, _):
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


def test_mongodb_read_failure_returns_service_unavailable() -> None:
    records = InMemoryCollection()
    counters = InMemoryCollection()
    settings = Settings(jwt_secret_key=secrets.token_urlsafe(48))
    with TestClient(create_app(
        settings=settings,
        patients_collection=BrokenCollection(),
        health_records_collection=records,
        health_id_counter_collection=counters,
    )) as client:
        response = client.post("/api/auth/login", json={"identifier": "MW001", "password": "bad"})
        assert response.status_code == 503


def test_unavailable_ai_model_returns_service_unavailable() -> None:
    patients = InMemoryCollection()
    records = InMemoryCollection()
    counters = InMemoryCollection()
    settings = Settings(
        frontend_base_url="http://localhost:5173",
        jwt_secret_key=secrets.token_urlsafe(48),
    )
    with TestClient(
        create_app(
            settings=settings,
            patients_collection=patients,
            health_records_collection=records,
            ai_provider=BrokenAIProvider(),
            health_id_counter_collection=counters,
        )
    ) as client:
        account = register(client)
        records.insert_one(
            {
                "record_id": "rec-med",
                "patient_id": account["patient"]["patient_id"],
                "category": "medication",
                "title": "Medicine",
                "details": "Recorded medicine.",
                "recorded_on": "2026-01-02",
            }
        )
        response = client.post(
            "/api/ai/query",
            headers=bearer(account),
            json={"question": "What medicines are recorded?"},
        )
        assert response.status_code == 503
        assert "Ollama became unavailable" in response.json()["detail"]


def test_registration_requires_configured_jwt_secret() -> None:
    patients = InMemoryCollection()
    records = InMemoryCollection()
    counters = InMemoryCollection()
    settings = Settings(jwt_secret_key="")
    with TestClient(
        create_app(
            settings=settings,
            patients_collection=patients,
            health_records_collection=records,
            ai_provider=FakeAIProvider(),
            health_id_counter_collection=counters,
        )
    ) as client:
        response = client.post("/api/auth/register", json=registration_payload())
        assert response.status_code == 503
        assert patients.documents == []
