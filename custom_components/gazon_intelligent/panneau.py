"""Page « Gazon » : la commande WebSocket et le panneau de la barre latérale (0.92.0).

Deux commandes servent la page (`frontend/gazon-intelligent-panel.js`) :
    · `gazon_intelligent/reglages/get` — tout ce qu'elle affiche pour une instance : le registre
      des réglages, leurs valeurs, le type de sol, les fiches produits COMPLÈTES, et les entités
      qu'elle lit (identifiants réels, renommages compris) ;
    · `gazon_intelligent/reglages/set` — réservée aux administrateurs : valide, enregistre dans
      les options de l'entrée (seulement ce qui diffère du conseil), puis relance un cycle.

Le panneau apparaît tant qu'une instance chargée a la case « page Gazon » cochée (par défaut).

Les imports de composants Home Assistant (websocket_api, frontend, panel_custom, http) sont faits
au moment d'enregistrer : le reste du module se teste sans Home Assistant.
"""

from __future__ import annotations

import asyncio
import copy
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import voluptuous as vol

from . import ia
from . import notifications
from . import reglages as registre
from . import sources as sources_meteo
from .const import (
    CONF_ALERTES_ACTIVES,
    CONF_CAPTEUR_TONDEUSE_BATTERIE,
    CONF_CAPTEUR_TONDEUSE_EN_CHARGE,
    CONF_CAPTEUR_TONDEUSE_ERREUR,
    CONF_CAPTEUR_TONDEUSE_HAUTEUR_COUPE,
    CONF_CAPTEUR_TONDEUSE_PLUIE,
    CONF_ENTITE_IA,
    CONF_ENTITE_TONDEUSE,
    CONF_ENTITE_VOLET_GARAGE_TONDEUSE,
    CONF_ENTITE_METEO,
    CONF_ENTITE_POMPE,
    CONF_MODE_NOTIFICATIONS,
    CONF_NOTIFICATION_HEURES_CALMES,
    CONF_NOTIFICATION_HEURES_CALMES_DEBUT,
    CONF_NOTIFICATION_HEURES_CALMES_FIN,
    CONF_NOTIFICATION_NIVEAU_MINIMAL,
    CONF_SOURCE_NOTIFICATIONS,
    CONF_NOTIFIER_ACTIVITE_ARROSAGE,
    CONF_NOTIFIER_ACTIVITE_TONDEUSE,
    CONF_NOTIFIER_ARROSAGE_GRAINES,
    CONF_NOTIFIER_CAPTEURS_METEO,
    CONF_NOTIFIER_GARAGE_TONDEUSE,
    CONF_NOTIFIER_SECURITE_ARROSAGE,
    CONF_NOTIFIER_TONDEUSE,
    CONF_NOTIFICATION_CIBLES,
    CONF_PAGE_GAZON,
    CONF_REGLAGES,
    CONF_PILOTAGE_TONDEUSE,
    CONF_TONDEUSE_CRENEAUX_DEPART,
    CONF_TYPE_SOL,
    CONF_ZONE_1,
    CONF_ZONE_2,
    CONF_ZONE_3,
    CONF_ZONE_4,
    CONF_ZONE_5,
    MODES_NOTIFICATIONS,
    NIVEAUX_NOTIFICATIONS,
    SOURCES_NOTIFICATIONS,
    DEFAULT_PAGE_GAZON,
    DEFAULT_MOWER_CONTROL_MODE,
    DEFAULT_MOWER_START_WINDOW_POLICY,
    DEFAULT_TYPE_SOL,
    DOMAIN,
)
from .entity_ids import PUBLIC_ENTITY_KEYS, public_entity_id, resolve_entry_instance_slug
from .shared_state import resolve_effective_config

_LOGGER = logging.getLogger(__name__)

URL_PANNEAU = "gazon"
COMPOSANT = "gazon-intelligent-panel"
URL_FICHIERS = f"/{DOMAIN}_panneau"
DOSSIER_FRONTEND = Path(__file__).parent / "frontend"
FICHIER_PANNEAU = "gazon-intelligent-panel.js"
WS_LIRE = f"{DOMAIN}/reglages/get"
WS_ECRIRE = f"{DOMAIN}/reglages/set"
_CLE_ETAT = f"{DOMAIN}_panneau"

LIAISONS_MATERIEL: tuple[dict[str, Any], ...] = (
    {
        "cle": CONF_ZONE_1, "titre": "Vanne de la zone 1", "groupe": "arrosage",
        "apporte": "Ouvre et ferme la première zone d'arrosage.", "sans_elle": "La zone 1 ne peut pas arroser.",
        "domaine": "switch", "obligatoire": True,
    },
    *tuple({
        "cle": cle, "titre": f"Vanne de la zone {numero}", "groupe": "arrosage",
        "apporte": f"Ouvre et ferme la zone d'arrosage {numero}.",
        "sans_elle": f"La zone {numero} reste inutilisée.", "domaine": "switch", "obligatoire": False,
    } for numero, cle in enumerate((CONF_ZONE_2, CONF_ZONE_3, CONF_ZONE_4, CONF_ZONE_5), start=2)),
    {
        "cle": CONF_ENTITE_TONDEUSE, "titre": "Tondeuse principale", "groupe": "tondeuse",
        "apporte": "Son état permet de coordonner la tonte, l'arrosage et le garage.",
        "sans_elle": "Découverte automatique seulement si Home Assistant ne trouve qu'une tondeuse.",
        "domaine": "lawn_mower", "obligatoire": False,
    },
    {
        "cle": CONF_CAPTEUR_TONDEUSE_ERREUR, "titre": "Erreur de la tondeuse", "groupe": "tondeuse",
        "apporte": "Donne le code ou le texte exact de la panne.", "sans_elle": "Les attributs de la tondeuse sont utilisés.",
        "domaine": "sensor", "obligatoire": False,
    },
    {
        "cle": CONF_CAPTEUR_TONDEUSE_BATTERIE, "titre": "Batterie de la tondeuse", "groupe": "tondeuse",
        "apporte": "Évite un départ automatique avec une batterie insuffisante.", "sans_elle": "Les attributs de la tondeuse sont utilisés.",
        "domaine": "sensor", "obligatoire": False,
    },
    {
        "cle": CONF_CAPTEUR_TONDEUSE_PLUIE, "titre": "Détecteur de pluie de la tondeuse", "groupe": "tondeuse",
        "apporte": "Confirme directement que le robot détecte la pluie.", "sans_elle": "La météo du jardin reste utilisée.",
        "domaine": "binary_sensor", "obligatoire": False,
    },
    {
        "cle": CONF_CAPTEUR_TONDEUSE_EN_CHARGE, "titre": "Tondeuse en charge", "groupe": "tondeuse",
        "apporte": "Renforce la détection de la tondeuse réellement rangée sur sa base.",
        "sans_elle": "La charge est déduite de l'état principal.", "domaine": "binary_sensor", "obligatoire": False,
    },
    {
        "cle": CONF_CAPTEUR_TONDEUSE_HAUTEUR_COUPE, "titre": "Hauteur de coupe de la tondeuse", "groupe": "tondeuse",
        "apporte": "Lit la hauteur réglée sur une tondeuse qui la publie dans Home Assistant.",
        "sans_elle": "La hauteur saisie manuellement dans Installation est utilisée.", "domaine": "number", "obligatoire": False,
    },
)
_LIAISONS_PAR_CLE = {str(liaison["cle"]): liaison for liaison in LIAISONS_MATERIEL}

# Clé que la page utilise → suffixe de l'identifiant unique de l'entité (`{entry_id}_{suffixe}`).
ENTITES_DE_LA_PAGE: dict[str, str] = {
    "assistant": "assistant",
    "arrosage_en_cours": "arrosage_en_cours",
    "prochain_arrosage": "prochain_arrosage",
    "blocage_arrosage": "arrosage_auto_blocage",
    "prochaine_tonte": "prochaine_tonte",
    "tonte_autorisee": "tonte_autorisee",
    "phase": "phase_active",
    "risque": "risque_gazon",
    "reserve": "reserve_actuelle",
    "etat_hydrique": "etat_hydrique",
    "hauteur_tonte": "hauteur_tonte",
    "hauteur_gazon_estimee": "hauteur_gazon_estimee",
    "tonte_etat": "tonte_etat",
    "catalogue_produits": "catalogue_produits",
    "derniere_application": "derniere_application",
    "prochaine_intervention": "prochaine_intervention",
    "dernier_arrosage": "dernier_arrosage_detecte",
    "objectif": "objectif_mm",
    "plan_arrosage": "plan_arrosage",
    "fenetre_optimale": "fenetre_optimale",
    "et0": "et0",
    "eto_horaire": "eto_horaire",
    "etc": "etc",
    "mode": "mode",
    "debit_zone_1": "debit_zone_1",
    "debit_zone_2": "debit_zone_2",
    "debit_zone_3": "debit_zone_3",
    "debit_zone_4": "debit_zone_4",
    "debit_zone_5": "debit_zone_5",
    "hauteur_coupe_tondeuse": "hauteur_coupe_tondeuse",
    "hauteur_min_tondeuse_cm": "hauteur_min_tondeuse_cm",
    "hauteur_max_tondeuse_cm": "hauteur_max_tondeuse_cm",
    "delai_reprise_tonte_apres_arrosage": "delai_reprise_tonte_apres_arrosage",
    "seuil_declaration_tonte": "seuil_declaration_tonte",
    "arrosage_automatique": "arrosage_automatique",
    "rafraichissement_soir": "rafraichissement_soir",
    "coordination_tondeuse": "coordination_tondeuse",
    "declaration_tonte_auto": "declaration_tonte_auto",
}
_ZONES = (CONF_ZONE_1, CONF_ZONE_2, CONF_ZONE_3, CONF_ZONE_4, CONF_ZONE_5)


# ── Ce que la page lit ─────────────────────────────────────────────────────────────────────


def page_voulue(entry: Any) -> bool:
    """La case « page Gazon » de l'entrée (cochée par défaut)."""
    for source in (getattr(entry, "options", None), getattr(entry, "data", None)):
        if isinstance(source, Mapping) and source.get(CONF_PAGE_GAZON) is not None:
            return bool(source[CONF_PAGE_GAZON])
    return DEFAULT_PAGE_GAZON


def _coordinateurs(hass: Any) -> list[Any]:
    domaine = hass.data.get(DOMAIN)
    if not isinstance(domaine, Mapping):
        return []
    return [c for c in domaine.values() if getattr(c, "entry", None) is not None and hasattr(c, "_get_conf")]


def instances_avec_page(hass: Any) -> list[Any]:
    return [c for c in _coordinateurs(hass) if page_voulue(c.entry)]


def coordinateur_demande(hass: Any, entry_id: str | None) -> Any | None:
    """L'instance demandée, ou la première qui affiche la page."""
    if entry_id:
        return next((c for c in _coordinateurs(hass) if c.entry.entry_id == entry_id), None)
    instances = instances_avec_page(hass)
    return instances[0] if instances else None


def _titre(entry: Any) -> str:
    return str(getattr(entry, "title", "") or "Gazon Intelligent")


def _sous_titre(entry: Any) -> str | None:
    """« Gazon Potager » pour « Gazon Intelligent - Gazon Potager » ; rien pour le titre par défaut."""
    titre = _titre(entry)
    if " - " not in titre:
        return None
    return titre.split(" - ", 1)[1].strip() or None


def _reglages_bruts(entry: Any) -> Any:
    options = getattr(entry, "options", None)
    return options.get(CONF_REGLAGES) if isinstance(options, Mapping) else None


def _registre_entites(hass: Any) -> Any | None:
    try:
        from homeassistant.helpers import entity_registry as er

        return er.async_get(hass)
    except Exception:  # noqa: BLE001 - hors Home Assistant (tests), ou registre indisponible
        return None


def entites_de_l_instance(hass: Any, entry: Any) -> dict[str, str]:
    """Identifiant réel de chaque entité lue par la page, renommage compris."""
    registre_entites = _registre_entites(hass)
    slug = resolve_entry_instance_slug(entry)
    entites: dict[str, str] = {}
    for cle_page, suffixe in ENTITES_DE_LA_PAGE.items():
        domaine = PUBLIC_ENTITY_KEYS[suffixe][0]
        entity_id = None
        if registre_entites is not None:
            entity_id = registre_entites.async_get_entity_id(domaine, DOMAIN, f"{entry.entry_id}_{suffixe}")
        entites[cle_page] = entity_id or public_entity_id(domaine, suffixe, instance_slug=slug)
    return entites


def _nom_entite(hass: Any, entity_id: str) -> str | None:
    """Le nom que Home Assistant donne à l'entité, sans le nom de l'appareil devant."""
    registre_entites = _registre_entites(hass)
    entree = registre_entites.async_get(entity_id) if registre_entites is not None else None
    if entree is not None and (entree.name or entree.original_name):
        return str(entree.name or entree.original_name)
    etat = hass.states.get(entity_id)
    nom = etat.attributes.get("friendly_name") if etat is not None else None
    return str(nom) if nom else None


def zones_de_l_instance(hass: Any, coordinateur: Any) -> list[dict[str, Any]]:
    """Les vannes configurées. Leur nom est celui de l'entité : la renommer dans Home Assistant
    renomme la zone sur la page."""
    zones = []
    for numero, cle in enumerate(_ZONES, start=1):
        switch = coordinateur._get_conf(cle)
        if not switch:
            continue
        zones.append({
            "numero": numero,
            "nom": _nom_entite(hass, str(switch)) or f"Zone {numero}",
            "switch": str(switch),
            "etat": None,
        })
    return zones


def liaisons_materiel_de_l_instance(hass: Any, coordinateur: Any) -> list[dict[str, Any]]:
    """Les vannes et signaux de tondeuse configurables depuis l'onglet Entités."""
    resultat = []
    zones = {str(coordinateur._get_conf(cle)) for cle in _ZONES if coordinateur._get_conf(cle)}
    pompe = str(coordinateur._get_conf(CONF_ENTITE_POMPE) or "")
    for definition in LIAISONS_MATERIEL:
        cle = str(definition["cle"])
        entity_id = coordinateur._get_conf(cle) or None
        domaine = str(definition["domaine"])
        candidats = _entites_du_domaine(hass, domaine)
        if cle in _ZONES:
            candidats = [
                candidat for candidat in candidats
                if candidat == entity_id or (candidat != pompe and candidat not in zones)
            ]
        resultat.append({
            **definition,
            "entity_id": str(entity_id) if entity_id else None,
            "nom": (_nom_entite(hass, str(entity_id)) or str(entity_id)) if entity_id else None,
            "choix": [_avec_nom(hass, candidat) for candidat in candidats],
        })
    return resultat


def produits_complets(coordinateur: Any) -> list[dict[str, Any]]:
    """Les fiches ENTIÈRES : `register_product` remplace une fiche, la page doit tout renvoyer."""
    produits = getattr(getattr(coordinateur, "brain", None), "products", None)
    if not isinstance(produits, Mapping):
        return []
    fiches = [copy.deepcopy(dict(p)) for p in produits.values() if isinstance(p, Mapping)]
    return sorted(fiches, key=lambda p: str(p.get("nom") or p.get("id") or "").casefold())


def _choix(coordinateur: Any) -> dict[str, Any]:
    return {
        CONF_TYPE_SOL: coordinateur._get_conf(CONF_TYPE_SOL) or DEFAULT_TYPE_SOL,
        CONF_PILOTAGE_TONDEUSE: coordinateur._get_conf(CONF_PILOTAGE_TONDEUSE) or DEFAULT_MOWER_CONTROL_MODE,
        CONF_TONDEUSE_CRENEAUX_DEPART: coordinateur._get_conf(CONF_TONDEUSE_CRENEAUX_DEPART)
        or DEFAULT_MOWER_START_WINDOW_POLICY,
    }


def _entites_du_domaine(hass: Any, domaine: str) -> list[str]:
    try:
        return sorted(str(e) for e in hass.states.async_entity_ids(domaine))
    except Exception:  # noqa: BLE001 - hors Home Assistant (tests), ou états illisibles
        return []


def _avec_nom(hass: Any, entity_id: str) -> dict[str, str]:
    return {"entity_id": entity_id, "nom": _nom_entite(hass, entity_id) or entity_id}


def notifications_de_l_instance(hass: Any, entry: Any) -> dict[str, Any]:
    """Où partent les alertes, quelle IA répond, et ce qu'on peut choisir (0.93.0).

    `ia_choisie` est le choix des options (vide : automatique) ; `ia`, celle qui répondra.
    """
    services = getattr(hass, "services", None)
    try:
        ia_disponible = bool(services is not None and services.has_service("ai_task", "generate_data"))
    except Exception:  # noqa: BLE001 - la page affiche alors « aucune IA »
        ia_disponible = False
    entite_ia = ia.entite_effective(hass, entry)
    sujets = notifications.sujets_voulus(entry)
    return {
        "cibles": [_avec_nom(hass, cible) for cible in notifications.cibles_configurees(entry)],
        "alertes": notifications.alertes_voulues(entry),
        "mode": notifications.mode_notifications(entry),
        "source": notifications.source_notifications(entry),
        "niveau_minimal": notifications.niveau_minimal(entry),
        "heures_calmes": dict(zip(
            ("active", "debut", "fin"), notifications.heures_calmes(entry), strict=True
        )),
        "categories": {
            "arrosage_graines": notifications.SUJET_GRAINES in sujets,
            "securite_arrosage": notifications.SUJET_VERROU in sujets,
            "capteurs_meteo": notifications.SUJET_MESURES in sujets,
            "tondeuse": notifications.SUJET_TONDEUSE in sujets,
            "activite_arrosage": notifications.SUJET_ACTIVITE_ARROSAGE in sujets,
            "activite_tondeuse": notifications.SUJET_ACTIVITE_TONDEUSE in sujets,
            "garage_tondeuse": notifications.SUJET_GARAGE_TONDEUSE in sujets,
        },
        "ia_choisie": ia.entite_configuree(entry),
        "ia": entite_ia,
        "ia_nom": _avec_nom(hass, entite_ia)["nom"] if entite_ia else None,
        "ia_disponible": ia_disponible,
        "telephones": sorted(
            (_avec_nom(hass, e) for e in _entites_du_domaine(hass, "notify")),
            key=lambda x: x["nom"].casefold(),
        ),
        "ias": sorted(
            (_avec_nom(hass, e) for e in _entites_du_domaine(hass, "ai_task")),
            key=lambda x: x["nom"].casefold(),
        ),
    }


def lire_notifications(hass: Any, envoi: Any) -> tuple[dict[str, Any], str | None]:
    """Les options à écrire pour les alertes et l'IA, ou la raison du refus.

    Seules les clés envoyées changent. Une entité doit exister : un choix fait sur une page restée
    ouverte peut viser un téléphone retiré depuis.
    """
    if not isinstance(envoi, Mapping):
        return {}, "Ce qui a été envoyé n'a pas la bonne forme."
    mises_a_jour: dict[str, Any] = {}
    if "cibles" in envoi:
        cibles = envoi["cibles"]
        if not isinstance(cibles, list) or not all(isinstance(c, str) for c in cibles):
            return {}, "La liste des téléphones n'a pas la bonne forme."
        connus = set(_entites_du_domaine(hass, "notify"))
        propres: list[str] = []
        for cible in cibles:
            if cible not in connus:
                return {}, f"Ce téléphone n'existe plus dans Home Assistant : {cible}."
            if cible not in propres:
                propres.append(cible)
        mises_a_jour[CONF_NOTIFICATION_CIBLES] = propres
    if "alertes" in envoi:
        if not isinstance(envoi["alertes"], bool):
            return {}, "Le choix des alertes n'a pas la bonne forme."
        mises_a_jour[CONF_ALERTES_ACTIVES] = envoi["alertes"]
    if "mode" in envoi:
        mode = envoi["mode"]
        if not isinstance(mode, str) or mode not in MODES_NOTIFICATIONS:
            return {}, "Sélectionner Veille intelligente ou Choix manuel."
        mises_a_jour[CONF_MODE_NOTIFICATIONS] = mode
    if "source" in envoi:
        source = envoi["source"]
        if not isinstance(source, str) or source not in SOURCES_NOTIFICATIONS:
            return {}, "Sélectionner les messages de Gazon Intelligent ou du Conseiller Gazon."
        mises_a_jour[CONF_SOURCE_NOTIFICATIONS] = source
    if "niveau_minimal" in envoi:
        niveau = envoi["niveau_minimal"]
        if not isinstance(niveau, str) or niveau not in NIVEAUX_NOTIFICATIONS:
            return {}, "Sélectionner Tout recevoir, Important ou Urgences seulement."
        mises_a_jour[CONF_NOTIFICATION_NIVEAU_MINIMAL] = niveau
    if "heures_calmes" in envoi:
        calme = envoi["heures_calmes"]
        if not isinstance(calme, Mapping) or set(calme) != {"active", "debut", "fin"}:
            return {}, "Les heures calmes n'ont pas la bonne forme."
        if not isinstance(calme["active"], bool):
            return {}, "L'activation des heures calmes doit être cochée ou décochée."
        if not all(isinstance(calme[cle], int) and not isinstance(calme[cle], bool) for cle in ("debut", "fin")):
            return {}, "Les heures calmes doivent être des minutes entières."
        if not all(0 <= calme[cle] < 24 * 60 for cle in ("debut", "fin")):
            return {}, "Sélectionner des heures calmes comprises dans la journée."
        mises_a_jour.update({
            CONF_NOTIFICATION_HEURES_CALMES: calme["active"],
            CONF_NOTIFICATION_HEURES_CALMES_DEBUT: calme["debut"],
            CONF_NOTIFICATION_HEURES_CALMES_FIN: calme["fin"],
        })
    categories = {
        "arrosage_graines": CONF_NOTIFIER_ARROSAGE_GRAINES,
        "securite_arrosage": CONF_NOTIFIER_SECURITE_ARROSAGE,
        "capteurs_meteo": CONF_NOTIFIER_CAPTEURS_METEO,
        "tondeuse": CONF_NOTIFIER_TONDEUSE,
        "activite_arrosage": CONF_NOTIFIER_ACTIVITE_ARROSAGE,
        "activite_tondeuse": CONF_NOTIFIER_ACTIVITE_TONDEUSE,
        "garage_tondeuse": CONF_NOTIFIER_GARAGE_TONDEUSE,
    }
    if "categories" in envoi:
        choix = envoi["categories"]
        if not isinstance(choix, Mapping):
            return {}, "Les catégories de notification n'ont pas la bonne forme."
        inconnues_categories = set(choix) - set(categories)
        if inconnues_categories:
            return {}, f"Catégorie de notification inconnue : {sorted(inconnues_categories)[0]}."
        if not all(isinstance(valeur, bool) for valeur in choix.values()):
            return {}, "Chaque catégorie de notification doit être cochée ou décochée."
        for cle, valeur in choix.items():
            mises_a_jour[categories[cle]] = valeur
    if "ia" in envoi:
        choix_ia = envoi["ia"] or None
        if choix_ia is not None and (
            not isinstance(choix_ia, str) or choix_ia not in _entites_du_domaine(hass, "ai_task")
        ):
            return {}, f"Cette IA n'existe pas dans Home Assistant : {choix_ia}."
        mises_a_jour[CONF_ENTITE_IA] = choix_ia
    inconnues = set(envoi) - {
        "cibles", "alertes", "mode", "source", "niveau_minimal", "heures_calmes", "categories", "ia"
    }
    if inconnues:
        return {}, f"Réglage d'alerte inconnu : {sorted(inconnues)[0]}."
    return mises_a_jour, None


# ── L'onglet Météo (0.94.0) ────────────────────────────────────────────────────────────────

# Ce qui trahit une position : jamais affiché, même quand un appareil le publie.
_MOTS_DE_POSITION = ("latitude", "longitude", "gps", "position", "location", "coordonnee", "coordinate")
_DOMAINES_DE_MESURE = ("sensor", "binary_sensor")
VOISINES_MAX_PAR_APPAREIL = 40
_ROLES_STATION_METEO = {
    "capteur_temperature", "capteur_humidite", "capteur_vent", "capteur_rayonnement",
    "capteur_pression", "capteur_pluie_cumul", "capteur_pluie_24h", "capteur_pluie_actuelle",
}
_SIGNATURES_STATION_METEO = {
    "capteur_vent", "capteur_rayonnement", "capteur_pluie_cumul", "capteur_pluie_actuelle",
}
_INDICES_PLUIE_DU_JOUR = ("jour", "today", "daily", "24h", "24_h")


def _registre_appareils(hass: Any) -> Any | None:
    try:
        from homeassistant.helpers import device_registry as dr

        return dr.async_get(hass)
    except Exception:  # noqa: BLE001 - hors Home Assistant (tests), ou registre indisponible
        return None


def _entites_de_l_appareil(hass: Any, registre_entites: Any, device_id: str) -> list[Any]:
    try:
        from homeassistant.helpers import entity_registry as er

        return list(er.async_entries_for_device(registre_entites, device_id))
    except Exception:  # noqa: BLE001
        return []


def _entites_par_appareil(registre_entites: Any) -> dict[str, list[Any]]:
    """Indexe une fois le registre pour découvrir les stations sans parcours quadratique."""
    toutes = getattr(registre_entites, "entities", None)
    if not isinstance(toutes, Mapping):
        return {}
    resultat: dict[str, list[Any]] = {}
    for entree in toutes.values():
        device_id = getattr(entree, "device_id", None)
        if device_id:
            resultat.setdefault(str(device_id), []).append(entree)
    return resultat


def _trahit_une_position(entity_id: str) -> bool:
    texte = entity_id.lower()
    return any(mot in texte for mot in _MOTS_DE_POSITION)


def _suggestion_automatique(hass: Any, source: Any, entity_id: str) -> bool:
    """Plus stricte que le choix manuel pour ne jamais conseiller une pluie au mauvais rôle."""
    if _refus_de_l_etat(hass, source, entity_id) is not None:
        return False
    etat = hass.states.get(entity_id) if hass is not None else None
    attributs = getattr(etat, "attributes", None) or {}
    texte = f"{entity_id} {attributs.get('friendly_name') or ''}".casefold().replace("-", "_").replace(" ", "_")
    classe = str(attributs.get("device_class") or "").casefold()
    annonce_pluie = any(indice in texte for indice in ("pluie", "rain", "precipitation"))
    pluie_du_jour = any(indice in texte for indice in _INDICES_PLUIE_DU_JOUR)
    if source.cle == "capteur_pluie_24h":
        return pluie_du_jour and (classe == "precipitation" or annonce_pluie)
    if source.cle == "capteur_pluie_cumul":
        return not pluie_du_jour and (classe == "precipitation" or annonce_pluie)
    if source.cle == "capteur_pluie_actuelle":
        return classe in {"precipitation", "precipitation_intensity"} or annonce_pluie
    return True


def _est_station_meteo_personnelle(hass: Any, entrees: list[Any]) -> bool:
    """Reconnaît une station par ses mesures, sans liste de marques ni de modèles."""
    roles = set()
    for entree in entrees:
        entity_id = str(getattr(entree, "entity_id", ""))
        if not entity_id or getattr(entree, "disabled_by", None) is not None or _trahit_une_position(entity_id):
            continue
        for source in sources_meteo.SOURCES:
            if source.cle in _ROLES_STATION_METEO and _suggestion_automatique(hass, source, entity_id):
                roles.add(source.cle)
    return len(roles) >= 3 and bool(roles & _SIGNATURES_STATION_METEO)


def sources_de_l_instance(hass: Any, coordinateur: Any) -> list[dict[str, Any]]:
    """Chaque entrée météo et jardin : son rôle, ce qu'elle apporte, et l'entité branchée.

    `partagee` : la valeur vient de la configuration commune aux pelouses. `appareil` : l'appareil
    Home Assistant de l'entité, pour regrouper ses autres mesures.
    """
    entry = coordinateur.entry
    partage = getattr(coordinateur, "shared_state", None)
    registre_entites = _registre_entites(hass)
    lignes = []
    for source in sources_meteo.SOURCES:
        entity_id = coordinateur._get_conf(source.cle) or None
        try:
            origine = resolve_effective_config(entry, source.cle, shared_state=partage).get("source")
        except Exception:  # noqa: BLE001 - l'origine n'est qu'une précision d'affichage
            origine = None
        appareil = None
        if entity_id and registre_entites is not None:
            entree = registre_entites.async_get(str(entity_id))
            appareil = getattr(entree, "device_id", None) if entree is not None else None
        lignes.append({
            "cle": source.cle,
            "titre": source.titre,
            "groupe": source.groupe,
            "apporte": source.apporte,
            "sans_elle": source.sans_elle,
            "mesure": source.mesure,
            "numerique": source.numerique,
            "entity_id": str(entity_id) if entity_id else None,
            "nom": (_nom_entite(hass, str(entity_id)) or str(entity_id)) if entity_id else None,
            "partagee": origine == "shared_state",
            "appareil": appareil,
            # Ce qui peut la remplacer (0.95.0) : la page filtre sa liste avec les mêmes règles
            # que `lire_entrees`, qui juge l'envoi.
            "domaine": source.domaine,
            "obligatoire": source.obligatoire,
            "unites": list(source.unites),
            "sans_unite": source.sans_unite,
            "unites_refusees": list(source.unites_refusees),
            "classes_refusees": list(source.classes_refusees),
            "classes": list(source.classes),
            "classes_etat_refusees": list(source.classes_etat_refusees),
            "exige_indice": source.exige_indice,
            "indice_sans_classe": source.indice_sans_classe,
            "noms_refuses": list(source.noms_refuses),
            "indices": list(source.indices),
        })
    return lignes


def _refus_de_l_etat(hass: Any, source: Any, entity_id: str) -> str | None:
    """`sources.refus` sur l'état que Home Assistant connaît de l'entité."""
    etat = hass.states.get(entity_id) if hass is not None else None
    attributs = getattr(etat, "attributes", None) or {}
    return sources_meteo.refus(
        source,
        entity_id=entity_id,
        unite=attributs.get("unit_of_measurement"),
        classe=attributs.get("device_class"),
        classe_etat=attributs.get("state_class"),
        nom=attributs.get("friendly_name"),
        etat=getattr(etat, "state", None),
    )


def _vient_de_l_integration(hass: Any, entity_id: str) -> bool:
    registre_entites = _registre_entites(hass)
    entree = registre_entites.async_get(entity_id) if registre_entites is not None else None
    if entree is not None:
        return getattr(entree, "platform", None) == DOMAIN
    return entity_id.split(".", 1)[-1].startswith(f"{DOMAIN}_")


def lire_entrees(hass: Any, coordinateur: Any, envoi: Any) -> tuple[dict[str, str | None], str | None]:
    """Les entrées à écrire (seulement celles qui changent, `None` : retirée), ou le refus.

    Refusé : une entrée inconnue, l'entité météo retirée, une entité absente de Home Assistant,
    une entité de Gazon Intelligent (l'intégration se lirait elle-même), et tout ce que le moteur
    lirait de travers (`sources.refus` : domaine, unité, point de rosée pour la rosée).
    """
    if not isinstance(envoi, Mapping):
        return {}, "Le choix des entrées n'a pas la bonne forme."
    changements: dict[str, str | None] = {}
    for cle, valeur in envoi.items():
        source = sources_meteo.PAR_CLE.get(str(cle))
        if source is None:
            return {}, f"Cette entrée n'existe pas : {cle}."
        if valeur in (None, ""):
            if source.obligatoire:
                return {}, f"« {source.titre} » est obligatoire : sélectionner une autre entité plutôt que de la retirer."
            choisie = None
        elif not isinstance(valeur, str):
            return {}, "Le choix des entrées n'a pas la bonne forme."
        else:
            etat = hass.states.get(valeur) if hass is not None else None
            if etat is None:
                return {}, f"Cette entité n'existe pas dans Home Assistant : {valeur}."
            if _vient_de_l_integration(hass, valeur):
                return {}, f"« {valeur} » vient de Gazon Intelligent : l'intégration ne peut pas se lire elle-même."
            refus = _refus_de_l_etat(hass, source, valeur)
            if refus:
                return {}, refus
            choisie = valeur
        if choisie != (coordinateur._get_conf(source.cle) or None):
            changements[source.cle] = choisie
    return changements, None


def lire_liaisons_materiel(
    hass: Any, coordinateur: Any, envoi: Any
) -> tuple[dict[str, str | None], str | None]:
    """Valide les vannes et les entités de tondeuse comme les sélecteurs Home Assistant."""
    if not isinstance(envoi, Mapping):
        return {}, "Le choix des entités du matériel n'a pas la bonne forme."
    changements: dict[str, str | None] = {}
    for cle_brute, valeur in envoi.items():
        cle = str(cle_brute)
        definition = _LIAISONS_PAR_CLE.get(cle)
        if definition is None:
            return {}, f"Cette liaison n'existe pas : {cle}."
        if valeur in (None, ""):
            if definition["obligatoire"]:
                return {}, f"« {definition['titre']} » est obligatoire : sélectionner une autre entité."
            choisie = None
        elif not isinstance(valeur, str):
            return {}, "Le choix des entités du matériel n'a pas la bonne forme."
        else:
            domaine = str(definition["domaine"])
            if not valeur.startswith(f"{domaine}.") or hass.states.get(valeur) is None:
                return {}, f"Cette entité {domaine} n'existe pas dans Home Assistant : {valeur}."
            if _vient_de_l_integration(hass, valeur):
                return {}, f"« {valeur} » vient de Gazon Intelligent : l'intégration ne peut pas se lire elle-même."
            choisie = valeur
        if choisie != (coordinateur._get_conf(cle) or None):
            changements[cle] = choisie
    if any(cle in changements for cle in _ZONES):
        futures_zones = {
            cle: changements.get(cle, coordinateur._get_conf(cle) or None)
            for cle in _ZONES
        }
        utilisees = [str(valeur) for valeur in futures_zones.values() if valeur]
        if len(utilisees) != len(set(utilisees)):
            return {}, "Une même vanne ne peut pas être utilisée par plusieurs zones."
        pompe = coordinateur._get_conf(CONF_ENTITE_POMPE) or None
        if pompe and str(pompe) in utilisees:
            return {}, "L'interrupteur de la pompe ne peut pas aussi servir de vanne."
    return changements, None


def appareils_des_sources(hass: Any, lignes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Les appareils branchés et les stations météo personnelles détectées, avec leurs mesures.

    Seuls les capteurs sont gardés (ni boutons, ni entités désactivées), et jamais ce qui trahit
    une position. Les suggestions passent toutes les règles de lecture et un filtre plus strict
    pour distinguer la pluie du jour d'un compteur cumulatif.
    """
    registre_entites = _registre_entites(hass)
    registre_appareils = _registre_appareils(hass)
    if registre_entites is None:
        return []
    libres = [s for s in sources_meteo.SOURCES if not any(
        ligne["cle"] == s.cle and ligne["entity_id"] for ligne in lignes
    )]
    branchees = {ligne["entity_id"]: ligne["cle"] for ligne in lignes if ligne["entity_id"]}
    appareils_branches = list(dict.fromkeys(ligne["appareil"] for ligne in lignes if ligne["appareil"]))
    index = _entites_par_appareil(registre_entites)
    stations_detectees = [
        device_id for device_id, entrees in index.items()
        if device_id not in appareils_branches and _est_station_meteo_personnelle(hass, entrees)
    ]
    appareils: list[dict[str, Any]] = []
    for device_id in [*appareils_branches, *stations_detectees]:
        appareil = registre_appareils.async_get(device_id) if registre_appareils is not None else None
        entites = []
        entrees_appareil = index.get(str(device_id)) or _entites_de_l_appareil(hass, registre_entites, device_id)
        station_personnelle = _est_station_meteo_personnelle(hass, entrees_appareil)
        for entree in entrees_appareil:
            entity_id = str(entree.entity_id)
            if entity_id.split(".", 1)[0] not in _DOMAINES_DE_MESURE:
                continue
            if getattr(entree, "disabled_by", None) is not None or _trahit_une_position(entity_id):
                continue
            # Une idée seulement si l'entité passe aussi les règles du changement (0.95.0) : le nom
            # d'un point de rosée contient « rosee », ce n'est pas une rosée sur l'herbe.
            pourrait = [
                s.cle for s in libres
                if entity_id not in branchees
                and _suggestion_automatique(hass, s, entity_id)
            ]
            entites.append({
                "entity_id": entity_id,
                "nom": _nom_entite(hass, entity_id) or entity_id,
                "branchee": branchees.get(entity_id),
                "pourrait": pourrait,
            })
        if not entites:
            continue
        entites.sort(key=lambda e: (e["branchee"] is None, str(e["nom"]).casefold()))
        appareils.append({
            "id": device_id,
            "nom": (getattr(appareil, "name_by_user", None) or getattr(appareil, "name", None)) if appareil else None,
            "fabricant": getattr(appareil, "manufacturer", None) if appareil else None,
            "modele": getattr(appareil, "model", None) if appareil else None,
            "station_personnelle": station_personnelle,
            "detectee": device_id not in appareils_branches,
            "entites": entites[:VOISINES_MAX_PAR_APPAREIL],
        })
    return appareils


# ── La pompe (0.94.0) ──────────────────────────────────────────────────────────────────────


def pompe_de_l_instance(hass: Any, coordinateur: Any) -> dict[str, Any]:
    """La pompe choisie et les interrupteurs proposés : ceux dont le nom parle d'une pompe
    d'abord. Ni les vannes des zones ni les interrupteurs de l'intégration n'en sont."""
    vannes = {str(coordinateur._get_conf(cle)) for cle in _ZONES if coordinateur._get_conf(cle)}
    candidats = []
    for entity_id in _entites_du_domaine(hass, "switch"):
        if entity_id in vannes or entity_id.startswith(f"switch.{DOMAIN}_"):
            continue
        nom = _nom_entite(hass, entity_id) or entity_id
        texte = f"{entity_id} {nom}".casefold()
        candidats.append({
            "entity_id": entity_id,
            "nom": nom,
            "proposee": any(mot in texte for mot in ("pompe", "pump", "surpresseur")),
        })
    candidats.sort(key=lambda c: (not c["proposee"], str(c["nom"]).casefold()))
    choisie = coordinateur._get_conf(CONF_ENTITE_POMPE) or None
    return {"choisie": str(choisie) if choisie else None, "interrupteurs": candidats}


def lire_pompe(hass: Any, coordinateur: Any, envoi: Any) -> tuple[str | None, str | None]:
    """La pompe à écrire (`None` : aucune), ou la raison du refus."""
    if envoi in (None, ""):
        return None, None
    if not isinstance(envoi, str):
        return None, "Le choix de la pompe n'a pas la bonne forme."
    vannes = {str(coordinateur._get_conf(cle)) for cle in _ZONES if coordinateur._get_conf(cle)}
    if envoi in vannes:
        return None, "Une vanne ne peut pas servir de pompe."
    if envoi not in _entites_du_domaine(hass, "switch"):
        return None, f"Cet interrupteur n'existe pas dans Home Assistant : {envoi}."
    return envoi, None


def garage_tondeuse_de_l_instance(hass: Any, coordinateur: Any) -> dict[str, Any]:
    """Le volet facultatif du garage et les entités ``cover`` disponibles."""
    choisie = coordinateur._get_conf(CONF_ENTITE_VOLET_GARAGE_TONDEUSE) or None
    volets = [_avec_nom(hass, entity_id) for entity_id in _entites_du_domaine(hass, "cover")]
    return {"choisie": str(choisie) if choisie else None, "volets": volets}


def lire_garage_tondeuse(hass: Any, envoi: Any) -> tuple[str | None, str | None]:
    """Le volet à écrire (`None` : aucun), ou la raison du refus."""
    if envoi in (None, ""):
        return None, None
    if not isinstance(envoi, str):
        return None, "Le choix du garage de la tondeuse n'a pas la bonne forme."
    if envoi not in _entites_du_domaine(hass, "cover"):
        return None, f"Ce volet n'existe pas dans Home Assistant : {envoi}."
    return envoi, None


def donnees_de_la_page(hass: Any, coordinateur: Any) -> dict[str, Any]:
    entry = coordinateur.entry
    return {
        "instances": [{"entry_id": c.entry.entry_id, "titre": _titre(c.entry)} for c in instances_avec_page(hass)],
        "entry_id": entry.entry_id,
        "titre": _titre(entry),
        "sous_titre": _sous_titre(entry),
        "registre": registre.exporter(),
        "valeurs": registre.valeurs_effectives(_reglages_bruts(entry)),
        "choix": _choix(coordinateur),
        "produits": produits_complets(coordinateur),
        "entites": entites_de_l_instance(hass, entry),
        "zones": zones_de_l_instance(hass, coordinateur),
        "pompe": coordinateur._get_conf(CONF_ENTITE_POMPE) or None,
        "meteo": coordinateur._get_conf(CONF_ENTITE_METEO) or None,
        "notifications": notifications_de_l_instance(hass, entry),
        "sources": (sources := sources_de_l_instance(hass, coordinateur)),
        "liaisons_materiel": liaisons_materiel_de_l_instance(hass, coordinateur),
        "appareils": appareils_des_sources(hass, sources),
        "pompe_choix": pompe_de_l_instance(hass, coordinateur),
        "garage_tondeuse": garage_tondeuse_de_l_instance(hass, coordinateur),
    }


# ── Ce que la page écrit ───────────────────────────────────────────────────────────────────


async def ecrire_reglages(
    coordinateur: Any,
    valeurs: Any,
    choix: Any,
    alertes: Any = None,
    *,
    hass: Any = None,
    pompe: Any = ...,
    garage_tondeuse: Any = ...,
    entrees: Any = None,
    liaisons_materiel: Any = None,
) -> dict[str, Any]:
    """Valide et enregistre les changements de la page ; rien n'est écrit si une valeur est refusée.

    Les contraintes sont jugées sur l'ensemble ENREGISTRÉ complété des changements : juger les
    seuls changements les comparerait au conseil, alors qu'une autre valeur réglée est en vigueur.
    `alertes` (0.93.0) : les téléphones, les alertes et l'IA, écrits dans les options de l'entrée.
    `pompe` (0.94.0) : l'interrupteur de la pompe, ou `None` pour n'en avoir aucune ; absent
    (`...`), la pompe ne change pas.
    `entrees` (0.95.0) : les entrées météo et jardin à brancher ou retirer. Jamais pendant un
    arrosage : le changement recharge l'intégration.
    `liaisons_materiel` : les vannes et les entrées de la tondeuse, soumises au même verrou.
    """
    if not isinstance(valeurs, Mapping) or not isinstance(choix, Mapping):
        return {"ok": False, "erreurs": {"_": "Ce qui a été envoyé n'a pas la bonne forme."}}
    enregistrees = registre.nettoyer(_reglages_bruts(coordinateur.entry))
    ensemble = {**enregistrees, **dict(valeurs)}
    erreurs = registre.valider(ensemble)
    erreurs.update(registre.valider_choix(dict(choix)))
    options_alertes: dict[str, Any] = {}
    if alertes:
        options_alertes, refus = lire_notifications(hass, alertes)
        if refus:
            erreurs["notifications"] = refus
    if pompe is not ...:
        pompe_choisie, refus = lire_pompe(hass, coordinateur, pompe)
        if refus:
            erreurs["pompe"] = refus
        else:
            options_alertes[CONF_ENTITE_POMPE] = pompe_choisie
    if garage_tondeuse is not ...:
        garage_choisi, refus = lire_garage_tondeuse(hass, garage_tondeuse)
        if refus:
            erreurs["garage_tondeuse"] = refus
        else:
            options_alertes[CONF_ENTITE_VOLET_GARAGE_TONDEUSE] = garage_choisi
    changements_entrees: dict[str, str | None] = {}
    if entrees is not None:
        changements_entrees, refus = lire_entrees(hass, coordinateur, entrees)
        if refus:
            erreurs["entrees"] = refus
    changements_liaisons: dict[str, str | None] = {}
    if liaisons_materiel is not None:
        changements_liaisons, refus = lire_liaisons_materiel(hass, coordinateur, liaisons_materiel)
        if refus:
            erreurs["liaisons_materiel"] = refus
    changements_sources = {**changements_entrees, **changements_liaisons}
    if not erreurs and changements_sources and coordinateur.arrosage_en_cours():
        erreurs["entrees"] = (
            "Un arrosage est en cours : modifier les entrées après sa fin, "
            "car le changement recharge l'intégration."
        )
    if erreurs:
        return {"ok": False, "erreurs": erreurs}
    nouvelles = registre.nettoyer(ensemble)
    resultat: dict[str, Any] = {"ok": True, "valeurs": registre.valeurs_effectives(nouvelles)}
    # Seulement des entrées : rien d'autre à réécrire, ni de cycle à relancer en plus.
    if valeurs or choix or options_alertes or (entrees is None and liaisons_materiel is None):
        mises_a_jour: dict[str, Any] = {CONF_REGLAGES: nouvelles, **options_alertes}
        if CONF_TYPE_SOL in choix:
            mises_a_jour[CONF_TYPE_SOL] = choix[CONF_TYPE_SOL]
        if CONF_PILOTAGE_TONDEUSE in choix:
            mises_a_jour[CONF_PILOTAGE_TONDEUSE] = choix[CONF_PILOTAGE_TONDEUSE]
        if CONF_TONDEUSE_CRENEAUX_DEPART in choix:
            mises_a_jour[CONF_TONDEUSE_CRENEAUX_DEPART] = choix[CONF_TONDEUSE_CRENEAUX_DEPART]
        # Le chemin des autres réglages de l'entrée : options fusionnées, puis un cycle relancé.
        await coordinateur.async_update_config(mises_a_jour)
    if changements_sources:
        resultat["recharge"] = await coordinateur.async_changer_entrees(changements_sources)
    resultat["choix"] = _choix(coordinateur)
    if hass is not None:
        resultat["notifications"] = notifications_de_l_instance(hass, coordinateur.entry)
        resultat["pompe"] = coordinateur._get_conf(CONF_ENTITE_POMPE) or None
        resultat["pompe_choix"] = pompe_de_l_instance(hass, coordinateur)
        resultat["garage_tondeuse"] = garage_tondeuse_de_l_instance(hass, coordinateur)
        if entrees is not None:
            resultat["meteo"] = coordinateur._get_conf(CONF_ENTITE_METEO) or None
            resultat["sources"] = sources_de_l_instance(hass, coordinateur)
            resultat["appareils"] = appareils_des_sources(hass, resultat["sources"])
        if liaisons_materiel is not None:
            resultat["liaisons_materiel"] = liaisons_materiel_de_l_instance(hass, coordinateur)
            resultat["zones"] = zones_de_l_instance(hass, coordinateur)
    return resultat


async def _ws_lire(hass: Any, connection: Any, msg: dict[str, Any]) -> None:
    coordinateur = coordinateur_demande(hass, msg.get("entry_id"))
    if coordinateur is None:
        connection.send_error(msg["id"], "not_found", "Aucune instance de Gazon Intelligent n'affiche la page.")
        return
    connection.send_result(msg["id"], donnees_de_la_page(hass, coordinateur))


async def _ws_ecrire(hass: Any, connection: Any, msg: dict[str, Any]) -> None:
    coordinateur = coordinateur_demande(hass, msg.get("entry_id"))
    if coordinateur is None:
        connection.send_error(msg["id"], "not_found", "Cette instance de Gazon Intelligent est introuvable.")
        return
    try:
        resultat = await ecrire_reglages(
            coordinateur,
            msg.get("valeurs") or {},
            msg.get("choix") or {},
            msg.get("notifications") or None,
            hass=hass,
            pompe=msg["pompe"] if "pompe" in msg else ...,
            garage_tondeuse=msg["garage_tondeuse"] if "garage_tondeuse" in msg else ...,
            entrees=msg.get("entrees"),
            liaisons_materiel=msg.get("liaisons_materiel"),
        )
    except Exception as err:  # noqa: BLE001 - l'erreur est rendue à la page, en clair
        _LOGGER.exception("Réglages de la page Gazon non enregistrés")
        connection.send_error(msg["id"], "unknown_error", str(err) or "Les réglages n'ont pas pu être enregistrés.")
        return
    connection.send_result(msg["id"], resultat)


# ── Enregistrement dans Home Assistant ─────────────────────────────────────────────────────


def _etat(hass: Any) -> dict[str, Any]:
    return hass.data.setdefault(_CLE_ETAT, {})


def async_enregistrer_commandes(hass: Any) -> None:
    """Les deux commandes, une seule fois par démarrage de Home Assistant."""
    etat = _etat(hass)
    if etat.get("commandes"):
        return
    from homeassistant.components import websocket_api

    lire = websocket_api.websocket_command(
        {vol.Required("type"): WS_LIRE, vol.Optional("entry_id"): str}
    )(websocket_api.async_response(_ws_lire))
    ecrire = websocket_api.require_admin(
        websocket_api.websocket_command(
            {
                vol.Required("type"): WS_ECRIRE,
                vol.Required("entry_id"): str,
                vol.Optional("valeurs", default={}): dict,
                vol.Optional("choix", default={}): dict,
                vol.Optional("notifications", default={}): dict,
                # N'importe quoi passe ici : `lire_pompe` refuse en clair ce qui n'est pas un choix.
                vol.Optional("pompe"): object,
                vol.Optional("garage_tondeuse"): object,
                # Idem : `lire_entrees` juge chaque entrée (0.95.0).
                vol.Optional("entrees"): object,
                vol.Optional("liaisons_materiel"): object,
            }
        )(websocket_api.async_response(_ws_ecrire))
    )
    websocket_api.async_register_command(hass, lire)
    websocket_api.async_register_command(hass, ecrire)
    etat["commandes"] = True


async def _version(hass: Any) -> str:
    try:
        from homeassistant.loader import async_get_integration

        return str((await async_get_integration(hass, DOMAIN)).version or "0")
    except Exception:  # noqa: BLE001 - le numéro ne sert qu'à renouveler le cache du navigateur
        return "0"


async def async_mettre_a_jour_panneau(hass: Any) -> None:
    """Affiche la page si une instance chargée la veut, la retire sinon. Sans effet si rien ne change."""
    etat = _etat(hass)
    verrou = etat.setdefault("verrou", asyncio.Lock())
    async with verrou:
        voulu = bool(instances_avec_page(hass))
        if voulu == bool(etat.get("panneau")):
            return
        if not voulu:
            from homeassistant.components import frontend

            frontend.async_remove_panel(hass, URL_PANNEAU)
            etat["panneau"] = False
            return
        if not etat.get("fichiers"):
            from homeassistant.components.http import StaticPathConfig

            await hass.http.async_register_static_paths(
                [StaticPathConfig(URL_FICHIERS, str(DOSSIER_FRONTEND), False)]
            )
            etat["fichiers"] = True
        from homeassistant.components import panel_custom

        # `?v=` : un navigateur ne garde pas l'ancienne page après une mise à jour.
        await panel_custom.async_register_panel(
            hass,
            frontend_url_path=URL_PANNEAU,
            webcomponent_name=COMPOSANT,
            sidebar_title="Gazon",
            sidebar_icon="mdi:grass",
            module_url=f"{URL_FICHIERS}/{FICHIER_PANNEAU}?v={await _version(hass)}",
            embed_iframe=False,
            require_admin=False,
            config={},
        )
        etat["panneau"] = True
