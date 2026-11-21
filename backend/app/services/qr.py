from io import BytesIO
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

import qrcode


def patient_page_url(frontend_base_url: str, patient_id: str, qr_token: str | None = None) -> str:
    base = urlsplit(frontend_base_url.rstrip("/"))
    path = f"{base.path.rstrip('/')}/patients/{quote(patient_id, safe='')}"
    query = urlencode({"qr_token": qr_token}) if qr_token else ""
    return urlunsplit((base.scheme, base.netloc, path, query, ""))


def create_qr_png(url: str) -> bytes:
    image = qrcode.make(url)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
