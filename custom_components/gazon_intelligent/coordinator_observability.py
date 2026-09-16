from __future__ import annotations

from datetime import date
from typing import Any

from .water import compute_recent_watering_mm


def extract_block_reason(snapshot: dict[str, Any]) -> str | None:
    """Motif de blocage compact pour l'observabilite."""
    reason = str(snapshot.get("block_reason") or snapshot.get("raison_decision") or "").strip()
    if not reason:
        return None
    lowered = reason.lower()
    for marker in (
        "pluie prévue suffisante",
        "pluie prévue",
        "humidité élevée",
        "garde-fou hebdomadaire",
        "mode bloqué",
        "arrosage bloqué",
        "post-produit",
        "application",
    ):
        if marker in lowered:
            return marker
    return reason


def etp_ecoulee_du_jour(soil_balance: Any, *, today: date) -> dict[str, Any]:
    """ET reellement debitee aujourd'hui, lue dans le journal du bilan sol."""
    vide: dict[str, Any] = {"etp_ecoulee_mm": None, "etp_jour_estime_mm": None}
    try:
        state = soil_balance or {}
        ledger = state.get("ledger") or []
        if not ledger:
            return vide
        entree = ledger[-1]
        if not isinstance(entree, dict):
            return vide
        if str(entree.get("date") or "") != today.isoformat():
            return vide
        return {
            "etp_ecoulee_mm": entree.get("etp_elapsed_mm"),
            "etp_jour_estime_mm": entree.get("etp_mm"),
        }
    except (AttributeError, TypeError, ValueError, IndexError):
        return vide


def build_observability_payload(
    snapshot: dict[str, Any],
    *,
    history: list[dict[str, Any]],
    today: date,
    feedback_observation: Any,
) -> dict[str, Any]:
    """Payload compact journalise en debug pour comprendre la decision courante."""
    payload = {
        "phase": snapshot.get("phase_active"),
        "sous_phase": snapshot.get("sous_phase"),
        "watering_cause": snapshot.get("watering_cause"),
        "type_arrosage": snapshot.get("type_arrosage"),
        "deficit_brut_mm": snapshot.get("deficit_brut_mm"),
        "deficit_mm_ajuste": snapshot.get("deficit_mm_ajuste"),
        "mm_cible": snapshot.get("mm_cible"),
        "mm_final": snapshot.get("mm_final"),
        "mm_requested": snapshot.get("mm_requested"),
        "mm_applied": snapshot.get("mm_applied"),
        "mm_detected": snapshot.get("mm_detected"),
        "mm_applied_today": round(compute_recent_watering_mm(history, today=today, days=0), 1),
        "mm_detected_24h": round(compute_recent_watering_mm(history, today=today, days=1), 1),
        "mm_detected_48h": round(compute_recent_watering_mm(history, today=today, days=2), 1),
        "heat_stress_level": snapshot.get("heat_stress_level"),
        "heat_stress_phase": snapshot.get("heat_stress_phase"),
        "confidence_level": snapshot.get("niveau_confiance"),
        "confidence_score": snapshot.get("confidence_score"),
        "block_reason": extract_block_reason(snapshot),
        "weekly_guardrail_mm_min": snapshot.get("weekly_guardrail_mm_min"),
        "weekly_guardrail_mm_max": snapshot.get("weekly_guardrail_mm_max"),
        "soil_profile": snapshot.get("soil_profile"),
        "soil_retention_factor": snapshot.get("soil_retention_factor"),
        "soil_drainage_factor": snapshot.get("soil_drainage_factor"),
        "soil_infiltration_factor": snapshot.get("soil_infiltration_factor"),
        "soil_need_factor": snapshot.get("soil_need_factor"),
        "feedback_observation": feedback_observation,
    }
    return {key: value for key, value in payload.items() if value is not None}
