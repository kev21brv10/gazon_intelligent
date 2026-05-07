from __future__ import annotations

"""Référentiel des phases métier.

`Hivernage` est volontairement traité comme un mode explicite:
- il reste présent dans l'historique et les règles de priorité/sous-phase
- il n'est plus activé implicitement par la météo ou la saison
- hors phase active connue, le moteur retombe sur `Normal`
"""

from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.util import dt as dt_util

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

PHASE_PRIORITIES: dict[str, int] = {
    "Normal": 0,
    "Traitement": 100,
    "Hivernage": 95,
    "Sursemis": 90,
    "Scarification": 80,
    "Fertilisation": 70,
    "Agent Mouillant": 60,
    "Biostimulant": 50,
}

SUBPHASE_RULES: dict[str, list[tuple[int, str]]] = {
    "Sursemis": [
        (7, "Germination"),
        (14, "Enracinement"),
        (999, "Reprise"),
    ],
    "Traitement": [
        (1, "Application"),
        (2, "Rémanence"),
        (999, "Suivi"),
    ],
    "Fertilisation": [
        (1, "Réponse"),
        (3, "Assimilation"),
        (999, "Stabilisation"),
    ],
    "Biostimulant": [
        (1, "Réponse"),
        (2, "Consolidation"),
        (999, "Stabilisation"),
    ],
    "Agent Mouillant": [
        (1, "Pénétration"),
        (3, "Répartition"),
        (999, "Stabilisation"),
    ],
    "Scarification": [
        (2, "Cicatrisation"),
        (5, "Reprise"),
        (999, "Stabilisation"),
    ],
    "Hivernage": [(999, "Repos")],
    "Normal": [(999, "Normal")],
}

SIGNIFICANT_WATERING_THRESHOLD_MM = 2.0


def phase_duration_days(phase: str) -> int:
    return PHASE_DURATIONS_DAYS.get(phase, 0)


def _validate_phase_referentials() -> None:
    duration_keys = set(PHASE_DURATIONS_DAYS)
    priority_keys = set(PHASE_PRIORITIES)
    subphase_keys = set(SUBPHASE_RULES)

    missing_subphases = duration_keys - subphase_keys
    if missing_subphases:
        raise ValueError(
            "SUBPHASE_RULES incomplet pour les phases: "
            + ", ".join(sorted(missing_subphases))
        )

    required_priorities = {phase for phase in duration_keys if phase != "Normal"}
    missing_priorities = required_priorities - priority_keys
    if missing_priorities:
        raise ValueError(
            "PHASE_PRIORITIES incomplet pour les phases: "
            + ", ".join(sorted(missing_priorities))
        )

    unknown_priorities = priority_keys - duration_keys
    if unknown_priorities:
        raise ValueError(
            "PHASE_PRIORITIES contient des phases inconnues: "
            + ", ".join(sorted(unknown_priorities))
        )

    unknown_subphases = subphase_keys - duration_keys
    if unknown_subphases:
        raise ValueError(
            "SUBPHASE_RULES contient des phases inconnues: "
            + ", ".join(sorted(unknown_subphases))
        )


def compute_phase_active(
    history: list[dict[str, Any]],
    today: date | None = None,
    temperature: float | None = None,
) -> tuple[str, date | None, date | None]:
    dominant = compute_dominant_phase(history, today=today, temperature=temperature)
    return dominant["phase_dominante"], dominant["date_debut"], dominant["date_fin"]


def compute_dominant_phase(
    history: list[dict[str, Any]],
    today: date | None = None,
    temperature: float | None = None,
) -> dict[str, Any]:
    today = today or dt_util.now().date()
    best: tuple[int, date] | None = None
    dominant: dict[str, Any] | None = None

    for item in history:
        if not isinstance(item, dict):
            continue
        phase = item.get("type")
        if phase not in PHASE_DURATIONS_DAYS or phase == "Normal":
            continue
        raw_date = item.get("date")
        if not raw_date:
            continue
        try:
            start = date.fromisoformat(str(raw_date))
        except ValueError:
            continue
        if start > today:
            continue
        duration_days = max(phase_duration_days(phase), 0)
        end = start + timedelta(days=max(duration_days - 1, 0))
        if today > end:
            continue
        priority = PHASE_PRIORITIES.get(phase, 0)
        rank = (priority, start)
        if best is None or rank > best:
            best = rank
            age_days = max((today - start).days, 0)
            dominant = {
                "phase_dominante": phase,
                "date_debut": start,
                "date_fin": end,
                "age_jours": age_days,
                "source": "historique_actif",
            }

    if dominant is None:
        return {
            "phase_dominante": "Normal",
            "date_debut": None,
            "date_fin": None,
            "age_jours": 0,
            "source": "absence_phase",
        }

    dominant["source"] = "historique_actif"
    return dominant


def compute_subphase(
    phase_dominante: str,
    date_debut: date | None,
    date_fin: date | None,
    today: date | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    today = today or dt_util.now().date()
    if now is None:
        now = dt_util.now()
    elif now.tzinfo is None:
        now = now.replace(tzinfo=dt_util.now().tzinfo)
    age_jours = 0
    progression = 0.0
    if date_debut is not None:
        age_jours = max((today - date_debut).days, 0)
    if date_debut is not None and date_fin is not None:
        total = max((date_fin - date_debut).days + 1, 1)
        start_dt = datetime.combine(date_debut, datetime.min.time(), tzinfo=now.tzinfo)
        elapsed_days = max((now - start_dt).total_seconds(), 0.0) / 86400.0
        progression = round(max(0.0, min(100.0, (elapsed_days / total) * 100.0)), 1)

    rules = SUBPHASE_RULES.get(phase_dominante, [(999, phase_dominante)])
    sous_phase = rules[-1][1]
    for limit, label in rules:
        if age_jours <= limit:
            sous_phase = label
            break

    return {
        "sous_phase": sous_phase,
        "age_jours": age_jours,
        "progression": progression,
        "detail": f"{phase_dominante} / {sous_phase}",
    }


_validate_phase_referentials()
