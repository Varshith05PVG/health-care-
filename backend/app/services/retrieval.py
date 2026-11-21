import json
import re


CATEGORY_TERMS = {
    "diagnosis": {"diagnosis", "diagnoses", "condition", "conditions", "illness", "illnesses"},
    "medication": {"medicine", "medicines", "medication", "medications", "drug", "drugs", "prescription"},
    "allergy": {"allergy", "allergies", "allergic"},
    "note": {"symptom", "symptoms"},
}
SUMMARY_TERMS = {"history", "summarize", "summary", "previous", "recorded", "records"}
STOP_WORDS = {
    "a", "an", "and", "are", "for", "from", "has", "have", "is", "list", "me", "my",
    "of", "on", "or", "patient", "please", "the", "this", "to", "what", "which",
}
EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_PATTERN = re.compile(r"(?<!\w)\+?[\d][\d\s().-]{7,}\d(?!\w)")


def retrieve_relevant_records(records: list[dict], question: str, limit: int = 10) -> list[dict]:
    words = set(re.findall(r"[a-zA-Z0-9]+", question.lower())) - STOP_WORDS
    categories = {
        category
        for category, terms in CATEGORY_TERMS.items()
        if words.intersection(terms)
    }
    is_summary = bool(words.intersection(SUMMARY_TERMS))
    ranked: list[tuple[int, str, dict]] = []

    for record in records:
        searchable = f"{record['title']} {record['details']}".lower()
        record_words = set(re.findall(r"[a-zA-Z0-9]+", searchable))
        overlap = len(words.intersection(record_words))
        category_match = bool(categories and record["category"] in categories)
        if category_match:
            overlap += 4
        if overlap:
            ranked.append((overlap, record["recorded_on"], record))

    if not ranked and is_summary:
        return sorted(records, key=lambda item: item["recorded_on"], reverse=True)[:limit]
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [record for _, _, record in ranked[:limit]]


def redact_direct_identifiers(value: str) -> str:
    without_emails = EMAIL_PATTERN.sub("[REDACTED]", value)
    return PHONE_PATTERN.sub("[REDACTED]", without_emails)


def build_record_context(records: list[dict]) -> str:
    excerpts = [
        {
            "record_id": record["record_id"],
            "category": record["category"],
            "recorded_on": record["recorded_on"],
            "title": redact_direct_identifiers(record["title"]),
            "details": redact_direct_identifiers(record["details"]),
        }
        for record in records
    ]
    return json.dumps(excerpts, ensure_ascii=False)


def validate_extractive_answer(raw_answer: str, records: list[dict]) -> tuple[str, list[dict]]:
    """Return only exact model-selected excerpts that belong to retrieved records."""
    fallback = (
        "I couldn't select an exact passage from the available records. "
        "Please review the records with a healthcare professional."
    )
    try:
        payload = json.loads(raw_answer)
    except json.JSONDecodeError:
        return fallback, []
    selections = payload.get("selections") if isinstance(payload, dict) else None
    if not isinstance(selections, list) or not selections or len(selections) > 10:
        return fallback, []

    by_id = {record["record_id"]: record for record in records}
    validated: list[tuple[dict, str]] = []
    seen: set[str] = set()
    for selection in selections:
        if not isinstance(selection, dict):
            return fallback, []
        record_id = selection.get("record_id")
        quote = selection.get("quote")
        record = by_id.get(record_id) if isinstance(record_id, str) else None
        if (
            record is None
            or record_id in seen
            or not isinstance(quote, str)
            or not quote.strip()
        ):
            return fallback, []
        title = redact_direct_identifiers(record["title"])
        details = redact_direct_identifiers(record["details"])
        if quote not in title and quote not in details:
            return fallback, []
        seen.add(record_id)
        validated.append((record, quote))

    answer = "\n".join(
        f"{record['category'].capitalize()} ({record['recorded_on']}): “{quote}” [{record['record_id']}]"
        for record, quote in validated
    )
    sources = [
        {
            "record_id": record["record_id"],
            "category": record["category"],
            "title": redact_direct_identifiers(record["title"]),
            "recorded_on": record["recorded_on"],
        }
        for record, _ in validated
    ]
    return answer, sources
