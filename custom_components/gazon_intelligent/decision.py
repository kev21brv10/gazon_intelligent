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
    today = today or date.today()
    best: tuple[int, date] | None = None
    active_phase: str | None = None
    active_date: date | None = None
    active_end: date | None = None

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
            active_phase = phase
            active_date = start
            active_end = end

    if active_phase:
        return active_phase, active_date, active_end
    if is_hivernage(today, temperature):
        return "Hivernage", None, None
    return "Normal", None, None


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


def compute_bilan_hydrique(
    etp: float | None,
    pluie_24h: float | None,
    pluie_demain: float | None,
    type_sol: str,
    recent_watering_mm: float,
) -> float:
    etp_j = max(0.0, etp or 0.0)
    pluie_j = max(0.0, pluie_24h or 0.0)
    pluie_j1 = max(0.0, pluie_demain or 0.0)

    reserve_sol = {
        "sableux": 8.0,
        "limoneux": 12.0,
        "argileux": 16.0,
    }.get(type_sol, 12.0)

    demande_48h = etp_j * 2.0
    apports_utiles = (pluie_j * 0.85) + (pluie_j1 * 0.35) + recent_watering_mm
    deficit = max(0.0, demande_48h - apports_utiles)
    deficit_pondere = deficit * (12.0 / reserve_sol)
    return round(max(0.0, min(deficit_pondere, 20.0)), 1)


def compute_internal_scores(
    history: list[dict[str, Any]],
    today: date | None,
    phase_active: str,
    bilan_hydrique: float,
    pluie_24h: float | None,
    pluie_demain: float | None,
    humidite: float | None,
    temperature: float | None,
    etp: float | None,
) -> dict[str, int]:
    today = today or date.today()
    pluie_24h = pluie_24h or 0.0
    pluie_demain = pluie_demain or 0.0
    humidite = humidite or 0.0
    temperature = temperature or 0.0
    etp = etp or 0.0
    arrosage_recent = compute_recent_watering_mm(history, today=today, days=1)

    score_hydrique = bilan_hydrique * 5.0
    if etp >= 5:
        score_hydrique += 12
    elif etp >= 4:
        score_hydrique += 8
    elif etp >= 3:
        score_hydrique += 4
    if pluie_demain >= 8:
        score_hydrique -= 24
    elif pluie_demain >= 5:
        score_hydrique -= 16
    elif pluie_demain >= 2:
        score_hydrique -= 8
    if arrosage_recent >= 4:
        score_hydrique -= 18
    elif arrosage_recent >= 2:
        score_hydrique -= 10
    elif arrosage_recent > 0:
        score_hydrique -= 5
    if phase_active == "Sursemis":
        score_hydrique += 8
    elif phase_active == "Scarification":
        score_hydrique += 6
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
    if phase_active in {"Sursemis", "Scarification", "Traitement"}:
        score_stress += 15
    elif phase_active in {"Fertilisation", "Biostimulant", "Agent Mouillant"}:
        score_stress += 6
    if pluie_demain >= 8 and temperature >= 30:
        score_stress -= 5
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
    if phase_active == "Sursemis":
        score_tonte += 45
    elif phase_active in {"Traitement", "Hivernage"}:
        score_tonte += 38
    elif phase_active != "Normal":
        score_tonte += 18
    score_tonte += score_stress * 0.35
    score_tonte = int(max(0.0, min(score_tonte, 100.0)))

    return {
        "score_hydrique": score_hydrique,
        "score_stress": score_stress,
        "score_tonte": score_tonte,
    }


def compute_objectif_mm(
    bilan_hydrique: float,
    phase_active: str,
    score_hydrique: int,
    score_stress: int,
) -> float:
    if phase_active in ("Traitement", "Hivernage"):
        return 0.0

    base_mm = (bilan_hydrique * 0.65) + (score_hydrique * 0.045) + (score_stress * 0.015)
    if score_hydrique < 15:
        base_mm *= 0.2

    profile = {
        "Normal": (1.00, 0.0, 12.0),
        "Sursemis": (0.55, 0.5, 3.0),
        "Fertilisation": (0.75, 0.5, 3.5),
        "Biostimulant": (0.70, 0.4, 3.0),
        "Agent Mouillant": (0.85, 0.8, 4.0),
        "Scarification": (0.80, 0.6, 3.5),
    }.get(phase_active, (1.00, 0.0, 12.0))

    mult, min_mm, max_mm = profile
    objectif = base_mm * mult
    if score_hydrique < 20 and score_stress < 35:
        min_mm = 0.0
    objectif = max(min_mm, min(max_mm, objectif))
    return round(max(0.0, objectif), 1)


def compute_jours_restants_for(
    phase_active: str,
    date_fin: date | None,
    today: date | None = None,
) -> int:
    today = today or date.today()
    if phase_active == "Hivernage":
        return 999
    if not date_fin:
        return 0
    return max((date_fin - today).days, 0)


def compute_decision(
    phase_active: str,
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
    pluie_24h = pluie_24h or 0.0
    pluie_demain = pluie_demain or 0.0
    humidite = humidite or 0.0
    temperature = temperature or 0.0
    etp = etp or 0.0
    arrosage_recent = compute_recent_watering_mm(history, today=today, days=1)
    now_hour = hour_of_day if hour_of_day is not None else datetime.now().hour
    prochain_creneau = "ce matin" if now_hour < 9 else "demain matin"

    if score_hydrique >= 75 or score_stress >= 80:
        urgence = "haute"
    elif score_hydrique >= 40 or score_stress >= 55:
        urgence = "moyenne"
    else:
        urgence = "faible"

    if phase_active == "Traitement":
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
            "urgence": "faible",
            "score_tonte": score_tonte,
        }
    if phase_active == "Hivernage":
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
            "urgence": "faible",
            "score_tonte": score_tonte,
        }
    if phase_active == "Sursemis":
        passages = 3 if objectif_mm >= 2 else 2
        return {
            "tonte_autorisee": False,
            "arrosage_auto_autorise": False,
            "arrosage_recommande": objectif_mm > 0,
            "type_arrosage": "manuel_frequent",
            "arrosage_conseille": "personnalise",
            "raison_decision": (
                f"Sursemis en cours + manque d'eau estimé à {objectif_mm} mm. "
                f"Pluie prévue demain: {pluie_demain:.1f} mm."
            ),
            "conseil_principal": f"Arroser {prochain_creneau} en {passages} passages courts.",
            "action_recommandee": f"Appliquer {objectif_mm} mm fractionnés ({passages}x).",
            "action_a_eviter": "Tondre avant levée complète.",
            "urgence": "haute" if score_hydrique >= 45 else "moyenne",
            "score_tonte": score_tonte,
        }

    tonte_ok = score_tonte < 45 and score_stress < 70
    auto_ok = phase_active in {"Normal", "Fertilisation", "Biostimulant", "Agent Mouillant", "Scarification"}
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

    if phase_active == "Normal":
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
            conseil_principal = f"Phase {phase_active}: pas d'arrosage requis pour l'instant."
            action_recommandee = "Surveiller les capteurs et l'évolution météo."
        elif phase_active == "Fertilisation":
            conseil_principal = "Fertilisation active: humidifier légèrement pour activer l'apport."
            action_recommandee = f"Appliquer {objectif_mm} mm en 1 à 2 passages."
        elif phase_active == "Scarification":
            conseil_principal = "Scarification: maintenir une humidité stable sans détremper."
            action_recommandee = f"Appliquer {objectif_mm} mm en apports courts."
        elif phase_active == "Agent Mouillant":
            conseil_principal = "Agent mouillant: faire pénétrer l'eau plus en profondeur."
            action_recommandee = f"Appliquer {objectif_mm} mm en cycle allongé."
        elif phase_active == "Biostimulant":
            conseil_principal = "Biostimulant: conserver un niveau hydrique modéré."
            action_recommandee = f"Appliquer {objectif_mm} mm en un passage."
        else:
            conseil_principal = f"Phase {phase_active}: maintenir un arrosage maîtrisé {prochain_creneau}."
            action_recommandee = f"Appliquer {objectif_mm} mm en tenant compte de l'humidité actuelle."
        action_a_eviter = "Tondre sur sol humide." if not tonte_ok else "Intervention agressive inutile."

    facteurs = [f"besoin_eau={etp:.1f}", f"pluie_24h={pluie_24h:.1f}", f"pluie_demain={pluie_demain:.1f}"]
    if pluie_significative:
        facteurs.append("risque d'humidité élevé")
    if stress_thermique:
        facteurs.append("stress thermique")
    if arrosage_recent > 0:
        facteurs.append(f"arrosage récent={arrosage_recent:.1f} mm")
    if humidite_haute:
        facteurs.append("humidité air élevée")
    facteurs_txt = ", ".join(facteurs)

    return {
        "tonte_autorisee": tonte_ok,
        "arrosage_auto_autorise": auto_ok,
        "arrosage_recommande": recommande,
        "type_arrosage": "auto" if auto_ok else "personnalise",
        "arrosage_conseille": "auto" if phase_active == "Normal" else "personnalise",
        "raison_decision": (
            f"Mode {phase_active} en cours ({jours_restants} jour(s) restants). "
            f"Niveaux: eau={score_hydrique}/stress={score_stress}/tonte={score_tonte}. {facteurs_txt}. {tonte_reason}"
        ),
        "conseil_principal": conseil_principal,
        "action_recommandee": action_recommandee,
        "action_a_eviter": action_a_eviter,
        "urgence": urgence if recommande else "faible",
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
) -> dict[str, Any]:
    today = today or date.today()
    etp = compute_etp(temperature=temperature, pluie_24h=pluie_24h, etp_capteur=etp_capteur)
    phase_active, date_action, date_fin = compute_phase_active(history, today=today, temperature=temperature)
    jours_restants = compute_jours_restants_for(phase_active=phase_active, date_fin=date_fin, today=today)
    bilan_hydrique = compute_bilan_hydrique(
        etp=etp,
        pluie_24h=pluie_24h,
        pluie_demain=pluie_demain,
        type_sol=type_sol,
        recent_watering_mm=compute_recent_watering_mm(history, today=today, days=2),
    )
    scores = compute_internal_scores(
        history=history,
        today=today,
        phase_active=phase_active,
        bilan_hydrique=bilan_hydrique,
        pluie_24h=pluie_24h,
        pluie_demain=pluie_demain,
        humidite=humidite,
        temperature=temperature,
        etp=etp,
    )
    objectif_mm = compute_objectif_mm(
        bilan_hydrique=bilan_hydrique,
        phase_active=phase_active,
        score_hydrique=scores["score_hydrique"],
        score_stress=scores["score_stress"],
    )
    decision = compute_decision(
        phase_active=phase_active,
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
        "mode": phase_active,
        "phase_active": phase_active,
        "date_action": date_action,
        "date_fin": date_fin,
        "etp": etp,
        "bilan_hydrique_mm": bilan_hydrique,
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
        "urgence": decision["urgence"],
        "score_tonte": decision["score_tonte"],
        "jours_restants": jours_restants,
    }
