from __future__ import annotations

from datetime import date, datetime


def parse_optional_date(date_value) -> date | None:
    if not date_value:
        return None
    if isinstance(date_value, date) and not isinstance(date_value, datetime):
        return date_value
    if isinstance(date_value, datetime):
        return date_value.date()

    text = str(date_value).strip()
    if not text:
        return None

    patterns = (
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d.%m.%Y",
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
    )
    for pattern in patterns:
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue

    try:
        return date.fromisoformat(text[:10])
    except ValueError as err:
        raise ValueError(f"Date invalide: {date_value}") from err
