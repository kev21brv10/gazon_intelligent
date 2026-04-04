from __future__ import annotations

"""Logique pure liée à la phase et à la sous-phase."""

from typing import Any

from homeassistant.util import dt as dt_util

from .decision_models import DecisionContext
from .guidance import compute_jours_restants_for
from .phases import compute_dominant_phase, compute_subphase


def build_phase_bundle(context: DecisionContext) -> dict[str, Any]:
    dominant = compute_dominant_phase(
        context.history,
        today=context.today,
        temperature=context.temperature,
    )
    phase_dominante = dominant["phase_dominante"]
    date_debut = dominant["date_debut"]
    date_fin = dominant["date_fin"]
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
    return {
        "phase_dominante": phase_dominante,
        "phase_dominante_source": dominant["source"],
        "date_action": date_debut,
        "date_fin": date_fin,
        "phase_age_days": dominant["age_jours"],
        "sous_phase": subphase["sous_phase"],
        "sous_phase_detail": subphase["detail"],
        "sous_phase_age_days": subphase["age_jours"],
        "sous_phase_progression": subphase["progression"],
        "jours_restants": jours_restants,
    }
