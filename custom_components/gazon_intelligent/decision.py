from __future__ import annotations

from datetime import date, datetime, timedelta
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

PHASE_PRIORITIES: dict[str, int] = {
    "Traitement": 100,
    "Hivernage": 95,
    "Sursemis": 90,
    "Scarification": 80,
    "Fertilisation": 70,
    "Agent Mouillant": 60,
    "Biostimulant": 50,
}

SIGNIFICANT_WATERING_THRESHOLD_MM = 2.0
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


def phase_duration_days(phase: str) -> int:
    return PHASE_DURATIONS_DAYS.get(phase, 0)


def is_hivernage(today: date, temperature: float | None) -> bool:
    if today.month in {11, 12, 1, 2}:
        return True
    if temperature is not None and temperature <= 5:
        return True
    return False


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
    today = today or date.today()
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
        end = start + timedelta(days=phase_duration_days(phase))
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
        if is_hivernage(today, temperature):
            return {
                "phase_dominante": "Hivernage",
                "date_debut": None,
                "date_fin": None,
                "age_jours": 0,
                "source": "climat",
            }
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
) -> dict[str, Any]:
    today = today or date.today()
    age_jours = 0
    progression = 0
    if date_debut is not None:
        age_jours = max((today - date_debut).days, 0)
    if date_debut is not None and date_fin is not None:
        total = max((date_fin - date_debut).days, 1)
        progression = int(max(0.0, min(100.0, round((age_jours / total) * 100.0))))

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


def compute_recent_watering_mm(
    history: list[dict[str, Any]],
    today: date | None = None,
    days: int = 2,
) -> float:
    today = today or date.today()
    total = 0.0
    for item in history:
        if not isinstance(item, dict) or item.get("type") != "arrosage":
            continue
        raw_date = item.get("date")
        if not raw_date:
            continue
        try:
            d = date.fromisoformat(str(raw_date))
        except ValueError:
            continue
        delta = (today - d).days
        if delta < 0 or delta > days:
            continue
        mm = item.get("objectif_mm")
        if mm is None:
            continue
        try:
            total += float(mm)
        except (TypeError, ValueError):
            continue
    return total


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_half_up_1(value: float) -> float:
    return float(int(value * 10.0 + 0.5)) / 10.0


def _latest_history_item(
    history: list[dict[str, Any]],
    predicate,
) -> dict[str, Any] | None:
    for item in reversed(history):
        if isinstance(item, dict) and predicate(item):
            return item
    return None


def _risk_rank(level: str) -> int:
    return {"faible": 0, "modere": 1, "eleve": 2}.get(level, 0)


def _risk_from_rank(rank: int) -> str:
    return {0: "faible", 1: "modere", 2: "eleve"}.get(max(0, min(rank, 2)), "faible")


def compute_advanced_context(
    humidite_sol: float | None = None,
    vent: float | None = None,
    rosee: float | None = None,
    hauteur_gazon: float | None = None,
    retour_arrosage: float | None = None,
    pluie_fine: float | None = None,
) -> dict[str, Any]:
    humidite_sol = _to_float(humidite_sol)
    vent = _to_float(vent)
    rosee = _to_float(rosee)
    hauteur_gazon = _to_float(hauteur_gazon)
    retour_arrosage = max(0.0, _to_float(retour_arrosage) or 0.0)
    pluie_fine = _to_float(pluie_fine)

    soil_factor = 1.0
    if humidite_sol is not None:
        if humidite_sol <= 25:
            soil_factor = 1.18
        elif humidite_sol <= 40:
            soil_factor = 1.08
        elif humidite_sol >= 80:
            soil_factor = 0.82
        elif humidite_sol >= 65:
            soil_factor = 0.92

    wind_factor = 1.0
    if vent is not None:
        if vent >= 25:
            wind_factor = 1.18
        elif vent >= 15:
            wind_factor = 1.10
        elif vent >= 8:
            wind_factor = 1.04

    dew_factor = 0.96 if rosee is not None and rosee > 0 else 1.0
    rain_factor = 0.92 if pluie_fine is not None else 0.85
    pluie_source = "capteur_pluie_fine" if pluie_fine is not None else "capteur_pluie_24h"

    return {
        "humidite_sol": humidite_sol,
        "vent": vent,
        "rosee": rosee,
        "hauteur_gazon": hauteur_gazon,
        "retour_arrosage": retour_arrosage if retour_arrosage > 0 else None,
        "pluie_fine": pluie_fine,
        "pluie_source": pluie_source,
        "soil_factor": soil_factor,
        "wind_factor": wind_factor,
        "dew_factor": dew_factor,
        "rain_factor": rain_factor,
    }


def compute_etp(
    temperature: float | None,
    pluie_24h: float | None,
    etp_capteur: float | None,
) -> float | None:
    if etp_capteur is not None:
        return etp_capteur
    if temperature is None:
        return None
    base = max(0.0, 0.08 * temperature)
    correction = max(0.0, (pluie_24h or 0) * 0.05)
    return max(0.0, base - correction)


def compute_water_balance(
    history: list[dict[str, Any]],
    today: date | None = None,
    etp: float | None = None,
    pluie_24h: float | None = None,
    pluie_demain: float | None = None,
    type_sol: str = "limoneux",
    recent_watering_mm_override: float | None = None,
    advanced_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    advanced_context = advanced_context or {}
    etp_j = max(0.0, etp or 0.0)
    pluie_j = max(0.0, pluie_24h or 0.0)
    pluie_j1 = max(0.0, pluie_demain or 0.0)
    pluie_fine = advanced_context.get("pluie_fine")
    pluie_source = advanced_context.get("pluie_source", "capteur_pluie_24h")
    if pluie_fine is not None:
        pluie_j = max(0.0, pluie_fine)

    reserve_sol = {
        "sableux": 8.0,
        "limoneux": 12.0,
        "argileux": 16.0,
    }.get(type_sol, 12.0)
    soil_factor = (12.0 / reserve_sol) * float(advanced_context.get("soil_factor", 1.0))
    soil_factor *= float(advanced_context.get("wind_factor", 1.0))
    soil_factor *= float(advanced_context.get("dew_factor", 1.0))

    pluie_efficace = _round_half_up_1((pluie_j * float(advanced_context.get("rain_factor", 0.85))) + (pluie_j1 * 0.55))
    arrosage_recent = (
        recent_watering_mm_override
        if recent_watering_mm_override is not None
        else compute_recent_watering_mm(history, today=today, days=7)
    )
    retour_arrosage = advanced_context.get("retour_arrosage")
    if retour_arrosage is not None:
        arrosage_recent = max(arrosage_recent, float(retour_arrosage))
    arrosage_recent_jour = compute_recent_watering_mm(history, today=today, days=1)
    arrosage_recent_3j = compute_recent_watering_mm(history, today=today, days=3)
    arrosage_recent_7j = arrosage_recent
    if retour_arrosage is not None:
        arrosage_recent_jour = max(arrosage_recent_jour, float(retour_arrosage))
        arrosage_recent_3j = max(arrosage_recent_3j, float(retour_arrosage))
        arrosage_recent_7j = max(arrosage_recent_7j, float(retour_arrosage))

    deficit_jour = max(0.0, (etp_j - pluie_efficace - arrosage_recent_jour) * soil_factor)
    deficit_3j = max(0.0, ((etp_j * 3.0) - (pluie_efficace * 1.4) - arrosage_recent_3j) * soil_factor)
    deficit_7j = max(0.0, ((etp_j * 7.0) - (pluie_efficace * 2.4) - arrosage_recent_7j) * soil_factor)

    return {
        "deficit_jour": _round_half_up_1(deficit_jour),
        "deficit_3j": _round_half_up_1(deficit_3j),
        "deficit_7j": _round_half_up_1(deficit_7j),
        "pluie_efficace": pluie_efficace,
        "arrosage_recent": _round_half_up_1(arrosage_recent_7j),
        "arrosage_recent_jour": _round_half_up_1(arrosage_recent_jour),
        "arrosage_recent_3j": _round_half_up_1(arrosage_recent_3j),
        "arrosage_recent_7j": _round_half_up_1(arrosage_recent_7j),
        "pluie_source": pluie_source,
        "pluie_fine": pluie_fine,
        "humidite_sol": advanced_context.get("humidite_sol"),
        "vent": advanced_context.get("vent"),
        "rosee": advanced_context.get("rosee"),
        "hauteur_gazon": advanced_context.get("hauteur_gazon"),
        "retour_arrosage": advanced_context.get("retour_arrosage"),
        "soil_factor": _round_half_up_1(soil_factor),
    }


def compute_internal_scores(
    history: list[dict[str, Any]],
    today: date | None,
    phase_dominante: str,
    sous_phase: str,
    water_balance: dict[str, float],
    advanced_context: dict[str, Any] | None,
    pluie_24h: float | None,
    pluie_demain: float | None,
    humidite: float | None,
    temperature: float | None,
    etp: float | None,
) -> dict[str, int]:
    today = today or date.today()
    advanced_context = advanced_context or {}
    deficit_jour = water_balance.get("deficit_jour", 0.0)
    deficit_3j = water_balance.get("deficit_3j", 0.0)
    deficit_7j = water_balance.get("deficit_7j", 0.0)
    pluie_efficace = water_balance.get("pluie_efficace", 0.0)
    arrosage_recent = water_balance.get("arrosage_recent", 0.0)
    humidite_sol = advanced_context.get("humidite_sol")
    vent = advanced_context.get("vent")
    rosee = advanced_context.get("rosee")
    hauteur_gazon = advanced_context.get("hauteur_gazon")
    pluie_24h = pluie_24h or 0.0
    pluie_demain = pluie_demain or 0.0
    humidite = humidite or 0.0
    temperature = temperature or 0.0
    etp = etp or 0.0

    score_hydrique = (deficit_jour * 8.0) + (deficit_3j * 3.0) + (deficit_7j * 1.2)
    if pluie_efficace >= 8:
        score_hydrique -= 10
    elif pluie_efficace >= 4:
        score_hydrique -= 5
    if arrosage_recent >= 8:
        score_hydrique -= 14
    elif arrosage_recent >= 4:
        score_hydrique -= 8
    elif arrosage_recent > 0:
        score_hydrique -= 3
    if phase_dominante == "Sursemis":
        score_hydrique += 10
    elif phase_dominante == "Scarification":
        score_hydrique += 6
    if sous_phase == "Germination":
        score_hydrique += 6
    elif sous_phase == "Enracinement":
        score_hydrique += 4
    if humidite_sol is not None:
        if humidite_sol <= 25:
            score_hydrique += 12
        elif humidite_sol <= 40:
            score_hydrique += 6
        elif humidite_sol >= 80:
            score_hydrique -= 10
        elif humidite_sol >= 65:
            score_hydrique -= 4
    if advanced_context.get("retour_arrosage") is not None:
        score_hydrique -= min(float(advanced_context["retour_arrosage"]) * 2.0, 8.0)
    score_hydrique = int(max(0.0, min(score_hydrique, 100.0)))

    score_stress = 0.0
    if temperature >= 34:
        score_stress += 36
    elif temperature >= 30:
        score_stress += 26
    elif temperature >= 27:
        score_stress += 14
    if etp >= 5:
        score_stress += 24
    elif etp >= 4:
        score_stress += 16
    elif etp >= 3:
        score_stress += 8
    if humidite <= 35:
        score_stress += 18
    elif humidite <= 45:
        score_stress += 10
    elif humidite >= 90:
        score_stress += 10
    elif humidite >= 82:
        score_stress += 6
    if pluie_24h >= 10:
        score_stress += 14
    elif pluie_24h >= 6:
        score_stress += 8
    if phase_dominante == "Sursemis":
        score_stress += 18
    if phase_dominante in {"Sursemis", "Scarification", "Traitement"}:
        score_stress += 15
    elif phase_dominante in {"Fertilisation", "Biostimulant", "Agent Mouillant"}:
        score_stress += 6
    if pluie_demain >= 8 and temperature >= 30:
        score_stress -= 5
    if vent is not None:
        if vent >= 25:
            score_stress += 16
        elif vent >= 15:
            score_stress += 10
        elif vent >= 8:
            score_stress += 4
    if rosee is not None and rosee > 0:
        score_stress += 5
    score_stress = int(max(0.0, min(score_stress, 100.0)))

    score_tonte = 0.0
    if pluie_24h >= 6:
        score_tonte += 30
    elif pluie_24h >= 3:
        score_tonte += 18
    if pluie_demain >= 5:
        score_tonte += 12
    elif pluie_demain >= 2:
        score_tonte += 6
    if humidite >= 88:
        score_tonte += 16
    elif humidite >= 78:
        score_tonte += 8
    if arrosage_recent >= 3:
        score_tonte += 12
    elif arrosage_recent > 0:
        score_tonte += 6
    if phase_dominante == "Sursemis":
        score_tonte += 45
    elif phase_dominante in {"Traitement", "Hivernage"}:
        score_tonte += 38
    elif phase_dominante != "Normal":
        score_tonte += 18
    if sous_phase == "Germination":
        score_tonte += 10
    elif sous_phase == "Enracinement":
        score_tonte += 5
    if hauteur_gazon is not None:
        if hauteur_gazon >= 12:
            score_tonte += 18
        elif hauteur_gazon >= 9:
            score_tonte += 10
        elif hauteur_gazon >= 7:
            score_tonte += 5
    if rosee is not None and rosee > 0:
        score_tonte += 8
    score_tonte += score_stress * 0.35
    score_tonte = int(max(0.0, min(score_tonte, 100.0)))

    return {
        "score_hydrique": score_hydrique,
        "score_stress": score_stress,
        "score_tonte": score_tonte,
    }


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


def compute_objectif_mm(
    phase_dominante: str,
    sous_phase: str,
    water_balance: dict[str, float],
    score_hydrique: int,
    score_stress: int,
) -> float:
    if phase_dominante in ("Traitement", "Hivernage"):
        return 0.0

    deficit_jour = water_balance.get("deficit_jour", 0.0)
    deficit_3j = water_balance.get("deficit_3j", 0.0)
    deficit_7j = water_balance.get("deficit_7j", 0.0)

    if phase_dominante == "Sursemis":
        base_mm = (deficit_jour * 0.95) + (deficit_3j * 0.12)
    elif phase_dominante == "Scarification":
        base_mm = (deficit_jour * 0.7) + (deficit_3j * 0.15)
    elif phase_dominante == "Fertilisation":
        base_mm = (deficit_jour * 0.65) + (deficit_3j * 0.12)
    elif phase_dominante == "Biostimulant":
        base_mm = (deficit_jour * 0.6) + (deficit_3j * 0.1)
    elif phase_dominante == "Agent Mouillant":
        base_mm = (deficit_jour * 0.75) + (deficit_3j * 0.1)
    else:
        base_mm = (deficit_jour * 0.55) + (deficit_3j * 0.25) + (deficit_7j * 0.08)

    if score_hydrique < 15:
        base_mm *= 0.25

    profile = {
        "Normal": (1.00, 0.0, 12.0),
        "Sursemis": (0.65, 0.5, 3.0),
        "Fertilisation": (0.80, 0.5, 3.5),
        "Biostimulant": (0.72, 0.4, 3.0),
        "Agent Mouillant": (0.88, 0.8, 4.0),
        "Scarification": (0.82, 0.6, 3.5),
    }.get(phase_dominante, (1.00, 0.0, 12.0))

    mult, min_mm, max_mm = profile
    objectif = base_mm * mult
    if phase_dominante == "Sursemis" and sous_phase == "Germination":
        max_mm = min(max_mm, 2.0)
    elif phase_dominante == "Sursemis" and sous_phase == "Enracinement":
        max_mm = min(max_mm, 2.5)
    elif phase_dominante == "Sursemis":
        max_mm = min(max_mm, 3.0)
    if score_hydrique < 20 and score_stress < 35:
        min_mm = 0.0
    objectif = max(min_mm, min(max_mm, objectif))
    return round(max(0.0, objectif), 1)


def compute_jours_restants_for(
    phase_dominante: str,
    date_fin: date | None,
    today: date | None = None,
) -> int:
    today = today or date.today()
    if phase_dominante == "Hivernage":
        return 999
    if not date_fin:
        return 0
    return max((date_fin - today).days, 0)


def compute_action_guidance(
    phase_dominante: str,
    sous_phase: str,
    water_balance: dict[str, float],
    advanced_context: dict[str, Any] | None,
    pluie_24h: float | None,
    pluie_demain: float | None,
    humidite: float | None,
    temperature: float | None,
    etp: float | None,
    objectif_mm: float,
    score_hydrique: int,
    score_stress: int,
    score_tonte: int,
    hour_of_day: int | None = None,
) -> dict[str, str]:
    advanced_context = advanced_context or {}
    pluie_24h = pluie_24h or 0.0
    pluie_demain = pluie_demain or 0.0
    humidite = humidite or 0.0
    temperature = temperature or 0.0
    etp = etp or 0.0

    pressure = max(score_hydrique, score_stress, score_tonte)
    pluie_compensatrice = objectif_mm > 0 and pluie_demain >= max(2.0, objectif_mm * 0.8)
    pluie_proche = pluie_24h >= 4 or pluie_demain >= 4
    now_hour = hour_of_day if hour_of_day is not None else datetime.now().hour
    vent = advanced_context.get("vent")
    rosee = advanced_context.get("rosee")
    hauteur_gazon = advanced_context.get("hauteur_gazon")
    rain_source = advanced_context.get("pluie_source")

    if phase_dominante in {"Traitement", "Hivernage"}:
        return {
            "niveau_action": "surveiller",
            "fenetre_optimale": "attendre",
            "risque_gazon": "faible",
        }

    if objectif_mm <= 0:
        fenetre_optimale = "attendre"
        if rosee is not None and rosee > 0:
            fenetre_optimale = "attendre"
        if vent is not None and vent >= 20:
            fenetre_optimale = "attendre"
        return {
            "niveau_action": "aucune_action" if phase_dominante == "Normal" else "surveiller",
            "fenetre_optimale": fenetre_optimale,
            "risque_gazon": "faible" if phase_dominante == "Normal" else "modere",
        }

    if phase_dominante == "Sursemis":
        niveau_action = "critique" if pressure >= 70 or score_hydrique >= 55 else "a_faire"
        if pluie_compensatrice or pluie_proche:
            fenetre_optimale = "apres_pluie"
        elif now_hour < 9:
            fenetre_optimale = "maintenant"
        else:
            fenetre_optimale = "demain_matin"
        if rain_source == "capteur_pluie_fine" and pluie_24h > 0:
            fenetre_optimale = "apres_pluie" if pluie_compensatrice else fenetre_optimale
        risque_gazon = "eleve" if pressure >= 70 or score_hydrique >= 55 or score_stress >= 70 else "modere"
        if vent is not None and vent >= 20:
            risque_gazon = "eleve"
        if hauteur_gazon is not None and hauteur_gazon >= 12:
            risque_gazon = "eleve"
        return {
            "niveau_action": niveau_action,
            "fenetre_optimale": fenetre_optimale,
            "risque_gazon": risque_gazon,
        }

    if pluie_compensatrice:
        fenetre_optimale = "apres_pluie"
        niveau_action = "surveiller"
    elif humidite >= 85:
        fenetre_optimale = "attendre"
        niveau_action = "surveiller"
    elif temperature >= 30 and etp >= 4:
        fenetre_optimale = "demain_matin"
        niveau_action = "a_faire"
    elif vent is not None and vent >= 20:
        fenetre_optimale = "demain_matin"
        niveau_action = "a_faire"
    elif rosee is not None and rosee > 0:
        fenetre_optimale = "attendre"
        niveau_action = "surveiller"
    elif now_hour < 9:
        fenetre_optimale = "maintenant"
        niveau_action = "a_faire"
    else:
        fenetre_optimale = "demain_matin"
        niveau_action = "a_faire"

    if pressure >= 75 or score_hydrique >= 60 or score_stress >= 75:
        risque_gazon = "eleve"
    elif pressure >= 40 or score_hydrique >= 35 or score_stress >= 50:
        risque_gazon = "modere"
    else:
        risque_gazon = "faible"
    if vent is not None and vent >= 20:
        risque_gazon = _risk_from_rank(min(_risk_rank(risque_gazon) + 1, 2))
    if hauteur_gazon is not None and hauteur_gazon >= 12:
        risque_gazon = _risk_from_rank(min(_risk_rank(risque_gazon) + 1, 2))

    return {
        "niveau_action": niveau_action,
        "fenetre_optimale": fenetre_optimale,
        "risque_gazon": risque_gazon,
    }


def compute_next_reevaluation(
    phase_dominante: str,
    niveau_action: str,
    fenetre_optimale: str,
    risque_gazon: str,
    pluie_demain: float | None = None,
) -> str:
    pluie_demain = pluie_demain or 0.0

    if fenetre_optimale == "apres_pluie" and pluie_demain > 0:
        return "apres_pluie"
    if phase_dominante in {"Traitement", "Hivernage"}:
        return "dans 24 h"
    if phase_dominante == "Sursemis":
        return "dans 24 h"
    if niveau_action == "critique":
        return "dans 12 h"
    if niveau_action == "a_faire":
        return "dans 24 h"
    if niveau_action == "surveiller":
        return "dans 48 h"
    return "dans 48 h"


def compute_decision(
    phase_dominante: str,
    sous_phase: str,
    water_balance: dict[str, float],
    advanced_context: dict[str, Any] | None,
    pluie_24h: float | None,
    pluie_demain: float | None,
    humidite: float | None,
    temperature: float | None,
    etp: float | None,
    objectif_mm: float,
    jours_restants: int,
    score_hydrique: int,
    score_stress: int,
    score_tonte: int,
    history: list[dict[str, Any]],
    today: date | None = None,
    hour_of_day: int | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    advanced_context = advanced_context or {}
    pluie_24h = pluie_24h or 0.0
    pluie_demain = pluie_demain or 0.0
    humidite = humidite or 0.0
    temperature = temperature or 0.0
    etp = etp or 0.0
    arrosage_recent = water_balance.get("arrosage_recent", 0.0)
    deficit_jour = water_balance.get("deficit_jour", 0.0)
    deficit_3j = water_balance.get("deficit_3j", 0.0)
    deficit_7j = water_balance.get("deficit_7j", 0.0)
    pluie_efficace = water_balance.get("pluie_efficace", 0.0)
    now_hour = hour_of_day if hour_of_day is not None else datetime.now().hour
    prochain_creneau = "ce matin" if now_hour < 9 else "demain matin"
    action_guidance = compute_action_guidance(
        phase_dominante=phase_dominante,
        sous_phase=sous_phase,
        water_balance=water_balance,
        advanced_context=advanced_context,
        pluie_24h=pluie_24h,
        pluie_demain=pluie_demain,
        humidite=humidite,
        temperature=temperature,
        etp=etp,
        objectif_mm=objectif_mm,
        score_hydrique=score_hydrique,
        score_stress=score_stress,
        score_tonte=score_tonte,
        hour_of_day=hour_of_day,
    )
    prochaine_reevaluation = compute_next_reevaluation(
        phase_dominante=phase_dominante,
        niveau_action=action_guidance["niveau_action"],
        fenetre_optimale=action_guidance["fenetre_optimale"],
        risque_gazon=action_guidance["risque_gazon"],
        pluie_demain=pluie_demain,
    )

    if phase_dominante == "Traitement":
        return {
            "tonte_autorisee": False,
            "arrosage_auto_autorise": False,
            "arrosage_recommande": False,
            "type_arrosage": "bloque",
            "arrosage_conseille": "personnalise",
            "raison_decision": "Traitement actif: tonte et arrosage bloqués.",
            "conseil_principal": f"Laisser agir le traitement encore {jours_restants} jour(s).",
            "action_recommandee": "Surveiller l'état du gazon sans intervention hydrique.",
            "action_a_eviter": "Tondre ou arroser.",
            "niveau_action": action_guidance["niveau_action"],
            "fenetre_optimale": action_guidance["fenetre_optimale"],
            "risque_gazon": action_guidance["risque_gazon"],
            "prochaine_reevaluation": prochaine_reevaluation,
            "score_tonte": score_tonte,
        }
    if phase_dominante == "Hivernage":
        return {
            "tonte_autorisee": False,
            "arrosage_auto_autorise": False,
            "arrosage_recommande": False,
            "type_arrosage": "bloque",
            "arrosage_conseille": "personnalise",
            "raison_decision": "Hivernage actif: repos végétatif.",
            "conseil_principal": "Limiter les interventions et éviter les coupes stressantes.",
            "action_recommandee": "Surveiller uniquement.",
            "action_a_eviter": "Arrosages fréquents.",
            "niveau_action": action_guidance["niveau_action"],
            "fenetre_optimale": action_guidance["fenetre_optimale"],
            "risque_gazon": action_guidance["risque_gazon"],
            "prochaine_reevaluation": prochaine_reevaluation,
            "score_tonte": score_tonte,
        }
    if phase_dominante == "Sursemis":
        passages = 3 if objectif_mm >= 2 else 2
        return {
            "tonte_autorisee": False,
            "arrosage_auto_autorise": False,
            "arrosage_recommande": objectif_mm > 0,
            "type_arrosage": "manuel_frequent",
            "arrosage_conseille": "personnalise",
            "raison_decision": (
                f"Sursemis / {sous_phase}: déficit jour={deficit_jour} mm, 3j={deficit_3j} mm, 7j={deficit_7j} mm. "
                f"Pluie efficace={pluie_efficace:.1f} mm."
            ),
            "conseil_principal": f"Arroser {prochain_creneau} en {passages} passages courts.",
            "action_recommandee": f"Appliquer {objectif_mm} mm fractionnés ({passages}x).",
            "action_a_eviter": "Tondre avant levée complète.",
            "niveau_action": action_guidance["niveau_action"],
            "fenetre_optimale": action_guidance["fenetre_optimale"],
            "risque_gazon": action_guidance["risque_gazon"],
            "prochaine_reevaluation": prochaine_reevaluation,
            "score_tonte": score_tonte,
        }

    tonte_ok = score_tonte < 45 and score_stress < 70
    auto_ok = phase_dominante in {"Normal", "Fertilisation", "Biostimulant", "Agent Mouillant", "Scarification"}
    recommande = score_hydrique >= 30 and objectif_mm > 0
    if not tonte_ok:
        if humidite >= 85:
            tonte_reason = "Humidité trop élevée: pelouse humide."
        elif pluie_24h >= 3:
            tonte_reason = "Pluie récente: sol encore humide."
        elif arrosage_recent > 0:
            tonte_reason = "Arrosage récent: attendre un ressuyage."
        elif temperature >= 30 and etp >= 4:
            tonte_reason = "Stress thermique élevé: limiter la tonte."
        else:
            tonte_reason = "Conditions défavorables à la tonte."
    else:
        tonte_reason = "Fenêtre tonte acceptable."

    pluie_significative = pluie_24h >= 4 or pluie_demain >= 4
    pluie_compensatrice = recommande and pluie_demain >= max(2.0, objectif_mm * 0.8)
    stress_thermique = temperature >= 30 and etp >= 4
    humidite_haute = humidite >= 85

    if phase_dominante == "Normal":
        if not recommande:
            if pluie_demain >= 2:
                conseil_principal = "Pas d'arrosage aujourd'hui: la pluie prévue couvre le besoin court terme."
                action_recommandee = "Laisser la pluie agir puis réévaluer demain."
                action_a_eviter = "Cumuler pluie + arrosage sans contrôle."
            else:
                conseil_principal = "Pas d'arrosage nécessaire pour le moment."
                action_recommandee = "Réévaluer au prochain cycle météo."
                action_a_eviter = "Arroser par réflexe."
        else:
            if pluie_compensatrice:
                conseil_principal = (
                    "Reporter l'arrosage: la pluie de demain peut compenser une grande partie du déficit."
                )
                action_recommandee = (
                    f"Réduire l'apport à {max(0.0, round(objectif_mm * 0.4, 1))} mm maximum aujourd'hui."
                )
                action_a_eviter = "Lancer un cycle complet avant l'épisode pluvieux."
            elif stress_thermique:
                conseil_principal = f"Arroser {prochain_creneau} en deux passages pour limiter l'évaporation."
                action_recommandee = f"Appliquer {objectif_mm} mm fractionnés (2x)."
                action_a_eviter = "Arroser entre 11h et 18h."
            elif humidite_haute:
                conseil_principal = "Attendre un léger ressuyage avant arrosage."
                action_recommandee = f"Programmer {objectif_mm} mm en fin de nuit si l'humidité baisse."
                action_a_eviter = "Arroser immédiatement sur pelouse saturée."
            else:
                conseil_principal = f"Arroser {prochain_creneau}: manque d'eau estimé à {objectif_mm} mm."
                action_recommandee = f"Appliquer {objectif_mm} mm sur les zones actives."
                action_a_eviter = "Arroser en pleine journée."
    else:
        if not recommande:
            conseil_principal = f"Phase {phase_dominante}: pas d'arrosage requis pour l'instant."
            action_recommandee = "Surveiller les capteurs et l'évolution météo."
        elif phase_dominante == "Fertilisation":
            conseil_principal = "Fertilisation active: humidifier légèrement pour activer l'apport."
            action_recommandee = f"Appliquer {objectif_mm} mm en 1 à 2 passages."
        elif phase_dominante == "Scarification":
            conseil_principal = "Scarification: maintenir une humidité stable sans détremper."
            action_recommandee = f"Appliquer {objectif_mm} mm en apports courts."
        elif phase_dominante == "Agent Mouillant":
            conseil_principal = "Agent mouillant: faire pénétrer l'eau plus en profondeur."
            action_recommandee = f"Appliquer {objectif_mm} mm en cycle allongé."
        elif phase_dominante == "Biostimulant":
            conseil_principal = "Biostimulant: conserver un niveau hydrique modéré."
            action_recommandee = f"Appliquer {objectif_mm} mm en un passage."
        else:
            conseil_principal = f"Phase {phase_dominante}: maintenir un arrosage maîtrisé {prochain_creneau}."
            action_recommandee = f"Appliquer {objectif_mm} mm en tenant compte de l'humidité actuelle."
        action_a_eviter = "Tondre sur sol humide." if not tonte_ok else "Intervention agressive inutile."

    facteurs = [
        f"deficit_jour={deficit_jour:.1f}",
        f"deficit_3j={deficit_3j:.1f}",
        f"deficit_7j={deficit_7j:.1f}",
        f"pluie_efficace={pluie_efficace:.1f}",
        f"arrosage_recent={arrosage_recent:.1f}",
    ]
    if pluie_significative:
        facteurs.append("risque d'humidité élevé")
    if stress_thermique:
        facteurs.append("stress thermique")
    if humidite_haute:
        facteurs.append("humidité air élevée")
    if advanced_context.get("humidite_sol") is not None:
        facteurs.append(f"humidite_sol={advanced_context['humidite_sol']:.1f}")
    if advanced_context.get("vent") is not None:
        facteurs.append(f"vent={advanced_context['vent']:.1f}")
    if advanced_context.get("rosee") is not None and advanced_context.get("rosee") > 0:
        facteurs.append("rosée présente")
    if advanced_context.get("hauteur_gazon") is not None:
        facteurs.append(f"hauteur_gazon={advanced_context['hauteur_gazon']:.1f}")
    if advanced_context.get("retour_arrosage") is not None:
        facteurs.append(f"retour_arrosage={advanced_context['retour_arrosage']:.1f}")
    facteurs_txt = ", ".join(facteurs)

    return {
        "tonte_autorisee": tonte_ok,
        "arrosage_auto_autorise": auto_ok,
        "arrosage_recommande": recommande,
        "type_arrosage": "auto" if auto_ok else "personnalise",
        "arrosage_conseille": "auto" if phase_dominante == "Normal" else "personnalise",
        "raison_decision": (
            f"Mode {phase_dominante} / {sous_phase} en cours ({jours_restants} jour(s) restants). "
            f"Niveaux: eau={score_hydrique}/stress={score_stress}/tonte={score_tonte}. {facteurs_txt}. {tonte_reason}"
        ),
        "conseil_principal": conseil_principal,
        "action_recommandee": action_recommandee,
        "action_a_eviter": action_a_eviter,
        "niveau_action": action_guidance["niveau_action"],
        "fenetre_optimale": action_guidance["fenetre_optimale"],
        "risque_gazon": action_guidance["risque_gazon"],
        "prochaine_reevaluation": prochaine_reevaluation,
        "score_tonte": score_tonte,
    }


def build_decision_snapshot(
    history: list[dict[str, Any]],
    today: date | None = None,
    hour_of_day: int | None = None,
    temperature: float | None = None,
    pluie_24h: float | None = None,
    pluie_demain: float | None = None,
    humidite: float | None = None,
    type_sol: str = "limoneux",
    etp_capteur: float | None = None,
    humidite_sol: float | None = None,
    vent: float | None = None,
    rosee: float | None = None,
    hauteur_gazon: float | None = None,
    retour_arrosage: float | None = None,
    pluie_fine: float | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    etp = compute_etp(temperature=temperature, pluie_24h=pluie_24h, etp_capteur=etp_capteur)
    advanced_context = compute_advanced_context(
        humidite_sol=humidite_sol,
        vent=vent,
        rosee=rosee,
        hauteur_gazon=hauteur_gazon,
        retour_arrosage=retour_arrosage,
        pluie_fine=pluie_fine,
    )
    dominant = compute_dominant_phase(history, today=today, temperature=temperature)
    phase_dominante = dominant["phase_dominante"]
    date_action = dominant["date_debut"]
    date_fin = dominant["date_fin"]
    sous_phase = compute_subphase(
        phase_dominante=phase_dominante,
        date_debut=date_action,
        date_fin=date_fin,
        today=today,
    )
    jours_restants = compute_jours_restants_for(
        phase_dominante=phase_dominante,
        date_fin=date_fin,
        today=today,
    )
    water_balance = compute_water_balance(
        history=history,
        today=today,
        etp=etp,
        pluie_24h=pluie_24h,
        pluie_demain=pluie_demain,
        type_sol=type_sol,
        recent_watering_mm_override=retour_arrosage,
        advanced_context=advanced_context,
    )
    scores = compute_internal_scores(
        history=history,
        today=today,
        phase_dominante=phase_dominante,
        sous_phase=sous_phase["sous_phase"],
        water_balance=water_balance,
        advanced_context=advanced_context,
        pluie_24h=pluie_24h,
        pluie_demain=pluie_demain,
        humidite=humidite,
        temperature=temperature,
        etp=etp,
    )
    objectif_mm = compute_objectif_mm(
        phase_dominante=phase_dominante,
        sous_phase=sous_phase["sous_phase"],
        water_balance=water_balance,
        score_hydrique=scores["score_hydrique"],
        score_stress=scores["score_stress"],
    )
    decision = compute_decision(
        phase_dominante=phase_dominante,
        sous_phase=sous_phase["sous_phase"],
        water_balance=water_balance,
        advanced_context=advanced_context,
        pluie_24h=pluie_24h,
        pluie_demain=pluie_demain,
        humidite=humidite,
        temperature=temperature,
        etp=etp,
        objectif_mm=objectif_mm,
        jours_restants=jours_restants,
        score_hydrique=scores["score_hydrique"],
        score_stress=scores["score_stress"],
        score_tonte=scores["score_tonte"],
        history=history,
        today=today,
        hour_of_day=hour_of_day,
    )
    return {
        "mode": phase_dominante,
        "phase_active": phase_dominante,
        "phase_dominante": phase_dominante,
        "phase_dominante_source": dominant["source"],
        "date_action": date_action,
        "date_fin": date_fin,
        "phase_age_days": dominant["age_jours"],
        "sous_phase": sous_phase["sous_phase"],
        "sous_phase_detail": sous_phase["detail"],
        "sous_phase_age_days": sous_phase["age_jours"],
        "sous_phase_progression": sous_phase["progression"],
        "etp": etp,
        "advanced_context": advanced_context,
        "humidite_sol": advanced_context["humidite_sol"],
        "vent": advanced_context["vent"],
        "rosee": advanced_context["rosee"],
        "hauteur_gazon": advanced_context["hauteur_gazon"],
        "retour_arrosage": advanced_context["retour_arrosage"],
        "pluie_fine": advanced_context["pluie_fine"],
        "pluie_source": advanced_context["pluie_source"],
        "water_balance": water_balance,
        "deficit_jour": water_balance["deficit_jour"],
        "deficit_3j": water_balance["deficit_3j"],
        "deficit_7j": water_balance["deficit_7j"],
        "pluie_efficace": water_balance["pluie_efficace"],
        "arrosage_recent": water_balance["arrosage_recent"],
        "arrosage_recent_jour": water_balance["arrosage_recent_jour"],
        "arrosage_recent_3j": water_balance["arrosage_recent_3j"],
        "arrosage_recent_7j": water_balance["arrosage_recent_7j"],
        "bilan_hydrique_mm": water_balance["deficit_jour"],
        "objectif_mm": objectif_mm,
        "score_hydrique": scores["score_hydrique"],
        "score_stress": scores["score_stress"],
        "tonte_autorisee": decision["tonte_autorisee"],
        "arrosage_auto_autorise": decision["arrosage_auto_autorise"],
        "arrosage_recommande": decision["arrosage_recommande"],
        "type_arrosage": decision["type_arrosage"],
        "arrosage_conseille": decision["arrosage_conseille"],
        "raison_decision": decision["raison_decision"],
        "conseil_principal": decision["conseil_principal"],
        "action_recommandee": decision["action_recommandee"],
        "action_a_eviter": decision["action_a_eviter"],
        "niveau_action": decision["niveau_action"],
        "fenetre_optimale": decision["fenetre_optimale"],
        "risque_gazon": decision["risque_gazon"],
        "prochaine_reevaluation": decision["prochaine_reevaluation"],
        "score_tonte": decision["score_tonte"],
        "jours_restants": jours_restants,
    }
