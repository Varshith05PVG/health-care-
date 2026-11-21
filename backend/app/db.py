import logging

from fastapi import HTTPException, Request
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

logger = logging.getLogger(__name__)


def get_patients_collection(request: Request) -> Collection:
    collection = request.app.state.patients
    if not request.app.state.patient_id_index_ready:
        try:
            collection.create_index("patient_id", unique=True)
            collection.create_index(
                "phone",
                unique=True,
                partialFilterExpression={"phone": {"$type": "string"}},
            )
            collection.create_index(
                "health_id",
                unique=True,
                partialFilterExpression={"health_id": {"$type": "string"}},
            )
        except PyMongoError as exc:
            logger.exception("Could not create the unique patient ID index.")
            raise HTTPException(
                status_code=503,
                detail="Patient storage is currently unavailable.",
            ) from exc
        request.app.state.patient_id_index_ready = True
    return collection


def get_health_records_collection(request: Request) -> Collection:
    collection = request.app.state.health_records
    if not request.app.state.health_record_indexes_ready:
        try:
            collection.create_index([("patient_id", 1), ("created_at", -1)])
        except PyMongoError as exc:
            logger.exception("Could not create health-record indexes.")
            raise HTTPException(
                status_code=503,
                detail="Health-record storage is currently unavailable.",
            ) from exc
        request.app.state.health_record_indexes_ready = True
    return collection
