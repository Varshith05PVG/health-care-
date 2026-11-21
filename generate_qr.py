"""Generate a patient Health ID QR code from the command line."""

import argparse
import os
import re
from pathlib import Path

from backend.app.config import get_settings
from backend.app.security import create_qr_token
from backend.app.services.qr import create_qr_png, patient_page_url


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a patient Health ID QR code.")
    parser.add_argument("patient_id", help="Registered patient ID, for example MW001")
    parser.add_argument(
        "--frontend-url",
        default=os.getenv("FRONTEND_BASE_URL", "http://localhost:5173"),
        help="Frontend base URL (defaults to FRONTEND_BASE_URL or http://localhost:5173)",
    )
    parser.add_argument("--output", help="Output PNG path (defaults to <patient_id>_QR.png)")
    args = parser.parse_args()

    if not re.fullmatch(r"MW[A-Za-z0-9_-]{1,38}", args.patient_id):
        parser.error("Patient ID must be a valid Health ID.")
    settings = get_settings()
    qr_token = create_qr_token(args.patient_id, settings)
    url = patient_page_url(args.frontend_url, args.patient_id, qr_token)
    output_path = Path(args.output or f"{args.patient_id}_QR.png")
    output_path.write_bytes(create_qr_png(url))
    print(f"QR code saved to {output_path}")


if __name__ == "__main__":
    main()