from __future__ import annotations

"""Référentiel des phases métier.

`Hivernage` est volontairement traité comme un mode explicite:
- il reste présent dans l'historique et les règles de priorité/sous-phase
- il n'est plus activé implicitement par la météo ou la saison
- hors phase active connue, le moteur retombe sur `Normal`
"""

import math
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.util import dt as dt_util

from .reglages import lire

PHASE_DURATIONS_DAYS: dict[str, int] = {
    "Normal": 0,
    "Semis": 45,
    "Sursemis": 45,
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
    "Semis": 90,
    "Sursemis": 90,
    "Scarification": 80,
    "Fertilisation": 70,
    "Agent Mouillant": 60,
    "Biostimulant": 50,
}

_SOUS_PHASES_SEMIS: list[tuple[int, str]] = [
    (10, "Germination"),
    (24, "Enracinement"),
    (34, "Reprise"),
    (999, "Stabilisation"),
]

SUBPHASE_RULES: dict[str, list[tuple[int, str]]] = {
    # Mêmes étapes pour les deux : elles pilotent l'ARROSAGE des graines, identique sur sol nu et
    # sur gazon en place. Seule la TONTE diffère (voir `decision_mowing`).
    "Semis": _SOUS_PHASES_SEMIS,
    "Sursemis": _SOUS_PHASES_SEMIS,
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

# DEUX MODES DE SEMIS (16/09/2026, arbitrage de Kévin) :
#   · « Semis » : terrain NU. Il n'y a que des plantules ; le comportement historique du mode
#     « Sursemis » (tonte interdite 25 jours, pousse nulle, planchers 7,5 → 5,0 cm) y est conservé.
#   · « Sursemis » : graines semées DANS un gazon en place, qui continue de pousser. L'arrosage
#     des graines est le même (UMass : « Irrigate in the same manner as for new seedings ») ; la
#     tonte reprend après la levée, lame courte puis remontée (Purdue AY-13-W).
# Tout ce qui concerne les GRAINES (arrosage, risque, stress) vaut pour les deux : tester
# `is_seeding_phase`, jamais le nom d'un seul des deux.
SEEDING_PHASES = frozenset({"Semis", "Sursemis"})


def is_seeding_phase(phase: Any) -> bool:
    """Vrai pour une phase où des graines lèvent : semis sur sol nu ou sursemis."""
    return str(phase or "") in SEEDING_PHASES


# CALENDRIER DES PLANTULES — partagé par la tonte (`decision_mowing`) et par la transition de
# l'arrosage (`guidance`). Sources : UC IPM (levée du ray-grass anglais 5-10 j, de la fétuque rouge
# 7-14 j ; première coupe à une fois et demie la hauteur de tonte) et Purdue AY-13-W (1,5 in).
# ⚠️ La pousse des plantules est une ESTIMATION : seuls des délais de première tonte sont publiés.
SURSEMIS_LEVEE_JOURS = 7                 # levée du ray-grass du mélange semé le 16/09/2026
PLANTULES_POUSSE_CM_JOUR = 0.4
SURSEMIS_HAUTEUR_COUPE_CM = 4.0          # Purdue : 1,5 in = 3,8 cm, au cran de 0,5 cm
PLANTULES_RATIO_PREMIERE_COUPE = 1.5     # UC IPM


# RÉGLAGES DE LA PAGE « GAZON » (0.92.0). Chaque instance peut remplacer ces valeurs : les
# fonctions ci-dessous prennent `reglages` (sortis de `reglages.nettoyer`) et retombent sur les
# constantes sans eux. Semis et Sursemis partagent la même durée et les mêmes étapes.
_DUREES_REGLABLES: dict[str, str] = {
    "Semis": "graines_duree",
    "Sursemis": "graines_duree",
    "Traitement": "mode_traitement_duree",
    "Fertilisation": "mode_fertilisation_duree",
    "Biostimulant": "mode_biostimulant_duree",
    "Agent Mouillant": "mode_agent_mouillant_duree",
    "Scarification": "mode_scarification_duree",
}
_FINS_D_ETAPE_REGLABLES: dict[str, str] = {
    "Germination": "graines_fin_germination",
    "Enracinement": "graines_fin_enracinement",
    "Reprise": "graines_fin_reprise",
}


def levee_sursemis_jours(reglages: Mapping[str, Any] | None = None) -> int:
    """Jours de levée d'un sursemis, pendant lesquels la tondeuse attend."""
    return int(lire(reglages, "sursemis_levee", SURSEMIS_LEVEE_JOURS))


def pousse_plantules_cm_jour(reglages: Mapping[str, Any] | None = None) -> float:
    return float(lire(reglages, "sursemis_pousse_plantules", PLANTULES_POUSSE_CM_JOUR))


def hauteur_coupe_sursemis_cm(reglages: Mapping[str, Any] | None = None) -> float:
    return float(lire(reglages, "sursemis_lame", SURSEMIS_HAUTEUR_COUPE_CM))


def jours_avant_premiere_coupe(reglages: Mapping[str, Any] | None = None) -> int:
    """Âge du semis (en jours) où les plantules atteignent leur hauteur de première coupe."""
    ratio = float(lire(reglages, "sursemis_premiere_coupe", PLANTULES_RATIO_PREMIERE_COUPE))
    hauteur = ratio * hauteur_coupe_sursemis_cm(reglages)
    # `round` avant `ceil` : 6,0 / 0,4 n'est pas exactement 15 en virgule flottante.
    return levee_sursemis_jours(reglages) + math.ceil(round(hauteur / pousse_plantules_cm_jour(reglages), 6))


def phase_duration_days(phase: str, reglages: Mapping[str, Any] | None = None) -> int:
    duree = PHASE_DURATIONS_DAYS.get(phase, 0)
    cle = _DUREES_REGLABLES.get(phase)
    return duree if cle is None else int(lire(reglages, cle, duree))


def regles_des_sous_phases(phase: str, reglages: Mapping[str, Any] | None = None) -> list[tuple[int, str]]:
    """Les étapes d'une phase, avec les fins d'étape réglées pour les graines."""
    regles = SUBPHASE_RULES.get(phase, [(999, phase)])
    if phase not in SEEDING_PHASES or not reglages:
        return list(regles)
    return [
        (int(lire(reglages, _FINS_D_ETAPE_REGLABLES[libelle], borne)) if libelle in _FINS_D_ETAPE_REGLABLES else borne, libelle)
        for borne, libelle in regles
    ]


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
    reglages: Mapping[str, Any] | None = None,
) -> tuple[str, date | None, date | None]:
    dominant = compute_dominant_phase(history, today=today, reglages=reglages)
    return dominant["phase_dominante"], dominant["date_debut"], dominant["date_fin"]


def compute_dominant_phase(
    history: list[dict[str, Any]],
    today: date | None = None,
    reglages: Mapping[str, Any] | None = None,
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
        duration_days = max(phase_duration_days(phase, reglages), 0)
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
    reglages: Mapping[str, Any] | None = None,
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

    rules = sorted(regles_des_sous_phases(phase_dominante, reglages), key=lambda r: r[0])
    sous_phase = rules[-1][1]
    subphase_start_day = 0
    subphase_end_day = rules[-1][0]
    previous_limit = -1
    for limit, label in rules:
        if age_jours <= limit:
            sous_phase = label
            subphase_start_day = previous_limit + 1
            subphase_end_day = limit
            break
        previous_limit = limit

    # La sentinelle 999 signifie "jusqu'à la fin de la phase": pour la progression,
    # borner la sous-phase terminale par la durée réelle de la phase au lieu de
    # traiter 999 comme une durée (sinon la barre rampe à ~0.1 %/jour).
    # Hivernage (durée 999) reste volontairement ouvert.
    phase_total_days = phase_duration_days(phase_dominante, reglages)
    if subphase_end_day >= 999 and 0 < phase_total_days < 999:
        subphase_end_day = max(phase_total_days, subphase_start_day)

    if date_debut is not None:
        subphase_start_date = date_debut + timedelta(days=subphase_start_day)
        subphase_duration_days = max((subphase_end_day - subphase_start_day) + 1, 1)
        start_dt = datetime.combine(
            subphase_start_date,
            datetime.min.time(),
            tzinfo=now.tzinfo,
        )
        elapsed_days = max((now - start_dt).total_seconds(), 0.0) / 86400.0
        progression = round(
            max(0.0, min(100.0, (elapsed_days / subphase_duration_days) * 100.0)),
            1,
        )

    return {
        "sous_phase": sous_phase,
        "age_jours": age_jours,
        "progression": progression,
        "detail": f"{phase_dominante} / {sous_phase}",
    }


_validate_phase_referentials()
