from __future__ import annotations

from datetime import date, datetime
from importlib import util
from pathlib import Path
from typing import Any

_MODULE_DIR = Path(__file__).resolve().parent


def _load_local_module(module_name: str, filename: str):
    spec = util.spec_from_file_location(module_name, _MODULE_DIR / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Impossible de charger {filename}")
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_phases = _load_local_module("_gazon_intelligent_phases", "phases.py")
_water = _load_local_module("_gazon_intelligent_water", "water.py")
_scores = _load_local_module("_gazon_intelligent_scores", "scores.py")
_memory = _load_local_module("_gazon_intelligent_memory", "memory.py")
_guidance = _load_local_module("_gazon_intelligent_guidance", "guidance.py")

_memory.PHASE_DURATIONS_DAYS = _phases.PHASE_DURATIONS_DAYS
_memory.SIGNIFICANT_WATERING_THRESHOLD_MM = _phases.SIGNIFICANT_WATERING_THRESHOLD_MM

PHASE_DURATIONS_DAYS = _phases.PHASE_DURATIONS_DAYS
PHASE_PRIORITIES = _phases.PHASE_PRIORITIES
SIGNIFICANT_WATERING_THRESHOLD_MM = _phases.SIGNIFICANT_WATERING_THRESHOLD_MM
SUBPHASE_RULES = _phases.SUBPHASE_RULES
compute_dominant_phase = _phases.compute_dominant_phase
compute_phase_active = _phases.compute_phase_active
compute_subphase = _phases.compute_subphase
is_hivernage = _phases.is_hivernage
phase_duration_days = _phases.phase_duration_days

compute_advanced_context = _water.compute_advanced_context
compute_etp = _water.compute_etp
compute_recent_watering_mm = _water.compute_recent_watering_mm
compute_water_balance = _water.compute_water_balance

compute_internal_scores = _scores.compute_internal_scores

compute_memory = _memory.compute_memory

compute_action_guidance = _guidance.compute_action_guidance
compute_jours_restants_for = _guidance.compute_jours_restants_for
compute_next_reevaluation = _guidance.compute_next_reevaluation
compute_legacy_urgence = _guidance.compute_legacy_urgence
compute_objectif_mm = _guidance.compute_objectif_mm
compute_tonte_statut = _guidance.compute_tonte_statut


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
            "tonte_statut": "interdite",
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
            "urgence": "faible",
            "prochaine_reevaluation": prochaine_reevaluation,
            "score_tonte": score_tonte,
        }
    if phase_dominante == "Hivernage":
        return {
            "tonte_autorisee": False,
            "tonte_statut": "interdite",
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
            "urgence": "faible",
            "prochaine_reevaluation": prochaine_reevaluation,
            "score_tonte": score_tonte,
        }
    if phase_dominante == "Sursemis":
        passages = 3 if objectif_mm >= 2 else 2
        urgence_sursemis = "haute" if score_hydrique >= 45 or action_guidance["risque_gazon"] == "eleve" else "moyenne"
        return {
            "tonte_autorisee": False,
            "tonte_statut": "interdite",
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
            "urgence": urgence_sursemis,
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
    tonte_statut = compute_tonte_statut(
        phase_dominante=phase_dominante,
        tonte_autorisee=tonte_ok,
        score_tonte=score_tonte,
        risque_gazon=action_guidance["risque_gazon"],
    )
    urgence = compute_legacy_urgence(
        phase_dominante=phase_dominante,
        arrosage_recommande=recommande,
        niveau_action=action_guidance["niveau_action"],
        risque_gazon=action_guidance["risque_gazon"],
        score_hydrique=score_hydrique,
        score_stress=score_stress,
    )

    return {
        "tonte_autorisee": tonte_ok,
        "tonte_statut": tonte_statut,
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
        "urgence": urgence,
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
    weather_profile: dict[str, Any] | None = None,
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
        weather_profile=weather_profile,
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
        "tonte_statut": decision["tonte_statut"],
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
        "urgence": decision["urgence"],
        "prochaine_reevaluation": decision["prochaine_reevaluation"],
        "score_tonte": decision["score_tonte"],
        "jours_restants": jours_restants,
    }
