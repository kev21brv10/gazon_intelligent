from __future__ import annotations

"""Logique pure d'arrosage et de recommandations utilisateur."""

from typing import Any

from .decision_models import DecisionContext
from .guidance import compute_objectif_mm, is_fertilization_window_open
from .scores import classify_stress_level
from .water import compute_advanced_context, compute_etp, compute_water_balance


def build_water_bundle(
    context: DecisionContext,
    phase_bundle: dict[str, Any],
) -> dict[str, Any]:
    advanced_context = compute_advanced_context(
        humidite_sol=context.humidite_sol,
        vent=context.vent,
        rosee=context.rosee,
        hauteur_gazon=context.hauteur_gazon,
        retour_arrosage=context.retour_arrosage,
        pluie_source=context.pluie_source,
        weather_profile=context.weather_profile,
    )
    etp = compute_etp(
        temperature=context.temperature,
        pluie_24h=context.pluie_24h,
        etp_capteur=context.etp_capteur,
        weather_profile=context.weather_profile,
    )
    water_balance = compute_water_balance(
        history=context.history,
        today=context.today,
        etp=etp,
        pluie_24h=context.pluie_24h,
        pluie_demain=context.pluie_demain,
        type_sol=context.type_sol,
        recent_watering_mm_override=context.retour_arrosage,
        advanced_context=advanced_context,
        weather_profile=context.weather_profile,
    )
    balance_snapshot = dict(water_balance)
    balance_snapshot["bilan_hydrique_journalier_mm"] = balance_snapshot.get("bilan_hydrique_mm", 0.0)
    if context.soil_balance:
        reserve_mm = context.soil_balance.get("reserve_mm")
        if reserve_mm is not None:
            balance_snapshot["bilan_hydrique_mm"] = reserve_mm
        balance_snapshot["soil_balance"] = context.soil_balance
        balance_snapshot["bilan_hydrique_precedent_mm"] = context.soil_balance.get("previous_reserve_mm")
        balance_snapshot["pluie_jour_mm"] = context.soil_balance.get("pluie_mm")
        balance_snapshot["arrosage_jour_mm"] = context.soil_balance.get("arrosage_mm")
        balance_snapshot["etp_jour_mm"] = context.soil_balance.get("etp_mm")
        balance_snapshot["delta_jour_mm"] = context.soil_balance.get("delta_mm")
    objective_mm = compute_objectif_mm(
        phase_dominante=phase_bundle["phase_dominante"],
        sous_phase=phase_bundle["sous_phase"],
        water_balance=balance_snapshot,
        today=context.today,
        pluie_demain=context.pluie_demain,
        humidite=context.humidite,
        temperature=context.temperature,
        etp=etp,
        type_sol=context.type_sol,
    )
    return {
        "etp": etp,
        "advanced_context": advanced_context,
        "water_balance": balance_snapshot,
        "objectif_mm": objective_mm,
    }


def _passage_spacing_text(passages: int) -> str:
    if passages <= 1:
        return "en un passage"
    if passages == 2:
        return "en 2 passages courts espacés de 20 à 30 min"
    return f"en {passages} passages courts espacés de 20 min"


def _watering_needed_text() -> str:
    return "Éviter tout arrosage inutile."


def _soil_fractionation_passages(
    phase_dominante: str,
    type_sol: str,
    objectif_mm: float,
    stress_level: str,
) -> int:
    soil_profile = (type_sol or "limoneux").strip().lower()
    if phase_dominante == "Sursemis":
        return 3 if objectif_mm >= 2.0 else 2
    if phase_dominante in {"Fertilisation", "Biostimulant"}:
        if soil_profile == "argileux" or stress_level == "fort" or objectif_mm >= 1.5:
            return 2
        return 1
    if soil_profile == "argileux" and objectif_mm >= 2.5:
        return 2
    if stress_level == "fort" and objectif_mm >= 2.0:
        return 2
    return 1


def _watering_style_text(
    phase_dominante: str,
    type_sol: str,
    objectif_mm: float,
    stress_level: str,
    passage_count: int | None = None,
) -> str:
    passages = passage_count or _soil_fractionation_passages(phase_dominante, type_sol, objectif_mm, stress_level)
    soil_profile = (type_sol or "limoneux").strip().lower()
    if passages <= 1:
        if soil_profile == "sableux":
            return "en un passage profond tôt le matin"
        return "en un passage profond tôt le matin"
    if passages == 2:
        return "en 2 passages courts espacés de 20 à 30 min"
    return "en 3 passages courts espacés de 20 à 30 min"


def _watering_amount_text(mm: float) -> str:
    if mm <= 0:
        return "Aucun arrosage nécessaire."
    return f"{mm:.1f} mm"


def build_watering_bundle(
    context: DecisionContext,
    phase_bundle: dict[str, Any],
    water_bundle: dict[str, Any],
    risk_bundle: dict[str, Any],
    mowing_bundle: dict[str, Any],
) -> dict[str, Any]:
    phase_dominante = phase_bundle["phase_dominante"]
    sous_phase = phase_bundle["sous_phase"]
    water_balance = water_bundle["water_balance"]
    advanced_context = water_bundle["advanced_context"]
    objectif_mm = water_bundle["objectif_mm"]
    niveau_action = risk_bundle["niveau_action"]
    fenetre_optimale = risk_bundle["fenetre_optimale"]
    risque_gazon = risk_bundle["risque_gazon"]
    prochaine_reevaluation = risk_bundle["prochaine_reevaluation"]
    score_tonte = mowing_bundle["score_tonte"]
    score_stress = mowing_bundle["score_stress"]
    tonte_ok = mowing_bundle["tonte_autorisee"]
    tonte_reason = mowing_bundle["tonte_reason"]

    now_hour = context.hour_of_day if context.hour_of_day is not None else 0
    prochain_creneau = "ce matin" if now_hour < 9 else "demain matin"
    arrosage_recent = water_balance.get("arrosage_recent", 0.0)
    deficit_3j = water_balance.get("deficit_3j", 0.0)
    deficit_7j = water_balance.get("deficit_7j", 0.0)
    bilan_hydrique_mm = water_balance.get("bilan_hydrique_mm", 0.0)
    bilan_hydrique_3j = water_balance.get("bilan_hydrique_3j", 0.0)
    bilan_hydrique_7j = water_balance.get("bilan_hydrique_7j", 0.0)
    pluie_efficace = water_balance.get("pluie_efficace", 0.0)
    pluie_24h = context.pluie_24h or 0.0
    pluie_demain = context.pluie_demain or 0.0
    humidite = context.humidite or 0.0
    temperature = context.temperature or 0.0
    etp = water_bundle["etp"] or 0.0
    stress_level = classify_stress_level(
        score_hydrique=int(risk_bundle["scores"]["score_hydrique"]),
        score_stress=int(score_stress),
        water_balance=water_balance,
        temperature=temperature,
        etp=etp,
    )
    fertilization_allowed = is_fertilization_window_open(
        today=context.today,
        temperature=temperature,
        humidite=humidite,
        etp=etp,
        water_balance=water_balance,
    )
    soil_style = context.type_sol

    pluie_significative = pluie_24h >= 4 or pluie_demain >= 4
    pluie_compensatrice = objectif_mm > 0 and pluie_demain >= max(2.0, objectif_mm * 0.8)
    stress_thermique = temperature >= 30 and etp >= 4
    humidite_haute = humidite >= 85
    besoin_eau = (
        bilan_hydrique_mm <= -0.2
        or deficit_3j > 0.8
        or deficit_7j > 1.5
    )
    recommande = objectif_mm > 0 and besoin_eau
    auto_ok = phase_dominante in {"Normal", "Fertilisation", "Biostimulant", "Agent Mouillant", "Scarification"}

    if phase_dominante == "Traitement":
        return {
            "tonte_autorisee": False,
            "tonte_statut": "interdite",
            "arrosage_auto_autorise": False,
            "arrosage_recommande": False,
            "type_arrosage": "bloque",
            "arrosage_conseille": "personnalise",
            "conseil_principal": f"Laisser agir le traitement encore {phase_bundle['jours_restants']} jour(s).",
            "action_recommandee": "Surveiller l'état du gazon sans intervention hydrique.",
            "action_a_eviter": "Tondre ou arroser.",
            "raison_decision": "Traitement actif: tonte et arrosage bloqués.",
            "decision_resume": {
                "faire": False,
                "action": "surveillance",
                "moment": "attendre",
                "objectif_mm": objectif_mm,
                "type_arrosage": "bloque",
                "niveau_action": niveau_action,
                "risque_gazon": risque_gazon,
            },
        }

    if phase_dominante == "Hivernage":
        return {
            "tonte_autorisee": False,
            "tonte_statut": "interdite",
            "arrosage_auto_autorise": False,
            "arrosage_recommande": False,
            "type_arrosage": "bloque",
            "arrosage_conseille": "personnalise",
            "conseil_principal": "N'arrose pas et limite les interventions.",
            "action_recommandee": "Surveille uniquement.",
            "action_a_eviter": "Arroser fréquemment.",
            "raison_decision": "Hivernage actif: repos végétatif.",
            "decision_resume": {
                "faire": False,
                "action": "surveillance",
                "moment": "attendre",
                "objectif_mm": objectif_mm,
                "type_arrosage": "bloque",
                "niveau_action": niveau_action,
                "risque_gazon": risque_gazon,
            },
        }

    if phase_dominante in {"Fertilisation", "Biostimulant"} and not fertilization_allowed:
        return {
            "tonte_autorisee": tonte_ok,
            "tonte_statut": mowing_bundle["tonte_statut"],
            "arrosage_auto_autorise": False,
            "arrosage_recommande": False,
            "type_arrosage": "bloque",
            "arrosage_conseille": "personnalise",
            "conseil_principal": (
                f"{phase_dominante}: reporte l'application, la fenêtre est trop chaude ou trop sèche."
            ),
            "action_recommandee": "Attends un créneau plus frais et moins stressant.",
            "action_a_eviter": "Fertiliser sous chaleur ou stress hydrique.",
            "raison_decision": (
                f"{phase_dominante} bloqué: bilan={bilan_hydrique_mm:.1f} mm, "
                f"stress={stress_level}, température={temperature:.1f}°C, ETP={etp:.1f} mm."
            ),
            "decision_resume": {
                "faire": False,
                "action": "surveillance",
                "moment": "attendre",
                "objectif_mm": 0.0,
                "type_arrosage": "bloque",
                "niveau_action": "surveiller",
                "risque_gazon": risque_gazon,
            },
            "niveau_action": "surveiller",
            "fenetre_optimale": "attendre",
            "risque_gazon": risque_gazon,
            "prochaine_reevaluation": prochaine_reevaluation,
        }

    if phase_dominante == "Sursemis":
        passages = 3 if objectif_mm >= 2 else 2
        passage_spacing = _passage_spacing_text(passages)
        if objectif_mm <= 0:
            conseil_principal = "Aucun arrosage nécessaire pour le sursemis."
            action_recommandee = "Surveille l'humidité et réévalue au prochain créneau."
            action_a_eviter = _watering_needed_text()
            return {
                "tonte_autorisee": False,
                "tonte_statut": "interdite",
                "arrosage_auto_autorise": False,
                "arrosage_recommande": False,
                "type_arrosage": "personnalise",
                "arrosage_conseille": "personnalise",
                "conseil_principal": conseil_principal,
                "action_recommandee": action_recommandee,
                "action_a_eviter": action_a_eviter,
                "raison_decision": (
                    f"Sursemis / {sous_phase}: objectif nul, bilan={bilan_hydrique_mm:.1f} mm, "
                    f"tendance 3j={bilan_hydrique_3j:.1f} mm, 7j={bilan_hydrique_7j:.1f} mm."
                ),
                "decision_resume": {
                    "faire": False,
                    "action": "surveillance",
                    "moment": "attendre",
                    "objectif_mm": objectif_mm,
                    "type_arrosage": "personnalise",
                    "niveau_action": "surveiller",
                    "risque_gazon": risque_gazon,
                },
                "niveau_action": "surveiller",
                "fenetre_optimale": "attendre",
                "risque_gazon": risque_gazon,
                "prochaine_reevaluation": prochaine_reevaluation,
                "tonte_autorisee": False,
                "tonte_statut": "interdite",
            }
        if pluie_demain >= 2 and bilan_hydrique_mm >= -0.5:
            conseil_principal = "Réduis ou reporte l'arrosage: la pluie de demain peut compenser une grande partie du déficit."
            reduction_mm = round(objectif_mm * 0.4, 1)
            if reduction_mm > 0:
                action_recommandee = f"Réduis l'apport à {reduction_mm:.1f} mm maximum aujourd'hui."
            else:
                action_recommandee = _watering_needed_text()
            action_a_eviter = "Lancer un cycle complet avant la pluie."
        elif humidite_haute:
            conseil_principal = "Attends un léger ressuyage avant d'arroser."
            action_recommandee = f"Programme {objectif_mm:.1f} mm en fin de nuit si l'humidité baisse."
            action_a_eviter = "Arroser immédiatement sur pelouse saturée."
        else:
            conseil_principal = f"Arroser {prochain_creneau} {passage_spacing}."
            action_recommandee = f"Appliquer {objectif_mm:.1f} mm fractionnés ({passages}x, 20 à 30 min entre les passages)."
            action_a_eviter = "Tondre avant levée complète."
        return {
            "tonte_autorisee": False,
            "tonte_statut": "interdite",
            "arrosage_auto_autorise": False,
            "arrosage_recommande": objectif_mm > 0,
            "type_arrosage": "manuel_frequent",
            "arrosage_conseille": "personnalise",
            "conseil_principal": conseil_principal,
            "action_recommandee": action_recommandee,
            "action_a_eviter": action_a_eviter,
            "raison_decision": (
                f"Sursemis / {sous_phase}: bilan={bilan_hydrique_mm:.1f} mm, tendance 3j={bilan_hydrique_3j:.1f} mm, 7j={bilan_hydrique_7j:.1f} mm. "
                f"Pluie efficace={pluie_efficace:.1f} mm."
            ),
            "decision_resume": {
                "faire": objectif_mm > 0,
                "action": "arrosage",
                "moment": fenetre_optimale,
                "objectif_mm": objectif_mm,
                "type_arrosage": "manuel_frequent",
                "niveau_action": niveau_action,
                "risque_gazon": risque_gazon,
            },
        }

    if not recommande:
        conseil_principal = f"Phase {phase_dominante}: n'arrose pas pour l'instant."
        action_recommandee = "Surveille les capteurs et l'évolution météo."
        action_a_eviter = "Éviter tout arrosage inutile."
        type_arrosage = "personnalise"
        arrosage_recommande = False
        arrosage_auto_autorise = False
        arrosage_conseille = "personnalise"
    elif phase_dominante == "Fertilisation":
        passages = _soil_fractionation_passages(phase_dominante, soil_style, objectif_mm, stress_level)
        style_text = _watering_style_text(phase_dominante, soil_style, objectif_mm, stress_level, passages)
        conseil_principal = "Fertilisation active: arrose légèrement, de préférence le matin."
        action_recommandee = f"Applique {objectif_mm:.1f} mm {style_text} pour activer l'apport."
        action_a_eviter = "Tondre sur sol humide."
        type_arrosage = "auto"
        arrosage_recommande = True
        arrosage_auto_autorise = auto_ok
        arrosage_conseille = "auto" if phase_dominante == "Normal" else "personnalise"
    elif phase_dominante == "Scarification":
        passages = _soil_fractionation_passages(phase_dominante, soil_style, objectif_mm, stress_level)
        style_text = _watering_style_text(phase_dominante, soil_style, objectif_mm, stress_level, passages)
        conseil_principal = "Scarification: garde une humidité stable sans détremper."
        action_recommandee = f"Applique {objectif_mm:.1f} mm {style_text}."
        action_a_eviter = "Saturer le sol."
        type_arrosage = "auto"
        arrosage_recommande = True
        arrosage_auto_autorise = auto_ok
        arrosage_conseille = "personnalise"
    elif phase_dominante == "Agent Mouillant":
        passages = _soil_fractionation_passages(phase_dominante, soil_style, objectif_mm, stress_level)
        style_text = _watering_style_text(phase_dominante, soil_style, objectif_mm, stress_level, passages)
        conseil_principal = "Agent mouillant: fais pénétrer l'eau plus en profondeur."
        action_recommandee = f"Applique {objectif_mm:.1f} mm {style_text}."
        action_a_eviter = "Arroser trop vite."
        type_arrosage = "auto"
        arrosage_recommande = True
        arrosage_auto_autorise = auto_ok
        arrosage_conseille = "personnalise"
    elif phase_dominante == "Biostimulant":
        passages = _soil_fractionation_passages(phase_dominante, soil_style, objectif_mm, stress_level)
        style_text = _watering_style_text(phase_dominante, soil_style, objectif_mm, stress_level, passages)
        conseil_principal = "Biostimulant: garde un niveau hydrique modéré."
        action_recommandee = f"Applique {objectif_mm:.1f} mm {style_text}."
        action_a_eviter = "Détremper le sol."
        type_arrosage = "auto"
        arrosage_recommande = True
        arrosage_auto_autorise = auto_ok
        arrosage_conseille = "personnalise"
    else:
        passages = _soil_fractionation_passages(phase_dominante, soil_style, objectif_mm, stress_level)
        style_text = _watering_style_text(phase_dominante, soil_style, objectif_mm, stress_level, passages)
        conseil_principal = f"Phase {phase_dominante}: arrose de façon maîtrisée {prochain_creneau}."
        action_recommandee = f"Applique {objectif_mm:.1f} mm {style_text} en tenant compte de l'humidité actuelle."
        action_a_eviter = "Arroser en pleine journée."
        type_arrosage = "auto" if auto_ok else "personnalise"
        arrosage_recommande = True
        arrosage_auto_autorise = auto_ok
        arrosage_conseille = "auto" if phase_dominante == "Normal" else "personnalise"

    if phase_dominante == "Normal":
        if not recommande:
            if pluie_demain >= 2:
                conseil_principal = "N'arrose pas aujourd'hui: la pluie prévue couvre le besoin court terme."
                action_recommandee = "Laisse la pluie agir puis réévalue demain."
                action_a_eviter = "Cumuler pluie et arrosage."
            else:
                conseil_principal = "N'arrose pas pour le moment."
                action_recommandee = "Réévalue au prochain cycle météo."
                action_a_eviter = "Éviter tout arrosage inutile."
        else:
            if pluie_compensatrice:
                reduction_mm = round(objectif_mm * 0.4, 1)
                conseil_principal = "Réduis ou reporte l'arrosage: la pluie de demain peut compenser une grande partie du déficit."
                if reduction_mm >= 0.5:
                    action_recommandee = f"Réduis l'apport à {reduction_mm:.1f} mm maximum aujourd'hui."
                else:
                    action_recommandee = _watering_needed_text()
                action_a_eviter = "Lancer un cycle complet avant la pluie."
            elif stress_thermique:
                passages = _soil_fractionation_passages(phase_dominante, soil_style, objectif_mm, stress_level)
                style_text = _watering_style_text(phase_dominante, soil_style, objectif_mm, stress_level, passages)
                conseil_principal = f"Arrose {prochain_creneau} en privilégiant la recharge de la réserve."
                action_recommandee = f"Applique {objectif_mm:.1f} mm {style_text}."
                action_a_eviter = "Arroser entre 11h et 18h."
            elif humidite_haute:
                conseil_principal = "Attends un léger ressuyage avant d'arroser."
                action_recommandee = "Reporte l'arrosage au prochain créneau sec."
                action_a_eviter = "Arroser immédiatement sur pelouse saturée."
            else:
                passages = _soil_fractionation_passages(phase_dominante, soil_style, objectif_mm, stress_level)
                style_text = _watering_style_text(phase_dominante, soil_style, objectif_mm, stress_level, passages)
                conseil_principal = f"Arrose {prochain_creneau}: recharge la réserve sans micro-apports."
                action_recommandee = f"Applique {objectif_mm:.1f} mm {style_text}."
                action_a_eviter = "Arroser en pleine journée ou multiplier les petits cycles."

    decision_resume = {
        "faire": arrosage_recommande,
        "action": "arrosage" if arrosage_recommande else ("aucune_action" if mowing_bundle["tonte_autorisee"] else "surveillance"),
        "moment": fenetre_optimale,
        "objectif_mm": objectif_mm,
        "type_arrosage": type_arrosage,
        "niveau_action": niveau_action,
        "risque_gazon": risque_gazon,
    }

    raison_parts = [
        f"Mode {phase_dominante} / {sous_phase} en cours ({phase_bundle['jours_restants']} jour(s) restants).",
        f"Bilan hydrique={bilan_hydrique_mm:.1f} mm, tendance 3j={bilan_hydrique_3j:.1f} mm, 7j={bilan_hydrique_7j:.1f} mm.",
        f"Pluie efficace={pluie_efficace:.1f} mm.",
    ]
    if pluie_significative:
        raison_parts.append("risque d'humidité élevé")
    if stress_thermique:
        raison_parts.append("stress thermique")
    if humidite_haute:
        raison_parts.append("humidité air élevée")
    if advanced_context.get("humidite_sol") is not None:
        raison_parts.append(f"humidite_sol={advanced_context['humidite_sol']}")
    if advanced_context.get("vent") is not None:
        raison_parts.append(f"vent={advanced_context['vent']}")
    if advanced_context.get("rosee") is not None and advanced_context.get("rosee") > 0:
        raison_parts.append("rosée présente")
    if advanced_context.get("hauteur_gazon") is not None:
        raison_parts.append(f"hauteur_gazon={advanced_context['hauteur_gazon']}")
    if advanced_context.get("retour_arrosage") is not None:
        raison_parts.append(f"retour_arrosage={advanced_context['retour_arrosage']}")
    raison_parts.append(tonte_reason)

    return {
        "conseil_principal": conseil_principal,
        "action_recommandee": action_recommandee,
        "action_a_eviter": action_a_eviter,
        "arrosage_recommande": arrosage_recommande,
        "arrosage_auto_autorise": arrosage_auto_autorise,
        "type_arrosage": type_arrosage,
        "arrosage_conseille": arrosage_conseille,
        "decision_resume": decision_resume,
        "raison_decision": " ".join(raison_parts),
        "niveau_action": niveau_action,
        "fenetre_optimale": fenetre_optimale,
        "risque_gazon": risque_gazon,
        "prochaine_reevaluation": prochaine_reevaluation,
        "tonte_autorisee": mowing_bundle["tonte_autorisee"],
        "tonte_statut": mowing_bundle["tonte_statut"],
    }
