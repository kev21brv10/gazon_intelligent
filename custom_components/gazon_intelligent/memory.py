from __future__ import annotations

from datetime import date
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

    return {
        "historique_total": len(history),
        "derniere_tonte": last_mowing,
        "dernier_arrosage": last_watering,
        "dernier_arrosage_significatif": last_significant_watering,
        "derniere_phase_active": last_phase_active,
        "dernier_conseil": last_advice,
        "date_derniere_mise_a_jour": today.isoformat(),
    }
