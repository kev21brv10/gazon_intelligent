from __future__ import annotations

"""Centralise les suffixes d'entités exposées par l'intégration.

La liste sert à deux choses:
- garder la migration HA cohérente
- détecter en test toute entité visible qui sortirait du périmètre
"""

from .const import DOMAIN

PUBLIC_ENTITY_KEYS: dict[str, tuple[str, str]] = {
    "mode": ("select", f"{DOMAIN}_mode_du_gazon"),
    "debit_zone_1": ("number", f"{DOMAIN}_debit_zone_1"),
    "debit_zone_2": ("number", f"{DOMAIN}_debit_zone_2"),
    "debit_zone_3": ("number", f"{DOMAIN}_debit_zone_3"),
    "debit_zone_4": ("number", f"{DOMAIN}_debit_zone_4"),
    "debit_zone_5": ("number", f"{DOMAIN}_debit_zone_5"),
    "hauteur_min_tondeuse_cm": ("number", f"{DOMAIN}_hauteur_min_tondeuse"),
    "hauteur_max_tondeuse_cm": ("number", f"{DOMAIN}_hauteur_max_tondeuse"),
    "tonte_autorisee": ("binary_sensor", f"{DOMAIN}_tonte_autorisee"),
    "arrosage_recommande": ("binary_sensor", f"{DOMAIN}_arrosage_recommande"),
    "retour_mode_normal": ("button", f"{DOMAIN}_retour_mode_normal"),
    "date_action_today": ("button", f"{DOMAIN}_date_action_today"),
    "hauteur_tonte": ("sensor", f"{DOMAIN}_hauteur_de_tonte_conseillee"),
    "phase_active": ("sensor", f"{DOMAIN}_phase_dominante"),
    "sous_phase": ("sensor", f"{DOMAIN}_sous_phase"),
    "objectif_mm": ("sensor", f"{DOMAIN}_objectif_d_arrosage"),
    "tonte_etat": ("sensor", f"{DOMAIN}_etat_de_tonte"),
    "conseil_principal": ("sensor", f"{DOMAIN}_conseil_principal"),
    "assistant": ("sensor", f"{DOMAIN}_assistant"),
    "action_recommandee": ("sensor", f"{DOMAIN}_action_recommandee"),
    "action_a_eviter": ("sensor", f"{DOMAIN}_action_a_eviter"),
    "niveau_action": ("sensor", f"{DOMAIN}_niveau_d_action"),
    "fenetre_optimale": ("sensor", f"{DOMAIN}_fenetre_optimale"),
    "risque_gazon": ("sensor", f"{DOMAIN}_risque_gazon"),
    "type_arrosage": ("sensor", f"{DOMAIN}_type_d_arrosage"),
    "plan_arrosage": ("sensor", f"{DOMAIN}_plan_d_arrosage"),
    "arrosage_en_cours": ("sensor", f"{DOMAIN}_arrosage_en_cours"),
    "dernier_arrosage_detecte": ("sensor", f"{DOMAIN}_dernier_arrosage_detecte"),
    "derniere_application": ("sensor", f"{DOMAIN}_derniere_application"),
    "derniere_action_utilisateur": ("sensor", f"{DOMAIN}_derniere_action_utilisateur"),
    "catalogue_produits": ("sensor", f"{DOMAIN}_catalogue_produits"),
    "produit_intervention": ("select", f"{DOMAIN}_produit_d_intervention"),
    "prochaine_intervention": ("sensor", f"{DOMAIN}_prochaine_intervention"),
    "debug_intervention": ("sensor", f"{DOMAIN}_debug_intervention"),
    "score_niveau": ("sensor", f"{DOMAIN}_niveau_de_pertinence"),
    "prochaine_fenetre_optimale": ("sensor", f"{DOMAIN}_prochaine_fenetre_optimale"),
    "prochain_blocage_attendu": ("sensor", f"{DOMAIN}_prochain_blocage_attendu"),
    "signal_intervention": ("binary_sensor", f"{DOMAIN}_signal_intervention"),
    "signal_irrigation": ("binary_sensor", f"{DOMAIN}_signal_irrigation"),
    "arrosage_apres_application_autorise": ("binary_sensor", f"{DOMAIN}_arrosage_apres_application_autorise"),
    "arrosage_automatique": ("switch", f"{DOMAIN}_arrosage_automatique_autorise"),
    "arroser_maintenant": ("button", f"{DOMAIN}_arroser_maintenant"),
}

ACTIVE_ENTITY_SUFFIXES: set[str] = set(PUBLIC_ENTITY_KEYS)


def public_entity_domain(suffix: str) -> str:
    return PUBLIC_ENTITY_KEYS[suffix][0]


def public_entity_id(platform: str, suffix: str) -> str:
    expected_platform, object_id = PUBLIC_ENTITY_KEYS[suffix]
    if expected_platform != platform:
        raise ValueError(f"Suffixe {suffix} attendu pour {expected_platform}, pas {platform}")
    return f"{platform}.{object_id}"
