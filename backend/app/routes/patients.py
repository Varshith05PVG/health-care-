import logging

from fastapi import APIRouter, Depends, HTTPException, Response
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

from backend.app.config import Settings, get_request_settings
from backend.app.db import get_patients_collection
from backend.app.schemas import PatientResponse, QRLookupRequest
from backend.app.security import create_qr_token, get_current_patient, verify_qr_token
from backend.app.services.qr import create_qr_png, patient_page_url

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["patients"])


def public_patient(document: dict) -> dict:
    patient_id = str(document.get("patient_id") or document.get("health_id") or document.get("_id"))
    return {
        "patient_id": patient_id,
        "health_id": document.get("health_id", patient_id),
        "name": document["name"],
        "age": document["age"],
        "gender": document["gender"],
        "blood_group": document.get("blood_group", "Unknown"),
        "language": document.get("language", "English"),
    }


@router.get("/patients/me", response_model=PatientResponse)
def current_patient(
    patient_id: str = Depends(get_current_patient),
    collection: Collection = Depends(get_patients_collection),
) -> dict:
    try:
        document = collection.find_one(
            {"$or": [{"patient_id": patient_id}, {"health_id": patient_id}]}
        )
    except PyMongoError as exc:
        logger.exception("MongoDB failed while retrieving the current patient.")
        raise HTTPException(status_code=503, detail="Patient storage is currently unavailable.") from exc

    if document is None:
        raise HTTPException(status_code=404, detail="Patient not found.")
    return public_patient(document)


@router.get("/patients/{patient_id}", response_model=PatientResponse)
def get_patient(
    patient_id: str,
    current_patient_id: str = Depends(get_current_patient),
    collection: Collection = Depends(get_patients_collection),
) -> dict:
    if patient_id != current_patient_id:
        try:
            document = collection.find_one(
                {"$or": [{"patient_id": current_patient_id}, {"health_id": current_patient_id}]}
            )
        except PyMongoError as exc:
            logger.exception("MongoDB failed while verifying a patient profile request.")
            raise HTTPException(status_code=503, detail="Patient storage is currently unavailable.") from exc
        if document is None or patient_id != document.get("health_id"):
            raise HTTPException(status_code=403, detail="You can only access your own patient record.")
        return public_patient(document)
    return current_patient(current_patient_id, collection)


@router.get("/patients/me/qr", responses={200: {"content": {"image/png": {}}}})
def get_patient_qr(
    patient_id: str = Depends(get_current_patient),
    settings: Settings = Depends(get_request_settings),
) -> Response:
    qr_token = create_qr_token(patient_id, settings)
    url = patient_page_url(settings.frontend_base_url, patient_id, qr_token)
    return Response(content=create_qr_png(url), media_type="image/png")


@router.post("/qr/lookup", response_model=PatientResponse)
def lookup_scanned_qr(
    qr: QRLookupRequest,
    current_patient_id: str = Depends(get_current_patient),
    collection: Collection = Depends(get_patients_collection),
    settings: Settings = Depends(get_request_settings),
) -> dict:
    if qr.patient_id != current_patient_id:
        raise HTTPException(status_code=403, detail="This Health ID does not belong to the logged-in patient.")

    if qr.qr_token:
        verify_qr_token(qr.qr_token, qr.patient_id, settings)

    try:
        document = collection.find_one(
            {"$or": [{"patient_id": current_patient_id}, {"health_id": current_patient_id}]}
        )
    except PyMongoError as exc:
        logger.exception("MongoDB failed while retrieving the scanned patient record.")
        raise HTTPException(status_code=503, detail="Patient storage is currently unavailable.") from exc

    if document is None:
        raise HTTPException(status_code=404, detail="Patient not found.")
    return public_patient(document)
