from datetime import date, datetime, timezone
import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

from backend.app.db import get_health_records_collection
from backend.app.schemas import HealthRecordCreate, HealthRecordResponse
from backend.app.security import get_current_patient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/records", tags=["health records"])


def serialize_record(document: dict) -> dict:
    return {
        "record_id": document["record_id"],
        "category": document["category"],
        "title": document["title"],
        "details": document["details"],
        "doctor_name": document.get("doctor_name"),
        "doctor_specialization": document.get("doctor_specialization"),
        "recorded_on": document["recorded_on"],
    }


@router.get("", response_model=list[HealthRecordResponse])
def list_records(
    patient_id: str = Depends(get_current_patient),
    collection: Collection = Depends(get_health_records_collection),
) -> list[dict]:
    try:
        patient_records = collection.find(
            {"$or": [{"patient_id": patient_id}, {"health_id": patient_id}]}
        )
        return [serialize_record(record) for record in patient_records.sort("recorded_on", -1)]
    except PyMongoError as exc:
        logger.exception("MongoDB failed while listing health records.")
        raise HTTPException(status_code=503, detail="Health-record storage is currently unavailable.") from exc


@router.post("", response_model=HealthRecordResponse, status_code=status.HTTP_201_CREATED)
def create_record(
    record: HealthRecordCreate,
    patient_id: str = Depends(get_current_patient),
    collection: Collection = Depends(get_health_records_collection),
) -> dict:
    document = record.model_dump()
    document["record_id"] = str(uuid4())
    document["patient_id"] = patient_id
    document["recorded_on"] = record.recorded_on or date.today().isoformat()
    document["created_at"] = datetime.now(timezone.utc)

    try:
        collection.insert_one(document)
    except PyMongoError as exc:
        logger.exception("MongoDB failed while saving a health record.")
        raise HTTPException(status_code=503, detail="Health-record storage is currently unavailable.") from exc
    return serialize_record(document)
