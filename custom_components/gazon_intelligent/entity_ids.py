from __future__ import annotations

"""Centralise les suffixes d'entités exposées par l'intégration.

La liste sert à deux choses:
- garder la migration HA cohérente
- détecter en test toute entité visible qui sortirait du périmètre
"""

from collections.abc import Mapping
from typing import Any
import re
import unicodedata

from .const import DOMAIN
from .const import CONF_INSTANCE_SLUG

PUBLIC_ENTITY_KEYS: dict[str, tuple[str, str]] = {
    "mode": ("select", f"{DOMAIN}_mode_du_gazon"),
    "debit_zone_1": ("number", f"{DOMAIN}_debit_zone_1"),
    "debit_zone_2": ("number", f"{DOMAIN}_debit_zone_2"),
    "debit_zone_3": ("number", f"{DOMAIN}_debit_zone_3"),
    "debit_zone_4": ("number", f"{DOMAIN}_debit_zone_4"),
    "debit_zone_5": ("number", f"{DOMAIN}_debit_zone_5"),
    "hauteur_min_tondeuse_cm": ("number", f"{DOMAIN}_hauteur_min_tondeuse"),
    "hauteur_max_tondeuse_cm": ("number", f"{DOMAIN}_hauteur_max_tondeuse"),
    "hauteur_coupe_tondeuse": ("number", f"{DOMAIN}_hauteur_coupe_tondeuse"),
    "delai_reprise_tonte_apres_arrosage": ("number", f"{DOMAIN}_delai_reprise_tonte_apres_arrosage"),
    "tonte_autorisee": ("binary_sensor", f"{DOMAIN}_tonte_autorisee"),
    "arrosage_recommande": ("binary_sensor", f"{DOMAIN}_arrosage_recommande"),
    "retour_mode_normal": ("button", f"{DOMAIN}_retour_mode_normal"),
    "date_action_today": ("button", f"{DOMAIN}_date_action_today"),
    "hauteur_tonte": ("sensor", f"{DOMAIN}_hauteur_de_tonte_conseillee"),
    "hauteur_gazon_estimee": ("sensor", f"{DOMAIN}_hauteur_gazon_estimee"),
    "phase_active": ("sensor", f"{DOMAIN}_phase_dominante"),
    "sous_phase": ("sensor", f"{DOMAIN}_sous_phase"),
    "objectif_mm": ("sensor", f"{DOMAIN}_objectif_d_arrosage"),
    "objectif_legacy_mm": ("sensor", f"{DOMAIN}_objectif_legacy"),
    "objectif_depletion_mm": ("sensor", f"{DOMAIN}_objectif_depletion"),
    "et0": ("sensor", f"{DOMAIN}_et0"),
    "etc": ("sensor", f"{DOMAIN}_etc"),
    "reserve_actuelle": ("sensor", f"{DOMAIN}_reserve_actuelle"),
    "depletion_ratio": ("sensor", f"{DOMAIN}_depletion_ratio"),
    "etat_hydrique": ("sensor", f"{DOMAIN}_etat_hydrique"),
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
    "dernier_arrosage_total_zones": ("sensor", f"{DOMAIN}_dernier_arrosage_total_zones"),
    "prochain_arrosage": ("sensor", f"{DOMAIN}_prochain_arrosage"),
    "prochaine_tonte": ("sensor", f"{DOMAIN}_prochaine_tonte"),
    "derniere_application": ("sensor", f"{DOMAIN}_derniere_application"),
    "derniere_action_utilisateur": ("sensor", f"{DOMAIN}_derniere_action_utilisateur"),
    "catalogue_produits": ("sensor", f"{DOMAIN}_catalogue_produits"),
    "produit_intervention": ("select", f"{DOMAIN}_produit_d_intervention"),
    "prochaine_intervention": ("sensor", f"{DOMAIN}_prochaine_intervention"),
    "debug_intervention": ("sensor", f"{DOMAIN}_debug_intervention"),
    "score_niveau": ("sensor", f"{DOMAIN}_niveau_de_pertinence"),
    "prochaine_fenetre_optimale": ("sensor", f"{DOMAIN}_prochaine_fenetre_optimale"),
    "prochain_blocage_attendu": ("sensor", f"{DOMAIN}_prochain_blocage_attendu"),
    "arrosage_auto_blocage": ("sensor", f"{DOMAIN}_arrosage_auto_blocage"),
    "signal_intervention": ("binary_sensor", f"{DOMAIN}_signal_intervention"),
    "signal_irrigation": ("binary_sensor", f"{DOMAIN}_signal_irrigation"),
    "arrosage_apres_application_autorise": ("binary_sensor", f"{DOMAIN}_arrosage_apres_application_autorise"),
    "arrosage_automatique": ("switch", f"{DOMAIN}_arrosage_automatique_autorise"),
    "coordination_tondeuse": ("switch", f"{DOMAIN}_coordination_tondeuse"),
    "arroser_maintenant": ("button", f"{DOMAIN}_arroser_maintenant"),
}

ACTIVE_ENTITY_SUFFIXES: set[str] = set(PUBLIC_ENTITY_KEYS)


def normalize_instance_slug(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split()).strip()
    if not text:
        return None
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_text = ascii_text.lower()
    ascii_text = re.sub(r"[^a-z0-9]+", "_", ascii_text)
    ascii_text = re.sub(r"_+", "_", ascii_text).strip("_")
    return ascii_text or None


def resolve_entry_instance_slug(entry: Any) -> str | None:
    data = getattr(entry, "data", None)
    options = getattr(entry, "options", None)
    for source in (options, data):
        if isinstance(source, Mapping):
            slug = normalize_instance_slug(source.get(CONF_INSTANCE_SLUG))
            if slug:
                return slug
    return None


def public_entity_domain(suffix: str) -> str:
    return PUBLIC_ENTITY_KEYS[suffix][0]


def public_entity_id(platform: str, suffix: str, instance_slug: str | None = None) -> str:
    expected_platform, object_id = PUBLIC_ENTITY_KEYS[suffix]
    if expected_platform != platform:
        raise ValueError(f"Suffixe {suffix} attendu pour {expected_platform}, pas {platform}")
    normalized_slug = normalize_instance_slug(instance_slug)
    if not normalized_slug:
        return f"{platform}.{object_id}"
    prefix = f"{DOMAIN}_"
    if object_id.startswith(prefix):
        object_tail = object_id[len(prefix) :]
    else:
        object_tail = object_id
    return f"{platform}.{DOMAIN}_{normalized_slug}_{object_tail}"
