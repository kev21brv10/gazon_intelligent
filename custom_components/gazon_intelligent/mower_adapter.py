from __future__ import annotations

"""Normalisation générique des états de robot tondeuse Home Assistant."""

from datetime import date, datetime, timezone
from typing import Any

try:
    from homeassistant.util import dt as dt_util
except Exception:  # pragma: no cover - standalone fallback
    dt_util = None

_MOWER_STATE_ALIASES: dict[str, str] = {
    "mowing": "tonte_en_cours",
    "edgecut": "tonte_en_cours",
    "cutting": "tonte_en_cours",
    "in_operation": "tonte_en_cours",
    "working": "tonte_en_cours",
    "returning": "retour_station",
    "going_home": "retour_station",
    "homing": "retour_station",
    "paused": "pause",
    "pause": "pause",
    "stopped": "pause",
    "charging": "en_charge",
    "docked": "au_repos",
    "dock": "au_repos",
    "parked": "au_repos",
    "parked_timer": "au_repos",
    "idle": "au_repos",
    "standby": "au_repos",
    "home": "au_repos",
    "rain_delay": "pluie",
    "rain_delayed": "pluie",
    "weather_delay": "pluie",
    "error": "erreur",
    "trapped": "erreur",
    "unavailable": "indisponible",
    "unknown": "inconnu",
}

_NO_ERROR_VALUES = {
    "",
    "none",
    "ok",
    "no_error",
    "no error",
    "aucune",
    "aucune_erreur",
    "aucune erreur",
}

_RAIN_ERROR_VALUES = {
    "rain_delay",
    "rain_delayed",
    "weather_delay",
}

_BLOCKING_STATUSES = {
    "indisponible",
    "erreur",
    "pluie",
    "en_charge",
    "retour_station",
    "tonte_en_cours",
}

_STATUS_LABELS: dict[str, str] = {
    "indisponible": "Indisponible",
    "erreur": "Erreur",
    "pluie": "Pluie",
    "en_charge": "En charge",
    "tonte_en_cours": "Tonte en cours",
    "retour_station": "Retour station",
    "pause": "En pause",
    "au_repos": "Au repos",
    "inconnu": "Inconnu",
}


def _status_label(status: str, raw_state: Any) -> str | None:
    lowered = str(raw_state or "").strip().lower()
    if status == "tonte_en_cours" and lowered == "edgecut":
        return "Coupe des bordures"
    return _human_label(status)


def _clean_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _normalize_error_code(raw_error: Any) -> str | None:
    text = _clean_text(raw_error)
    if text is None:
        return None
    lowered = text.lower()
    if lowered in _NO_ERROR_VALUES:
        return None
    return lowered


def _human_label(value: str | None) -> str | None:
    if not value:
        return None
    if value in _STATUS_LABELS:
        return _STATUS_LABELS[value]
    return value.replace("_", " ").strip().capitalize()


def _local_timezone():
    if dt_util is not None:
        now_getter = getattr(dt_util, "now", None)
        if callable(now_getter):
            current = now_getter()
            if isinstance(current, datetime) and current.tzinfo is not None:
                return current.tzinfo
    current = datetime.now().astimezone()
    return current.tzinfo or timezone.utc


def _normalize_mower_status(
    raw_state: Any,
    *,
    charging: bool | None,
    rain: bool | None,
    error_code: str | None,
    available: bool,
) -> str:
    if not available:
        return "indisponible"
    if error_code in _RAIN_ERROR_VALUES or rain is True:
        return "pluie"
    if error_code is not None:
        return "erreur"
    if charging is True:
        return "en_charge"

    lowered = str(raw_state or "").strip().lower()
    if lowered in _MOWER_STATE_ALIASES:
        return _MOWER_STATE_ALIASES[lowered]
    if not lowered:
        return "inconnu"
    return "inconnu"


def _human_datetime_text(value: Any) -> str | None:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, datetime):
        dt_value = value
    elif isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt_value = datetime.fromisoformat(text)
        except ValueError:
            try:
                return date.fromisoformat(text[:10]).strftime("%d/%m/%Y")
            except ValueError:
                return text
    if dt_value.tzinfo is not None:
        dt_value = dt_value.astimezone(_local_timezone())
    return dt_value.strftime("%d/%m/%Y à %H:%M")


def derive_related_entity_id(source_entity_id: str | None, platform: str, suffix: str) -> str | None:
    """Dérive une entité associée à partir de l'identifiant de la tondeuse."""
    text = _clean_text(source_entity_id)
    if not text or "." not in text:
        return None
    _domain, object_id = text.split(".", 1)
    if not object_id:
        return None
    return f"{platform}.{object_id}_{suffix}"


def build_mower_context(
    *,
    entity_id: str | None,
    entity_name: str | None,
    raw_state: Any,
    available: bool,
    charging: bool | None = None,
    rain: bool | None = None,
    error_raw: Any = None,
    battery_percent: float | None = None,
    next_schedule_raw: Any = None,
    cutting_height_mm: float | None = None,
    resolution_state: str | None = None,
    resolution_reason: str | None = None,
    resolution_candidate_count: int | None = None,
) -> dict[str, Any]:
    """Construit un contexte tondeuse standardisé depuis des entités HA hétérogènes."""

    error_code = _normalize_error_code(error_raw)
    status = _normalize_mower_status(
        raw_state,
        charging=charging,
        rain=rain,
        error_code=error_code,
        available=available,
    )
    ready = status not in _BLOCKING_STATUSES and available
    reason = None
    if status == "pluie":
        reason = "Pluie ou délai pluie actif."
    elif status == "erreur":
        reason = _human_label(error_code) or "Erreur tondeuse."
    elif status == "indisponible":
        reason = "Tondeuse indisponible."
    elif status == "en_charge":
        reason = "Tondeuse en charge."
    elif status == "retour_station":
        reason = "Tondeuse en retour station."
    elif status == "tonte_en_cours":
        reason = "Tonte déjà en cours."
    elif status == "pause":
        reason = "Tonte en pause."

    payload: dict[str, Any] = {
        "tondeuse_source_entity": entity_id,
        "tondeuse_nom": entity_name,
        "tondeuse_etat_brut": _clean_text(raw_state),
        "tondeuse_statut": status,
        "tondeuse_statut_libelle": _status_label(status, raw_state),
        "tondeuse_connectee": bool(available),
        "tondeuse_prete": bool(ready),
        "tondeuse_raison": reason,
        "tondeuse_en_charge": charging,
        "tondeuse_pluie": rain,
        "tondeuse_erreur": error_code,
        "tondeuse_erreur_libelle": _human_label(error_code),
        "tondeuse_batterie": battery_percent,
        "tondeuse_prochain_depart": _clean_text(next_schedule_raw),
        "tondeuse_prochain_depart_display": _human_datetime_text(next_schedule_raw),
        "tondeuse_hauteur_coupe_mm": cutting_height_mm,
        "tondeuse_resolution_state": _clean_text(resolution_state),
        "tondeuse_resolution_reason": _clean_text(resolution_reason),
        "tondeuse_resolution_candidate_count": resolution_candidate_count,
    }
    return {key: value for key, value in payload.items() if value is not None}
