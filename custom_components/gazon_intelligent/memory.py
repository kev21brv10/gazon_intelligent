from __future__ import annotations

from datetime import date, timedelta
from typing import Any

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


def _split_csv_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        items = value
    else:
        items = str(value).split(",")
    clean: list[str] = []
    for item in items:
        text = str(item).strip()
        if text:
            clean.append(text)
    return clean


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
        "note": note or None,
    }
    clean = {key: value for key, value in record.items() if value not in (None, "", {}, [])}
    if not clean:
        return None
    return clean


def build_product_summary(product: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(product, dict):
        return None
    summary = {
        "id": product.get("id"),
        "nom": product.get("nom"),
        "type": product.get("type"),
        "dose_conseillee": product.get("dose_conseillee"),
        "reapplication_after_days": _to_int(product.get("reapplication_after_days")),
        "delai_avant_tonte_jours": _to_int(product.get("delai_avant_tonte_jours")),
        "phase_compatible": product.get("phase_compatible"),
        "note": product.get("note"),
    }
    clean = {key: value for key, value in summary.items() if value not in (None, "", {}, [])}
    return clean or None


def build_application_summary(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if not item:
        return None
    if item.get("type") not in PHASE_DURATIONS_DAYS:
        return None
    libelle = item.get("produit") or item.get("type")
    dose = item.get("dose")
    if isinstance(dose, str):
        dose = dose.strip()
    summary = {
        "produit_id": item.get("produit_id"),
        "libelle": libelle,
        "type": item.get("type"),
        "date": item.get("date"),
        "produit": item.get("produit"),
        "dose": dose,
        "zone": item.get("zone"),
        "note": item.get("note"),
        "reapplication_after_days": _to_int(item.get("reapplication_after_days")),
        "source": item.get("source"),
    }
    clean = {key: value for key, value in summary.items() if value not in (None, "", {}, [])}
    return clean or None


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
        and (_to_float(item.get("objectif_mm")) or 0.0) >= significant_watering_threshold_mm,
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
        lambda item: item.get("reapplication_after_days") is not None
        or item.get("produit") is not None
        or item.get("dose") is not None,
    )
    if last_application is None:
        last_application = _latest_history_item(
            history,
            lambda item: item.get("type") in PHASE_DURATIONS_DAYS and item.get("type") != "Normal",
        )

    return {
        "historique_total": len(history),
        "derniere_tonte": last_mowing,
        "dernier_arrosage": last_watering,
        "dernier_arrosage_significatif": last_significant_watering,
        "derniere_phase_active": last_phase_active,
        "dernier_conseil": last_advice,
        "derniere_application": build_application_summary(last_application),
        "prochaine_reapplication": compute_next_reapplication_date(history, today=today),
        "date_derniere_mise_a_jour": today.isoformat(),
    }
