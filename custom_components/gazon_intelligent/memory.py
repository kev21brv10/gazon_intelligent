from __future__ import annotations

import ast
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from typing import Any

try:
    from homeassistant.util import dt as dt_util
except Exception:  # pragma: no cover - standalone fallback
    dt_util = None

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
    DEFAULT_AUTO_MOWING_DECLARATION_ENABLED,
    DEFAULT_AUTO_MOWING_DECLARATION_MINUTES,
    DEFAULT_EVENING_COOLING_ENABLED,
    DEFAULT_MOWER_COORDINATION_ENABLED,
    DEFAULT_MOWING_COOLDOWN_AFTER_WATERING_MINUTES,
    POST_APPLICATION_STATUS_ALIASES,
    POST_APPLICATION_STATUS_INDISPONIBLE,
    POST_APPLICATION_STATUS_NON_REQUIS,
    POST_APPLICATION_STATUS_EN_ATTENTE,
    POST_APPLICATION_STATUS_AUTORISE,
    POST_APPLICATION_STATUS_TERMINE,
    POST_APPLICATION_STATUS_BLOQUE,
    POST_APPLICATION_STATUSES,
    PRODUCT_USAGE_MODES,
)
from .phases import PHASE_DURATIONS_DAYS, SIGNIFICANT_WATERING_THRESHOLD_MM
from .water import _watering_item_mm, compute_recent_watering_mm

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


def _current_datetime() -> datetime:
    if dt_util is not None:
        now_getter = getattr(dt_util, "now", None)
        if callable(now_getter):
            current = now_getter()
            if isinstance(current, datetime):
                return current
    return datetime.now(timezone.utc)


def _current_date() -> date:
    return _current_datetime().date()


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


def normalize_post_application_status(value: Any) -> str:
    if value in (None, "", [], {}):
        return POST_APPLICATION_STATUS_INDISPONIBLE
    normalized = _normalize_text(value)
    normalized = POST_APPLICATION_STATUS_ALIASES.get(normalized, normalized)
    if normalized in POST_APPLICATION_STATUSES:
        return normalized
    return POST_APPLICATION_STATUS_INDISPONIBLE


def _normalize_usage_mode(value: Any) -> str | None:
    if value in (None, "", [], {}):
        return None
    normalized = _normalize_text(value)
    if normalized in PRODUCT_USAGE_MODES:
        return normalized
    aliases = {
        "preventive": "preventif",
        "preventif": "preventif",
        "curative": "curatif",
        "entretien": "entretien",
        "maintenance": "entretien",
        "rattrapage": "rattrapage",
    }
    return aliases.get(normalized)


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


def _is_application_relevant_item(item: dict[str, Any]) -> bool:
    # Garde de robustesse : l'historique peut contenir un élément non-dict (ex. `.storage`
    # corrompue). Sans lui, `.get` lèverait une AttributeError. Fonction de référence unique —
    # gazon_brain délègue ici (elle avait un DOUBLON qui, lui, portait déjà ce garde).
    if not isinstance(item, dict):
        return False
    item_type = str(item.get("type") or "")
    if item_type in APPLICATION_INTERVENTIONS:
        return True
    return any(
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
    )


def _latest_application_item(
    history: list[dict[str, Any]],
) -> tuple[int | None, dict[str, Any] | None]:
    for idx in range(len(history) - 1, -1, -1):
        item = history[idx]
        if _is_application_relevant_item(item):
            return idx, item
    return None, None


def _application_runtime_fields(item: dict[str, Any]) -> dict[str, Any]:
    item_type = str(item.get("type") or "").strip()
    defaults = APPLICATION_DEFAULTS.get(item_type, {})
    product_catalogue = item.get("produit_catalogue")
    application_months = normalize_application_months(item.get("application_months"))
    if not application_months and isinstance(product_catalogue, dict):
        application_months = normalize_application_months(product_catalogue.get("application_months"))
    declared_dt = _parse_datetime(item.get("declared_at") or item.get("recorded_at") or item.get("date"))
    application_type = _application_type_for_item(item)
    application_requires_watering_after = _to_bool(item.get("application_requires_watering_after"))
    if application_requires_watering_after is None:
        application_requires_watering_after = defaults.get("application_requires_watering_after", False)
    application_post_watering_mm = _to_float(item.get("application_post_watering_mm"))
    if application_post_watering_mm is None:
        application_post_watering_mm = float(defaults.get("application_post_watering_mm", 0.0))
    application_irrigation_block_hours = _to_float(item.get("application_irrigation_block_hours"))
    if application_irrigation_block_hours is None:
        application_irrigation_block_hours = float(defaults.get("application_irrigation_block_hours", 0.0))
    application_irrigation_delay_minutes = _to_float(item.get("application_irrigation_delay_minutes"))
    if application_irrigation_delay_minutes is None:
        application_irrigation_delay_minutes = float(defaults.get("application_irrigation_delay_minutes", 0.0))
    application_irrigation_mode = _normalize_application_irrigation_mode(item.get("application_irrigation_mode"))
    if application_irrigation_mode is None:
        application_irrigation_mode = defaults.get("application_irrigation_mode")
    application_label_notes = item.get("application_label_notes") or defaults.get("application_label_notes")
    application_block_until = None
    if declared_dt is not None and application_irrigation_block_hours and application_irrigation_block_hours > 0:
        application_block_until = (
            declared_dt + timedelta(hours=float(application_irrigation_block_hours))
        ).isoformat()
    return {
        "application_type": application_type,
        "application_requires_watering_after": bool(application_requires_watering_after),
        "application_post_watering_mm": float(application_post_watering_mm or 0.0),
        "application_irrigation_block_hours": float(application_irrigation_block_hours or 0.0),
        "application_irrigation_delay_minutes": float(application_irrigation_delay_minutes or 0.0),
        "application_irrigation_mode": application_irrigation_mode,
        "application_label_notes": application_label_notes,
        "application_months": application_months or None,
        "application_months_label": format_application_months_label(application_months),
        "declared_dt": declared_dt,
        "application_block_until": application_block_until,
    }


def _compute_application_block_state(
    application_block_until: str | None,
    now: datetime,
) -> dict[str, Any]:
    application_block_active = False
    application_block_remaining_minutes = 0.0
    if application_block_until is not None:
        block_dt = _parse_datetime(application_block_until)
        if block_dt is not None:
            remaining = (block_dt - now).total_seconds() / 60.0
            if remaining > 0:
                application_block_active = True
                application_block_remaining_minutes = round(max(0.0, remaining), 1)
    return {
        "application_block_active": application_block_active,
        "application_block_remaining_minutes": application_block_remaining_minutes,
    }


def _compute_post_watering_state(
    runtime_fields: dict[str, Any],
    now: datetime,
    water_after_application: float,
    application_block_active: bool,
    application_date: date | None = None,
    reference_date: date | None = None,
) -> dict[str, Any]:
    declared_dt = runtime_fields.get("declared_dt")
    application_type = runtime_fields.get("application_type")
    application_requires_watering_after = bool(runtime_fields.get("application_requires_watering_after"))
    application_post_watering_mm = float(runtime_fields.get("application_post_watering_mm") or 0.0)
    application_irrigation_delay_minutes = float(runtime_fields.get("application_irrigation_delay_minutes") or 0.0)
    application_irrigation_mode = runtime_fields.get("application_irrigation_mode")

    application_post_watering_ready_at = None
    application_post_watering_delay_remaining_minutes = 0.0
    if declared_dt is not None and application_irrigation_delay_minutes > 0:
        application_post_watering_ready_at = (
            declared_dt + timedelta(minutes=application_irrigation_delay_minutes)
        ).isoformat()
        ready_dt = _parse_datetime(application_post_watering_ready_at)
        if ready_dt is not None:
            remaining_delay = (ready_dt - now).total_seconds() / 60.0
            if remaining_delay > 0:
                application_post_watering_delay_remaining_minutes = round(remaining_delay, 1)

    application_post_watering_remaining_mm = max(
        0.0,
        application_post_watering_mm - water_after_application,
    )
    # L'arrosage technique d'incorporation n'a de sens que le jour même de l'épandage.
    # Pour une application plus ancienne (ex. déclarée rétroactivement), l'incorporation
    # est présumée faite → on éteint le pending (et donc conseil, override, arrosage auto).
    # Référence = le `today` de la décision (et non l'horloge murale) ; à défaut, now.date().
    # Date d'application absente = traitée comme « aujourd'hui » (non-régression sans date).
    reference_date = reference_date if reference_date is not None else now.date()
    applied_today = application_date is None or application_date == reference_date
    application_post_watering_pending = bool(
        application_type == APPLICATION_TYPE_SOL
        and application_requires_watering_after
        and application_post_watering_remaining_mm > 0.1
        and applied_today
    )
    application_post_watering_ready = bool(
        application_type == APPLICATION_TYPE_SOL
        and application_requires_watering_after
        and application_post_watering_pending
        and not application_block_active
        and (application_irrigation_mode in {None, "", "auto", "manuel"})
        and application_post_watering_delay_remaining_minutes <= 0.0
    )
    application_post_watering_status = POST_APPLICATION_STATUS_NON_REQUIS
    if application_block_active:
        application_post_watering_status = POST_APPLICATION_STATUS_BLOQUE
    elif application_requires_watering_after:
        if application_post_watering_pending and application_post_watering_ready:
            application_post_watering_status = POST_APPLICATION_STATUS_AUTORISE
        elif application_post_watering_pending:
            application_post_watering_status = POST_APPLICATION_STATUS_EN_ATTENTE
        else:
            application_post_watering_status = POST_APPLICATION_STATUS_TERMINE

    return {
        "application_post_watering_status": normalize_post_application_status(application_post_watering_status),
        "application_post_watering_pending": application_post_watering_pending,
        "application_post_watering_ready_at": application_post_watering_ready_at,
        "application_post_watering_delay_remaining_minutes": application_post_watering_delay_remaining_minutes,
        "application_post_watering_ready": application_post_watering_ready,
        "application_post_watering_remaining_mm": round(application_post_watering_remaining_mm, 1),
    }


def _default_application_state() -> dict[str, Any]:
    return {
        "derniere_application": None,
        "application_type": None,
        "application_requires_watering_after": False,
        "application_post_watering_mm": 0.0,
        "application_irrigation_block_hours": 0.0,
        "application_irrigation_delay_minutes": 0.0,
        "application_irrigation_mode": None,
        "application_label_notes": None,
        "application_post_watering_status": "indisponible",
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
        "usage_mode": _normalize_usage_mode(payload.get("usage_mode")),
        "max_applications_per_year": _to_int(payload.get("max_applications_per_year")),
        "reapplication_after_days": _to_int(payload.get("reapplication_after_days")),
        "delai_avant_tonte_jours": _to_int(payload.get("delai_avant_tonte_jours")),
        "phase_compatible": _split_csv_values(payload.get("phase_compatible")),
        "application_months": normalize_application_months(payload.get("application_months")),
        "temperature_min": _to_float(payload.get("temperature_min")),
        "temperature_max": _to_float(payload.get("temperature_max")),
        "note": note or None,
    }
    # Les valeurs ont déjà été normalisées par `_to_int`/`_to_float` juste au-dessus ; on relit
    # dans une variable locale plutôt que dans le dict hétérogène, pour que la garde soit lisible
    # (et vérifiable) sans reconvertir.
    _max_apps = record.get("max_applications_per_year")
    if isinstance(_max_apps, (int, float)) and _max_apps < 0:
        record["max_applications_per_year"] = None
    _t_min = record.get("temperature_min")
    _t_max = record.get("temperature_max")
    if (
        isinstance(_t_min, (int, float))
        and isinstance(_t_max, (int, float))
        and _t_min > _t_max
    ):
        record["temperature_min"], record["temperature_max"] = (
            record["temperature_max"],
            record["temperature_min"],
        )
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
    runtime_fields = _application_runtime_fields(item)
    libelle = item.get("produit") or item.get("type")
    dose = item.get("dose")
    if isinstance(dose, str):
        dose = dose.strip()
    summary = {
        "produit_id": item.get("produit_id"),
        "libelle": libelle,
        "type": item.get("type"),
        "date": item.get("date"),
        "date_action": item.get("date"),
        "declared_at": runtime_fields["declared_dt"].isoformat() if runtime_fields["declared_dt"] is not None else None,
        "produit": item.get("produit"),
        "dose": dose,
        "zone": item.get("zone"),
        "note": item.get("note"),
        "reapplication_after_days": _to_int(item.get("reapplication_after_days")),
        "source": item.get("source"),
        "application_type": runtime_fields["application_type"],
        "application_requires_watering_after": runtime_fields["application_requires_watering_after"],
        "application_post_watering_mm": runtime_fields["application_post_watering_mm"],
        "application_irrigation_block_hours": runtime_fields["application_irrigation_block_hours"],
        "application_irrigation_delay_minutes": runtime_fields["application_irrigation_delay_minutes"],
        "application_irrigation_mode": runtime_fields["application_irrigation_mode"],
        "application_label_notes": runtime_fields["application_label_notes"],
        "application_months": runtime_fields["application_months"],
        "application_months_label": runtime_fields["application_months_label"],
        "application_block_until": runtime_fields["application_block_until"],
    }
    clean = {key: value for key, value in summary.items() if value not in (None, "", {}, [])}
    return clean or None


def compute_application_state(
    history: list[dict[str, Any]],
    now: datetime | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    now = now or _current_datetime()
    history = [item for item in history if isinstance(item, dict)]
    latest_index, latest_item = _latest_application_item(history)

    if latest_item is None:
        return _default_application_state()

    summary = build_application_summary(latest_item)
    runtime_fields = _application_runtime_fields(latest_item)
    block_state = _compute_application_block_state(runtime_fields["application_block_until"], now)

    water_after_application = 0.0
    if latest_index is not None:
        for item in history[latest_index + 1 :]:
            if item.get("type") != "arrosage":
                continue
            water_after_application += float(_watering_item_mm(item) or 0.0)
    application_dt = _parse_datetime(latest_item.get("date"))
    application_date = application_dt.date() if application_dt is not None else None
    post_watering_state = _compute_post_watering_state(
        runtime_fields,
        now=now,
        water_after_application=water_after_application,
        application_block_active=bool(block_state["application_block_active"]),
        application_date=application_date,
        reference_date=today,
    )

    return {
        "derniere_application": summary,
        "application_type": runtime_fields["application_type"],
        "application_requires_watering_after": runtime_fields["application_requires_watering_after"],
        "application_post_watering_mm": round(runtime_fields["application_post_watering_mm"], 1),
        "application_irrigation_block_hours": round(runtime_fields["application_irrigation_block_hours"], 1),
        "application_irrigation_delay_minutes": round(runtime_fields["application_irrigation_delay_minutes"], 1),
        "application_irrigation_mode": runtime_fields["application_irrigation_mode"],
        "application_label_notes": runtime_fields["application_label_notes"],
        "application_post_watering_status": post_watering_state["application_post_watering_status"],
        "date_action": latest_item.get("date"),
        "declared_at": runtime_fields["declared_dt"].isoformat() if runtime_fields["declared_dt"] is not None else None,
        "application_block_until": runtime_fields["application_block_until"],
        "application_block_active": block_state["application_block_active"],
        "application_block_remaining_minutes": block_state["application_block_remaining_minutes"],
        "application_post_watering_pending": post_watering_state["application_post_watering_pending"],
        "application_post_watering_ready_at": post_watering_state["application_post_watering_ready_at"],
        "application_post_watering_delay_remaining_minutes": post_watering_state[
            "application_post_watering_delay_remaining_minutes"
        ],
        "application_post_watering_ready": post_watering_state["application_post_watering_ready"],
        "application_post_watering_remaining_mm": post_watering_state["application_post_watering_remaining_mm"],
    }


def compute_next_reapplication_date(
    history: list[dict[str, Any]],
    today: date | None = None,
) -> str | None:
    # Best-effort rule: keep the latest dated application carrying an explicit
    # reapplication delay, even if older interventions also define one.
    today = today or _current_date()
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
    # `or` INTERDIT ici : un `deficit_mm_ajuste` NUL est parfaitement légitime — c'est
    # `max(0, brut − pluie_support − …)`, donc « il va pleuvoir demain, plus rien à combler ».
    # La chaîne `or` le traitait comme absent et retombait sur le déficit BRUT : le message
    # d'apprentissage annonçait « il reste 4,6 mm » alors que le moteur avait conclu à 0.
    _decision = decision or {}
    current_deficit = None
    for _cle in ("deficit_mm_ajuste", "deficit_brut_mm", "objectif_mm"):
        _valeur = _to_float(_decision.get(_cle))
        if _valeur is not None:
            current_deficit = _valeur
            break
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


def _reglage_entier(
    previous_memory: dict[str, Any] | None,
    cle: str,
    defaut: int,
    *,
    minimum: int,
) -> int:
    """Reconduit un réglage utilisateur ENTIER d'un cycle à l'autre.

    Même rôle que les `bool(previous_memory.get(...))` voisins, mais pour un nombre : une
    valeur illisible (None, texte, NaN) retombe sur le défaut plutôt que de propager une
    saleté qu'un curseur afficherait ensuite.
    """
    if not previous_memory:
        return defaut
    try:
        return max(minimum, int(float(previous_memory.get(cle, defaut))))
    except (TypeError, ValueError):
        return defaut


def compute_memory(
    history: list[dict[str, Any]],
    current_phase: str | None = None,
    decision: dict[str, Any] | None = None,
    previous_memory: dict[str, Any] | None = None,
    today: date | None = None,
    significant_watering_threshold_mm: float = SIGNIFICANT_WATERING_THRESHOLD_MM,
) -> dict[str, Any]:
    """Consolide la mémoire persistée et la reconstruit au mieux depuis l'historique.

    Cette mémoire reste volontairement best-effort: elle fusionne l'historique,
    la mémoire précédente et la décision courante pour produire un état public
    stable sans changer le contrat observable du moteur.
    """
    today = today or _current_date()
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

    _, last_application = _latest_application_item(history)
    application_state = compute_application_state(history, now=_current_datetime(), today=today)
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
        "application_post_watering_status": application_state.get("application_post_watering_status"),
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
        "mower_coordination_enabled": bool(
            previous_memory.get(
                "mower_coordination_enabled",
                DEFAULT_MOWER_COORDINATION_ENABLED,
            )
            if previous_memory
            else DEFAULT_MOWER_COORDINATION_ENABLED
        ),
        # compute_memory RECONSTRUIT la mémoire à chaque cycle (toutes les 2 min) : tout réglage
        # utilisateur absent de ce dict est PERDU, et l'entité repart sur sa valeur par défaut.
        # Sans cette ligne, couper le rafraîchissement du soir ne tenait pas : le switch se
        # rallumait tout seul au refresh suivant. Toute nouvelle option persistée doit être
        # reconduite ici (cf. tests/test_memory.py::PersistedSettingsSurviveComputeMemoryTests).
        "evening_cooling_enabled": bool(
            previous_memory.get(
                "evening_cooling_enabled",
                DEFAULT_EVENING_COOLING_ENABLED,
            )
            if previous_memory
            else DEFAULT_EVENING_COOLING_ENABLED
        ),
        "auto_mowing_declaration_enabled": bool(
            previous_memory.get(
                "auto_mowing_declaration_enabled",
                DEFAULT_AUTO_MOWING_DECLARATION_ENABLED,
            )
            if previous_memory
            else DEFAULT_AUTO_MOWING_DECLARATION_ENABLED
        ),
        # ⚠️ LES RÉGLAGES NUMÉRIQUES SE PERDAIENT AUSSI — et personne ne l'avait vu, parce que
        # la garde ci-dessus (et son test) ne couvrait que des booléens.
        # `mowing_cooldown_after_watering_minutes` est dans ce cas DEPUIS SA LIVRAISON : le
        # curseur « Délai reprise tonte après arrosage » revenait à 180 min au cycle suivant,
        # soit deux minutes après chaque réglage. Vérifié en exécution le 08/08/2026.
        "mowing_cooldown_after_watering_minutes": _reglage_entier(
            previous_memory,
            "mowing_cooldown_after_watering_minutes",
            DEFAULT_MOWING_COOLDOWN_AFTER_WATERING_MINUTES,
            minimum=0,
        ),
        "auto_mowing_declaration_minutes": _reglage_entier(
            previous_memory,
            "auto_mowing_declaration_minutes",
            DEFAULT_AUTO_MOWING_DECLARATION_MINUTES,
            minimum=1,
        ),
        "feedback_observation": feedback_observation,
        "prochaine_reapplication": compute_next_reapplication_date(history, today=today),
        "date_derniere_mise_a_jour": today.isoformat(),
    }
