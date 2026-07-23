from __future__ import annotations

"""Logique pure liée à la phase et à la sous-phase."""

from datetime import date
from typing import Any

from homeassistant.util import dt as dt_util

from .decision_models import DecisionContext
from .guidance import compute_jours_restants_for
from .phases import compute_dominant_phase, compute_subphase


def _safe_phase_name(value: Any) -> str:
    text = str(value or "").strip()
    return text or "Normal"


def _safe_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _safe_int(value: Any, default: int = 0, minimum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if minimum is not None:
        parsed = max(minimum, parsed)
    return parsed


def _safe_progression(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = 0.0
    return max(0.0, min(parsed, 100.0))


def build_phase_bundle(context: DecisionContext) -> dict[str, Any]:
    dominant = compute_dominant_phase(
        context.history,
        today=context.today,
    )
    phase_dominante = _safe_phase_name(dominant.get("phase_dominante"))
    date_debut = _safe_date(dominant.get("date_debut"))
    date_fin = _safe_date(dominant.get("date_fin"))
    subphase = compute_subphase(
        phase_dominante=phase_dominante,
        date_debut=date_debut,
        date_fin=date_fin,
        today=context.today,
        now=dt_util.now(),
    )
    jours_restants = compute_jours_restants_for(
        phase_dominante=phase_dominante,
        date_fin=date_fin,
        today=context.today,
    )
    phase_age_days = _safe_int(dominant.get("age_jours"), default=0, minimum=0)
    sous_phase_age = _safe_int(subphase.get("age_jours"), default=0, minimum=0)
    sous_phase_progression = _safe_progression(subphase.get("progression"))

    raw_source = dominant.get("source")
    phase_source = raw_source if isinstance(raw_source, str) and raw_source else "inconnu"
    raw_detail = subphase.get("detail")
    sous_phase_detail = raw_detail if isinstance(raw_detail, str) and raw_detail else phase_dominante

    return {
        "phase_dominante": phase_dominante,
        "phase_dominante_source": phase_source,
        "date_action": date_debut.isoformat() if date_debut else None,
        "date_fin": date_fin.isoformat() if date_fin else None,
        "phase_age_days": phase_age_days,
        "sous_phase": subphase.get("sous_phase") or phase_dominante,
        "sous_phase_detail": sous_phase_detail,
        "sous_phase_age_days": sous_phase_age,
        "sous_phase_progression": sous_phase_progression,
        "jours_restants": max(0, jours_restants),
    }
