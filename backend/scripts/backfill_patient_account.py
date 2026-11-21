"""Attach login credentials to an existing Week 6 patient record.

Run only after a trusted operator has independently verified the patient.
"""

import argparse
import getpass
import logging
import re

from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError, PyMongoError

from backend.app.config import get_settings
from backend.app.security import hash_password, normalize_phone

logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill an existing patient account after trusted identity verification."
    )
    parser.add_argument("patient_id", help="Existing Health ID exactly as stored in MongoDB")
    args = parser.parse_args()

    phone = normalize_phone(input("Verified phone number (include country code): ").strip())
    if not re.fullmatch(r"\+?[1-9]\d{7,14}", phone):
        parser.error("Phone number must contain 8 to 15 digits and may start with '+'.")

    password = getpass.getpass("Set a new password (at least 12 characters): ")
    if len(password) < 12 or len(password) > 128:
        parser.error("Password must be between 12 and 128 characters.")
    confirmation = getpass.getpass("Confirm new password: ")
    if password != confirmation:
        parser.error("Passwords do not match.")

    client = MongoClient(get_settings().mongodb_uri, serverSelectionTimeoutMS=3000)
    try:
        patients = client[get_settings().mongodb_database]["patients"]
        patients.create_index(
            "phone",
            unique=True,
            partialFilterExpression={"phone": {"$type": "string"}},
        )
        result = patients.update_one(
            {"patient_id": args.patient_id, "password_hash": {"$exists": False}},
            {"$set": {"phone": phone, "password_hash": hash_password(password)}},
        )
        if result.matched_count == 0:
            print("No unclaimed legacy patient record matched that Health ID.")
            return 1
    except DuplicateKeyError:
        print("That verified phone number is already associated with another patient account.")
        return 1
    except PyMongoError:
        logger.exception("MongoDB failed during the trusted account backfill.")
        print("Patient account backfill failed. Check MongoDB availability and try again.")
        return 1
    finally:
        client.close()

    print("Patient account credentials were added. The patient can now sign in.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
