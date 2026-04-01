from __future__ import annotations

"""Centralise les suffixes d'entités exposées par l'intégration.

La liste sert à deux choses:
- garder la migration HA cohérente
- détecter en test toute entité visible qui sortirait du périmètre
"""

ACTIVE_ENTITY_SUFFIXES: set[str] = {
    "mode",
    "debit_zone_1",
    "debit_zone_2",
    "debit_zone_3",
    "debit_zone_4",
    "debit_zone_5",
    "hauteur_min_tondeuse_cm",
    "hauteur_max_tondeuse_cm",
    "tonte_autorisee",
    "arrosage_recommande",
    "retour_mode_normal",
    "date_action_today",
    "hauteur_tonte",
    "phase_active",
    "sous_phase",
    "objectif_mm",
    "tonte_etat",
    "conseil_principal",
    "assistant",
    "action_recommandee",
    "action_a_eviter",
    "niveau_action",
    "fenetre_optimale",
    "risque_gazon",
    "type_arrosage",
    "plan_arrosage",
    "dernier_arrosage_detecte",
    "derniere_application",
    "derniere_action_utilisateur",
    "catalogue_produits",
    "produit_intervention",
    "arrosage_apres_application_autorise",
    "arrosage_automatique",
    "arroser_maintenant",
}
