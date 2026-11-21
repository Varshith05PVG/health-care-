import re

from pymongo import ReturnDocument
from pymongo.collection import Collection


HEALTH_ID_PATTERN = re.compile(r"^HI-P(\d+)V\1G$", re.IGNORECASE)
HEALTH_ID_COUNTER_KEY = "patient_health_id"


def next_health_id(patients: Collection, counters: Collection) -> str:
    existing_ids = patients.find({}, {"health_id": 1})
    highest_existing = max(
        (
            int(match.group(1))
            for patient in existing_ids
            if isinstance(patient.get("health_id"), str)
            if (match := HEALTH_ID_PATTERN.fullmatch(patient["health_id"]))
        ),
        default=0,
    )
    counters.find_one_and_update(
        {"_id": HEALTH_ID_COUNTER_KEY},
        {"$max": {"sequence": highest_existing}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    counter = counters.find_one_and_update(
        {"_id": HEALTH_ID_COUNTER_KEY},
        {"$inc": {"sequence": 1}},
        return_document=ReturnDocument.AFTER,
    )
    sequence = counter["sequence"]
    return f"HI-P{sequence:02d}V{sequence:02d}G"
