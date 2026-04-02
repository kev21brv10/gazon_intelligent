from __future__ import annotations

import ast
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from typing import Any

from .const import (
    APPLICATION_INTERVENTIONS,
    APPLICATION_IRRIGATION_MODE_AUTO,
    APPLICATION_IRRIGATION_MODE_MANUAL,
    APPLICATION_IRRIGATION_MODE_SUGGESTION,
    APPLICATION_TYPE_FOLIAIRE,
    APPLICATION_TYPE_SOL,
    DEFAULT_APPLICATION_IRRIGATION_BLOCK_HOURS,
    DEFAULT_APPLICATION_IRRIGATION_DELAY_MINUTES,
    DEFAULT_APPLICATION_IRRIGATION_MODE,
    DEFAULT_APPLICATION_POST_WATERING_MM,
    DEFAULT_AUTO_IRRIGATION_ENABLED,
)
from .water import _watering_item_mm, compute_recent_watering_mm

PHASE_DURATIONS_DAYS: dict[str, int] = {
    "Normal": 0,
    "Sursemis": 21,
    "Traitement": 2,
    "Fertilisation": 2,
    "Biostimulant": 1,
    "Agent Mouillant": 1,
    "Scarification": 7,
    "Hivernage": 999,
}

SIGNIFICANT_WATERING_THRESHOLD_MM = 2.0

APPLICATION_DEFAULTS: dict[str, dict[str, Any]] = {
    "Traitement": {
        "application_type": APPLICATION_TYPE_FOLIAIRE,
        "application_requires_watering_after": False,
        "application_post_watering_mm": 0.0,
        "application_irrigation_block_hours": DEFAULT_APPLICATION_IRRIGATION_BLOCK_HOURS,
        "application_irrigation_delay_minutes": DEFAULT_APPLICATION_IRRIGATION_DELAY_MINUTES,
        "application_irrigation_mode": APPLICATION_IRRIGATION_MODE_SUGGESTION,
    },
    "Fertilisation": {
        "application_type": APPLICATION_TYPE_SOL,
        "application_requires_watering_after": True,
        "application_post_watering_mm": DEFAULT_APPLICATION_POST_WATERING_MM,
        "application_irrigation_block_hours": 0.0,
        "application_irrigation_delay_minutes": DEFAULT_APPLICATION_IRRIGATION_DELAY_MINUTES,
        "application_irrigation_mode": DEFAULT_APPLICATION_IRRIGATION_MODE,
    },
    "Biostimulant": {
        "application_type": APPLICATION_TYPE_SOL,
        "application_requires_watering_after": True,
        "application_post_watering_mm": DEFAULT_APPLICATION_POST_WATERING_MM,
        "application_irrigation_block_hours": 0.0,
        "application_irrigation_delay_minutes": DEFAULT_APPLICATION_IRRIGATION_DELAY_MINUTES,
        "application_irrigation_mode": DEFAULT_APPLICATION_IRRIGATION_MODE,
    },
    "Agent Mouillant": {
        "application_type": APPLICATION_TYPE_SOL,
        "application_requires_watering_after": True,
        "application_post_watering_mm": DEFAULT_APPLICATION_POST_WATERING_MM,
        "application_irrigation_block_hours": 0.0,
        "application_irrigation_delay_minutes": DEFAULT_APPLICATION_IRRIGATION_DELAY_MINUTES,
        "application_irrigation_mode": DEFAULT_APPLICATION_IRRIGATION_MODE,
    },
    "Scarification": {
        "application_type": APPLICATION_TYPE_SOL,
        "application_requires_watering_after": True,
        "application_post_watering_mm": 0.8,
        "application_irrigation_block_hours": 0.0,
        "application_irrigation_delay_minutes": DEFAULT_APPLICATION_IRRIGATION_DELAY_MINUTES,
        "application_irrigation_mode": DEFAULT_APPLICATION_IRRIGATION_MODE,
    },
}


def _normalize_user_action_summary(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    summary: dict[str, Any] = {}
    state = str(value.get("state") or "").strip().lower()
    if state in {"ok", "bloque", "en_attente", "refuse"}:
        summary["state"] = state
    action = value.get("action")
    if action not in (None, ""):
        summary["action"] = str(action)
    triggered_at = value.get("triggered_at")
    if triggered_at not in (None, ""):
        summary["triggered_at"] = str(triggered_at)
    reason = value.get("reason")
    if reason not in (None, ""):
        summary["reason"] = str(reason)
    plan_type = value.get("plan_type")
    if plan_type not in (None, ""):
        summary["plan_type"] = str(plan_type)
    zone_count = _to_int(value.get("zone_count"))
    if zone_count is not None:
        summary["zone_count"] = zone_count
    passages = _to_int(value.get("passages"))
    if passages is not None:
        summary["passages"] = passages
    return summary or None


def _latest_history_item(
    history: list[dict[str, Any]],
    predicate,
) -> dict[str, Any] | None:
    for item in reversed(history):
        if isinstance(item, dict) and predicate(item):
            return item
    return None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _to_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "on", "1", "yes", "oui"}:
        return True
    if text in {"false", "off", "0", "no", "non"}:
        return False
    return None


def _normalize_application_irrigation_mode(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip().lower()
    if text == "manual":
        text = APPLICATION_IRRIGATION_MODE_MANUAL
    if text in {
        APPLICATION_IRRIGATION_MODE_AUTO,
        APPLICATION_IRRIGATION_MODE_MANUAL,
        APPLICATION_IRRIGATION_MODE_SUGGESTION,
    }:
        return text
    return None


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed_date = date.fromisoformat(text)
        except ValueError:
            return None
        return datetime.combine(parsed_date, datetime.min.time(), tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _application_defaults_for_intervention(intervention: Any) -> dict[str, Any]:
    return dict(APPLICATION_DEFAULTS.get(str(intervention or "").strip(), {}))


def _merge_application_fields(
    base: dict[str, Any],
    payload: dict[str, Any] | None,
    intervention: Any = None,
) -> dict[str, Any]:
    payload = payload or {}
    merged = dict(base)
    defaults = _application_defaults_for_intervention(intervention)
    for key, value in defaults.items():
        merged.setdefault(key, value)
    for key in (
        "application_type",
        "application_requires_watering_after",
        "application_post_watering_mm",
        "application_irrigation_block_hours",
        "application_irrigation_delay_minutes",
        "application_irrigation_mode",
        "application_label_notes",
    ):
        if key in payload and payload.get(key) not in (None, "", [], {}):
            merged[key] = payload.get(key)
    if merged.get("application_type") in (None, ""):
        merged["application_type"] = defaults.get("application_type")
    merged["application_requires_watering_after"] = _to_bool(merged.get("application_requires_watering_after"))
    if merged.get("application_requires_watering_after") is None:
        merged["application_requires_watering_after"] = defaults.get("application_requires_watering_after")
    merged["application_post_watering_mm"] = _to_float(merged.get("application_post_watering_mm"))
    if merged.get("application_post_watering_mm") is None:
        merged["application_post_watering_mm"] = defaults.get("application_post_watering_mm")
    merged["application_irrigation_block_hours"] = _to_float(merged.get("application_irrigation_block_hours"))
    if merged.get("application_irrigation_block_hours") is None:
        merged["application_irrigation_block_hours"] = defaults.get("application_irrigation_block_hours")
    merged["application_irrigation_delay_minutes"] = _to_float(
        merged.get("application_irrigation_delay_minutes")
    )
    if merged.get("application_irrigation_delay_minutes") is None:
        merged["application_irrigation_delay_minutes"] = defaults.get("application_irrigation_delay_minutes")
    merged["application_irrigation_mode"] = _normalize_application_irrigation_mode(
        merged.get("application_irrigation_mode")
    )
    if merged.get("application_irrigation_mode") is None:
        merged["application_irrigation_mode"] = defaults.get("application_irrigation_mode")
    if merged.get("application_label_notes") in ("", None):
        merged.pop("application_label_notes", None)
    return merged


def _application_type_for_item(item: dict[str, Any]) -> str | None:
    value = item.get("application_type")
    if value in (None, ""):
        defaults = APPLICATION_DEFAULTS.get(str(item.get("type") or "").strip(), {})
        value = defaults.get("application_type")
    if value in (None, ""):
        return None
    return str(value).strip().lower()


def _split_csv_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        items = value
    else:
        text = str(value).strip()
        if not text:
            return []
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = ast.literal_eval(text)
            except (ValueError, SyntaxError):
                parsed = None
            if isinstance(parsed, (list, tuple, set)):
                items = parsed
            else:
                items = text.split(",")
        else:
            items = text.split(",")
    clean: list[str] = []
    for item in items:
        text = str(item).strip()
        if text:
            clean.append(text)
    return clean


_MONTH_LABELS_FR: dict[int, str] = {
    1: "Janvier",
    2: "Février",
    3: "Mars",
    4: "Avril",
    5: "Mai",
    6: "Juin",
    7: "Juillet",
    8: "Août",
    9: "Septembre",
    10: "Octobre",
    11: "Novembre",
    12: "Décembre",
}

_MONTH_ALIASES: dict[str, int] = {
    "janvier": 1,
    "janv": 1,
    "jan": 1,
    "feb": 2,
    "fev": 2,
    "fevr": 2,
    "fevrier": 2,
    "février": 2,
    "mars": 3,
    "mar": 3,
    "avr": 4,
    "avril": 4,
    "apr": 4,
    "mai": 5,
    "may": 5,
    "juin": 6,
    "jun": 6,
    "juil": 7,
    "juillet": 7,
    "jul": 7,
    "aout": 8,
    "août": 8,
    "sep": 9,
    "sept": 9,
    "septembre": 9,
    "oct": 10,
    "octobre": 10,
    "nov": 11,
    "novembre": 11,
    "dec": 12,
    "decembre": 12,
    "décembre": 12,
}


def _normalize_text(value: object | None) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _month_token_to_int(value: object | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and 1 <= value <= 12:
        return value
    try:
        number = int(float(str(value).strip()))
    except (TypeError, ValueError):
        number = None
    if number is not None and 1 <= number <= 12:
        return number
    normalized = _normalize_text(value)
    if not normalized:
        return None
    return _MONTH_ALIASES.get(normalized)


def normalize_application_months(value: Any) -> list[int]:
    if value in (None, "", [], {}):
        return []

    items: list[object]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = ast.literal_eval(text)
            except (ValueError, SyntaxError):
                parsed = None
            if isinstance(parsed, (list, tuple, set)):
                items = list(parsed)
            else:
                items = re.split(r"[,+;/|]", text)
        else:
            items = re.split(r"[,+;/|]", text)
    elif isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        items = [value]

    months: list[int] = []
    for item in items:
        if item in (None, "", [], {}):
            continue
        if isinstance(item, (list, tuple, set)):
            months.extend(normalize_application_months(item))
            continue
        if isinstance(item, str):
            token = item.strip()
            if not token:
                continue
            range_match = re.fullmatch(r"(.+?)\s*(?:-|–|à|au|to)\s*(.+)", token, flags=re.IGNORECASE)
            if range_match:
                start = _month_token_to_int(range_match.group(1))
                end = _month_token_to_int(range_match.group(2))
                if start is not None and end is not None:
                    if start <= end:
                        months.extend(range(start, end + 1))
                    else:
                        months.extend(list(range(start, 13)) + list(range(1, end + 1)))
                    continue
            month = _month_token_to_int(token)
            if month is not None:
                months.append(month)
            continue
        month = _month_token_to_int(item)
        if month is not None:
            months.append(month)

    return sorted(dict.fromkeys(months))


def format_application_months_label(value: Any) -> str | None:
    months = normalize_application_months(value)
    if not months:
        return None

    ranges: list[tuple[int, int]] = []
    start = months[0]
    previous = months[0]
    for month in months[1:]:
        if month == previous + 1:
            previous = month
            continue
        ranges.append((start, previous))
        start = previous = month
    ranges.append((start, previous))

    parts: list[str] = []
    for start_month, end_month in ranges:
        if start_month == end_month:
            parts.append(_MONTH_LABELS_FR.get(start_month, str(start_month)))
        else:
            parts.append(
                f"{_MONTH_LABELS_FR.get(start_month, str(start_month))} à {_MONTH_LABELS_FR.get(end_month, str(end_month))}"
            )
    return ", ".join(parts)


def normalize_product_id(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower().replace(" ", "_")
    text = "".join(ch for ch in text if ch.isalnum() or ch in {"_", "-"}).strip("_-")
    return text or None


def normalize_product_record(product_id: Any, payload: dict[str, Any] | None) -> dict[str, Any] | None:
    product_key = normalize_product_id(product_id)
    if not product_key:
        return None
    payload = payload or {}
    name = str(payload.get("nom") or payload.get("name") or product_key).strip()
    product_type = str(payload.get("type") or "").strip()
    dose_conseillee = str(payload.get("dose_conseillee") or "").strip()
    note = str(payload.get("note") or "").strip()
    record = {
        "id": product_key,
        "nom": name or product_key,
        "type": product_type or None,
        "dose_conseillee": dose_conseillee or None,
        "reapplication_after_days": _to_int(payload.get("reapplication_after_days")),
        "delai_avant_tonte_jours": _to_int(payload.get("delai_avant_tonte_jours")),
        "phase_compatible": _split_csv_values(payload.get("phase_compatible")),
        "application_months": normalize_application_months(payload.get("application_months")),
        "note": note or None,
    }
    record = _merge_application_fields(record, payload, product_type or None)
    application_months_label = format_application_months_label(record.get("application_months"))
    if application_months_label:
        record["application_months_label"] = application_months_label
    clean = {key: value for key, value in record.items() if value not in (None, "", {}, [])}
    if not clean:
        return None
    return clean


def build_application_summary(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if not item:
        return None
    if item.get("type") not in PHASE_DURATIONS_DAYS:
        return None
    libelle = item.get("produit") or item.get("type")
    dose = item.get("dose")
    if isinstance(dose, str):
        dose = dose.strip()
    application_type = _application_type_for_item(item)
    application_requires_watering_after = _to_bool(item.get("application_requires_watering_after"))
    application_post_watering_mm = _to_float(item.get("application_post_watering_mm"))
    application_irrigation_block_hours = _to_float(item.get("application_irrigation_block_hours"))
    application_irrigation_delay_minutes = _to_float(item.get("application_irrigation_delay_minutes"))
    application_irrigation_mode = _normalize_application_irrigation_mode(item.get("application_irrigation_mode"))
    defaults = APPLICATION_DEFAULTS.get(str(item.get("type") or "").strip(), {})
    if application_type is None:
        application_type = defaults.get("application_type")
    if application_requires_watering_after is None:
        application_requires_watering_after = defaults.get("application_requires_watering_after")
    if application_post_watering_mm is None:
        application_post_watering_mm = defaults.get("application_post_watering_mm")
    if application_irrigation_block_hours is None:
        application_irrigation_block_hours = defaults.get("application_irrigation_block_hours")
    if application_irrigation_delay_minutes is None:
        application_irrigation_delay_minutes = defaults.get("application_irrigation_delay_minutes")
    if application_irrigation_mode is None:
        application_irrigation_mode = defaults.get("application_irrigation_mode")
    application_label_notes = item.get("application_label_notes")
    if application_label_notes in (None, ""):
        application_label_notes = defaults.get("application_label_notes")
    product_catalogue = item.get("produit_catalogue")
    application_months = normalize_application_months(item.get("application_months"))
    if not application_months and isinstance(product_catalogue, dict):
        application_months = normalize_application_months(product_catalogue.get("application_months"))
    application_months_label = format_application_months_label(application_months)
    declared_at = item.get("declared_at") or item.get("recorded_at")
    declared_dt = _parse_datetime(declared_at)
    application_block_until = None
    if declared_dt is not None and application_irrigation_block_hours is not None:
        if float(application_irrigation_block_hours) > 0:
            application_block_until = (
                declared_dt + timedelta(hours=float(application_irrigation_block_hours))
            ).isoformat()
    summary = {
        "produit_id": item.get("produit_id"),
        "libelle": libelle,
        "type": item.get("type"),
        "date": item.get("date"),
        "date_action": item.get("date"),
        "declared_at": declared_dt.isoformat() if declared_dt is not None else None,
        "produit": item.get("produit"),
        "dose": dose,
        "zone": item.get("zone"),
        "note": item.get("note"),
        "reapplication_after_days": _to_int(item.get("reapplication_after_days")),
        "source": item.get("source"),
        "application_type": application_type,
        "application_requires_watering_after": application_requires_watering_after,
        "application_post_watering_mm": application_post_watering_mm,
        "application_irrigation_block_hours": application_irrigation_block_hours,
        "application_irrigation_delay_minutes": application_irrigation_delay_minutes,
        "application_irrigation_mode": application_irrigation_mode,
        "application_label_notes": application_label_notes,
        "application_months": application_months or None,
        "application_months_label": application_months_label,
        "application_block_until": application_block_until,
    }
    clean = {key: value for key, value in summary.items() if value not in (None, "", {}, [])}
    return clean or None


def compute_application_state(
    history: list[dict[str, Any]],
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    history = [item for item in history if isinstance(item, dict)]
    latest_index = None
    latest_item = None
    for idx in range(len(history) - 1, -1, -1):
        item = history[idx]
        item_type = str(item.get("type") or "")
        if item_type not in APPLICATION_INTERVENTIONS and not any(
            item.get(key) not in (None, "", [], {})
            for key in (
                "application_type",
                "application_requires_watering_after",
                "application_post_watering_mm",
                "application_irrigation_block_hours",
                "application_irrigation_delay_minutes",
                "application_irrigation_mode",
                "application_label_notes",
                "produit",
                "dose",
                "reapplication_after_days",
            )
        ):
            continue
        latest_index = idx
        latest_item = item
        break

    if latest_item is None:
        return {
            "derniere_application": None,
            "application_type": None,
            "application_requires_watering_after": False,
            "application_post_watering_mm": 0.0,
            "application_irrigation_block_hours": 0.0,
            "application_irrigation_delay_minutes": 0.0,
            "application_irrigation_mode": None,
            "application_label_notes": None,
            "declared_at": None,
            "application_block_until": None,
            "application_block_active": False,
            "application_block_remaining_minutes": 0.0,
            "application_post_watering_pending": False,
            "application_post_watering_ready_at": None,
            "application_post_watering_delay_remaining_minutes": 0.0,
            "application_post_watering_ready": False,
            "application_post_watering_remaining_mm": 0.0,
        }

    summary = build_application_summary(latest_item)
    application_type = _application_type_for_item(latest_item)
    defaults = APPLICATION_DEFAULTS.get(str(latest_item.get("type") or "").strip(), {})
    application_requires_watering_after = _to_bool(latest_item.get("application_requires_watering_after"))
    if application_requires_watering_after is None:
        application_requires_watering_after = defaults.get("application_requires_watering_after", False)
    application_post_watering_mm = _to_float(latest_item.get("application_post_watering_mm"))
    if application_post_watering_mm is None:
        application_post_watering_mm = float(defaults.get("application_post_watering_mm", 0.0))
    application_irrigation_block_hours = _to_float(latest_item.get("application_irrigation_block_hours"))
    if application_irrigation_block_hours is None:
        application_irrigation_block_hours = float(defaults.get("application_irrigation_block_hours", 0.0))
    application_irrigation_delay_minutes = _to_float(latest_item.get("application_irrigation_delay_minutes"))
    if application_irrigation_delay_minutes is None:
        application_irrigation_delay_minutes = float(defaults.get("application_irrigation_delay_minutes", 0.0))
    application_irrigation_mode = _normalize_application_irrigation_mode(latest_item.get("application_irrigation_mode"))
    if application_irrigation_mode is None:
        application_irrigation_mode = defaults.get("application_irrigation_mode")
    application_label_notes = latest_item.get("application_label_notes") or defaults.get("application_label_notes")
    declared_dt = _parse_datetime(latest_item.get("declared_at") or latest_item.get("recorded_at") or latest_item.get("date"))
    application_block_until = None
    if declared_dt is not None and application_irrigation_block_hours and application_irrigation_block_hours > 0:
        application_block_until = (
            declared_dt + timedelta(hours=float(application_irrigation_block_hours))
        ).isoformat()
    application_block_active = False
    application_block_remaining_minutes = 0.0
    if application_block_until is not None:
        block_dt = _parse_datetime(application_block_until)
        if block_dt is not None:
            remaining = (block_dt - now).total_seconds() / 60.0
            if remaining > 0:
                application_block_active = True
                application_block_remaining_minutes = round(max(0.0, remaining), 1)

    application_post_watering_ready_at = None
    application_post_watering_delay_remaining_minutes = 0.0
    if declared_dt is not None and application_irrigation_delay_minutes is not None:
        delay_minutes = max(0.0, float(application_irrigation_delay_minutes))
        if delay_minutes > 0:
            application_post_watering_ready_at = (
                declared_dt + timedelta(minutes=delay_minutes)
            ).isoformat()
            ready_dt = _parse_datetime(application_post_watering_ready_at)
            if ready_dt is not None:
                remaining_delay = (ready_dt - now).total_seconds() / 60.0
                if remaining_delay > 0:
                    application_post_watering_delay_remaining_minutes = round(remaining_delay, 1)

    application_post_watering_ready = False
    if (
        application_type == APPLICATION_TYPE_SOL
        and application_requires_watering_after
        and not application_block_active
        and (application_irrigation_mode in {None, "", "auto", "manuel"})
    ):
        application_post_watering_ready = application_post_watering_delay_remaining_minutes <= 0.0

    water_after_application = 0.0
    if latest_index is not None:
        for item in history[latest_index + 1 :]:
            if item.get("type") != "arrosage":
                continue
            water_after_application += float(_watering_item_mm(item) or 0.0)
    application_post_watering_remaining_mm = max(
        0.0,
        float(application_post_watering_mm or 0.0) - water_after_application,
    )
    application_post_watering_pending = bool(
        application_type == APPLICATION_TYPE_SOL
        and application_requires_watering_after
        and application_post_watering_remaining_mm > 0.1
    )

    return {
        "derniere_application": summary,
        "application_type": application_type,
        "application_requires_watering_after": bool(application_requires_watering_after),
        "application_post_watering_mm": round(float(application_post_watering_mm or 0.0), 1),
        "application_irrigation_block_hours": round(float(application_irrigation_block_hours or 0.0), 1),
        "application_irrigation_delay_minutes": round(float(application_irrigation_delay_minutes or 0.0), 1),
        "application_irrigation_mode": application_irrigation_mode,
        "application_label_notes": application_label_notes,
        "date_action": latest_item.get("date"),
        "declared_at": declared_dt.isoformat() if declared_dt is not None else None,
        "application_block_until": application_block_until,
        "application_block_active": application_block_active,
        "application_block_remaining_minutes": application_block_remaining_minutes,
        "application_post_watering_pending": application_post_watering_pending,
        "application_post_watering_ready_at": application_post_watering_ready_at,
        "application_post_watering_delay_remaining_minutes": application_post_watering_delay_remaining_minutes,
        "application_post_watering_ready": application_post_watering_ready,
        "application_post_watering_remaining_mm": round(application_post_watering_remaining_mm, 1),
    }


def compute_next_reapplication_date(
    history: list[dict[str, Any]],
    today: date | None = None,
) -> str | None:
    today = today or date.today()
    latest = _latest_history_item(
        history,
        lambda item: item.get("reapplication_after_days") is not None
        and item.get("date")
        and item.get("type") in PHASE_DURATIONS_DAYS,
    )
    if latest is None:
        return None
    try:
        start = date.fromisoformat(str(latest.get("date")))
    except ValueError:
        return None
    delay = _to_int(latest.get("reapplication_after_days"))
    if delay is None:
        return None
    next_date = start + timedelta(days=max(delay, 0))
    if next_date < today:
        return next_date.isoformat()
    return next_date.isoformat()


def build_feedback_observation(
    history: list[dict[str, Any]],
    previous_memory: dict[str, Any] | None,
    decision: dict[str, Any] | None,
    today: date,
) -> dict[str, Any] | None:
    if not previous_memory:
        return None
    previous_advice = previous_memory.get("dernier_conseil")
    if not isinstance(previous_advice, dict):
        return None
    raw_date = previous_advice.get("date") or previous_memory.get("date_derniere_mise_a_jour")
    if not raw_date:
        return None
    try:
        advice_date = date.fromisoformat(str(raw_date)[:10])
    except ValueError:
        return None
    elapsed_days = (today - advice_date).days
    if elapsed_days not in {1, 2}:
        return None

    recommended_mm = _to_float(previous_advice.get("objectif_mm"))
    if recommended_mm is None:
        recommended_mm = _to_float(previous_advice.get("mm_final"))
    if recommended_mm is None:
        recommended_mm = _to_float(previous_advice.get("mm_final_recommande"))
    if recommended_mm is None:
        recommended_mm = 0.0

    observed_mm = compute_recent_watering_mm(history, today=today, days=elapsed_days)
    current_deficit = _to_float(
        (decision or {}).get("deficit_mm_ajuste")
        or (decision or {}).get("deficit_brut_mm")
        or (decision or {}).get("objectif_mm")
    )
    if current_deficit is None:
        current_deficit = 0.0

    feedback = {
        "window": f"{elapsed_days * 24}h",
        "recommended_mm": round(recommended_mm, 1),
        "observed_mm": round(observed_mm, 1),
        "delta_mm": round(observed_mm - recommended_mm, 1),
        "current_deficit_mm": round(current_deficit, 1),
        "current_risk": (decision or {}).get("risque_gazon"),
        "current_heat_stress_level": (decision or {}).get("heat_stress_level"),
        "current_type_arrosage": (decision or {}).get("type_arrosage"),
        "current_mm_final": _to_float((decision or {}).get("mm_final")),
        "source": "observation_only",
    }
    return {key: value for key, value in feedback.items() if value is not None}


def compute_memory(
    history: list[dict[str, Any]],
    current_phase: str | None = None,
    decision: dict[str, Any] | None = None,
    previous_memory: dict[str, Any] | None = None,
    today: date | None = None,
    significant_watering_threshold_mm: float = SIGNIFICANT_WATERING_THRESHOLD_MM,
) -> dict[str, Any]:
    today = today or date.today()
    history = [item for item in history if isinstance(item, dict)]

    last_mowing = _latest_history_item(history, lambda item: item.get("type") == "tonte")
    last_watering = _latest_history_item(history, lambda item: item.get("type") == "arrosage")
    last_significant_watering = _latest_history_item(
        history,
        lambda item: item.get("type") == "arrosage"
        and (_watering_item_mm(item) or 0.0) >= significant_watering_threshold_mm,
    )
    last_phase_event = _latest_history_item(
        history,
        lambda item: item.get("type") in PHASE_DURATIONS_DAYS and item.get("type") != "Normal",
    )

    if current_phase and current_phase != "Normal":
        last_phase_active = current_phase
    elif last_phase_event is not None:
        last_phase_active = str(last_phase_event.get("type"))
    elif previous_memory and previous_memory.get("derniere_phase_active"):
        last_phase_active = str(previous_memory.get("derniere_phase_active"))
    else:
        last_phase_active = "Normal"

    last_advice = previous_memory.get("dernier_conseil") if previous_memory else None
    if decision is not None:
        last_advice = {
            "date": today.isoformat(),
            "phase_active": current_phase or decision.get("phase_active"),
            "phase_dominante": decision.get("phase_dominante"),
            "sous_phase": decision.get("sous_phase"),
            "objectif_mm": decision.get("objectif_mm"),
            "decision_resume": decision.get("decision_resume"),
            "conseil_principal": decision.get("conseil_principal"),
            "action_recommandee": decision.get("action_recommandee"),
            "action_a_eviter": decision.get("action_a_eviter"),
            "niveau_action": decision.get("niveau_action"),
            "fenetre_optimale": decision.get("fenetre_optimale"),
            "risque_gazon": decision.get("risque_gazon"),
            "prochaine_reevaluation": decision.get("prochaine_reevaluation"),
            "raison_decision": decision.get("raison_decision"),
        }

    last_application = _latest_history_item(
        history,
        lambda item: item.get("type") in APPLICATION_INTERVENTIONS
        or item.get("application_type") is not None
        or item.get("reapplication_after_days") is not None
        or item.get("application_irrigation_delay_minutes") is not None
        or item.get("application_irrigation_mode") is not None
        or item.get("produit") is not None
        or item.get("dose") is not None,
    )
    application_state = compute_application_state(history, now=datetime.now(timezone.utc))
    feedback_observation = build_feedback_observation(history, previous_memory, decision, today=today)

    return {
        "historique_total": len(history),
        "derniere_tonte": last_mowing,
        "dernier_arrosage": last_watering,
        "dernier_arrosage_significatif": last_significant_watering,
        "derniere_phase_active": last_phase_active,
        "dernier_conseil": last_advice,
        "derniere_action_utilisateur": _normalize_user_action_summary(
            previous_memory.get("derniere_action_utilisateur") if previous_memory else None
        ),
        "derniere_application": build_application_summary(last_application),
        "application_type": application_state.get("application_type"),
        "application_requires_watering_after": application_state.get("application_requires_watering_after", False),
        "application_post_watering_mm": application_state.get("application_post_watering_mm", 0.0),
        "application_irrigation_block_hours": application_state.get("application_irrigation_block_hours", 0.0),
        "application_irrigation_delay_minutes": application_state.get("application_irrigation_delay_minutes", 0.0),
        "application_irrigation_mode": application_state.get("application_irrigation_mode"),
        "application_label_notes": application_state.get("application_label_notes"),
        "application_block_until": application_state.get("application_block_until"),
        "application_block_active": application_state.get("application_block_active", False),
        "application_block_remaining_minutes": application_state.get("application_block_remaining_minutes", 0.0),
        "application_post_watering_pending": application_state.get("application_post_watering_pending", False),
        "application_post_watering_ready_at": application_state.get("application_post_watering_ready_at"),
        "application_post_watering_delay_remaining_minutes": application_state.get(
            "application_post_watering_delay_remaining_minutes",
            0.0,
        ),
        "application_post_watering_ready": application_state.get("application_post_watering_ready", False),
        "application_post_watering_remaining_mm": application_state.get("application_post_watering_remaining_mm", 0.0),
        "auto_irrigation_enabled": bool(
            previous_memory.get("auto_irrigation_enabled", DEFAULT_AUTO_IRRIGATION_ENABLED)
            if previous_memory
            else DEFAULT_AUTO_IRRIGATION_ENABLED
        ),
        "feedback_observation": feedback_observation,
        "prochaine_reapplication": compute_next_reapplication_date(history, today=today),
        "date_derniere_mise_a_jour": today.isoformat(),
    }
