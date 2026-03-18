from __future__ import annotations

"""Logique pure liée à la tonte."""

from typing import Any

from .decision_models import DecisionContext
from .guidance import compute_tonte_statut


def build_mowing_bundle(
    context: DecisionContext,
    phase_bundle: dict[str, Any],
    water_bundle: dict[str, Any],
    risk_bundle: dict[str, Any],
) -> dict[str, Any]:
    score_tonte = int(risk_bundle["scores"]["score_tonte"])
    score_stress = int(risk_bundle["scores"]["score_stress"])
    tonte_ok = score_tonte < 45 and score_stress < 70
    if phase_bundle["phase_dominante"] in {"Sursemis", "Traitement", "Hivernage"}:
        tonte_ok = False
    if not tonte_ok:
        humidite = context.humidite or 0.0
        pluie_24h = context.pluie_24h or 0.0
        temperature = context.temperature or 0.0
        etp = water_bundle["etp"] or 0.0
        arrosage_recent = water_bundle["water_balance"].get("arrosage_recent", 0.0)
        if humidite >= 85:
            reason = "Humidité trop élevée: pelouse humide."
        elif pluie_24h >= 3:
            reason = "Pluie récente: sol encore humide."
        elif arrosage_recent > 0:
            reason = "Arrosage récent: attendre un ressuyage."
        elif temperature >= 30 and etp >= 4:
            reason = "Stress thermique élevé: limiter la tonte."
        else:
            reason = "Conditions défavorables à la tonte."
    else:
        reason = "Fenêtre tonte acceptable."

    tonte_statut = compute_tonte_statut(
        phase_dominante=phase_bundle["phase_dominante"],
        tonte_autorisee=tonte_ok,
        score_tonte=score_tonte,
        risque_gazon=risk_bundle["risque_gazon"],
    )

    return {
        "tonte_autorisee": tonte_ok,
        "tonte_statut": tonte_statut,
        "tonte_reason": reason,
        "score_tonte": score_tonte,
        "score_stress": score_stress,
    }
