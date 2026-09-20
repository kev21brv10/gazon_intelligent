"""Alertes et notifications (0.93.0).

Ce module ne DÉCIDE rien : il lit ce que le moteur a déjà décidé et le raconte. La décision
d'arrosage ne l'appelle jamais, et le coordinateur isole son appel : une panne ici ne retient
aucun cycle.

Trois alertes, choisies parce qu'elles faussent l'arrosage SANS BRUIT :
    · un cycle de graines toujours pas parti après son heure (20 min par défaut, réglable) alors
      que le moteur veut arroser (vent, interrupteur coupé, fenêtre fermée, lancement raté…),
      puis son rattrapage. Constat du 17/09/2026 : un vent au-dessus de la limite retient les
      cycles sans rien afficher d'autre que « Bloqué », qui s'affiche AUSSI pendant l'attente
      normale entre deux cycles. Seul l'écart entre l'heure prévue et l'heure réelle distingue
      les deux ;
    · le verrou de sécurité (une vanne ne s'est pas fermée) : plus aucun arrosage automatique ne
      part tant qu'il est posé ;
    · des mesures qui manquent depuis une heure (0.94.0) : sans elles, l'intégration se replie
      sur les prévisions, sans le dire ailleurs que dans ses voyants de santé.

Quand c'est le moteur lui-même qui renonce (pluie, sol humide, froid), ce n'est pas une panne :
une simple information, une fois par jour.

La partie pure (`evaluer_alertes`, `resume_du_gazon`) se teste sans Home Assistant ; les envois
importent Home Assistant au moment d'agir, comme `panneau.py`.
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from . import ia
from .const import (
    CONF_ALERTES_ACTIVES,
    CONF_ENTITE_METEO,
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
    DEFAULT_ALERTES_ACTIVES,
    DEFAULT_MODE_NOTIFICATIONS,
    DEFAULT_NOTIFICATION_HEURES_CALMES,
    DEFAULT_NOTIFICATION_HEURES_CALMES_DEBUT,
    DEFAULT_NOTIFICATION_HEURES_CALMES_FIN,
    DEFAULT_NOTIFICATION_NIVEAU_MINIMAL,
    DEFAULT_SOURCE_NOTIFICATIONS,
    DEFAULT_NOTIFICATION_CATEGORIE_ACTIVE,
    DOMAIN,
    MODES_NOTIFICATIONS,
    NIVEAUX_NOTIFICATIONS,
    SOURCES_NOTIFICATIONS,
    block_reason_display_label,
)
from .mower_adapter import _RAIN_ERROR_VALUES  # source unique des codes « pause pluie »
from .sources import valeur_utilisable

_LOGGER = logging.getLogger(__name__)

# Un cycle dû est lancé au tick suivant (2 min). Vingt minutes, c'est dix ticks manqués : ce
# n'est plus un décalage, c'est un cycle qui ne part pas. Réglable (`graines_alerte_retard`).
DELAI_RETARD_GRAINES = timedelta(minutes=20)

# Une mesure absente une heure n'est plus un redémarrage ni un hoquet du réseau. Un appareil dont
# AUCUNE entité n'a bougé depuis trois heures est muet, même si sa dernière valeur reste affichée
# (un appareil à piles peut garder sa dernière valeur un jour entier avant d'être déclaré absent).
DELAI_MESURE_MANQUANTE = timedelta(hours=1)
DELAI_APPAREIL_MUET = timedelta(hours=3)

# Le moteur ne demande pas d'eau : ce n'est pas une panne, on informe seulement.
RAISONS_SANS_BESOIN = frozenset({"no_objective", "not_recommended", "semis_target_reached"})

SUJET_GRAINES = "graines"
SUJET_VERROU = "verrou"
SUJET_MESURES = "mesures"
SUJET_TONDEUSE = "tondeuse"
SUJET_ACTIVITE_ARROSAGE = "activite_arrosage"
SUJET_ACTIVITE_TONDEUSE = "activite_tondeuse"
SUJET_GARAGE_TONDEUSE = "garage_tondeuse"

SUJETS_ACTIVITE = frozenset({
    SUJET_ACTIVITE_ARROSAGE,
    SUJET_ACTIVITE_TONDEUSE,
    SUJET_GARAGE_TONDEUSE,
})

OPTIONS_PAR_SUJET = {
    SUJET_GRAINES: CONF_NOTIFIER_ARROSAGE_GRAINES,
    SUJET_VERROU: CONF_NOTIFIER_SECURITE_ARROSAGE,
    SUJET_MESURES: CONF_NOTIFIER_CAPTEURS_METEO,
    SUJET_TONDEUSE: CONF_NOTIFIER_TONDEUSE,
    SUJET_ACTIVITE_ARROSAGE: CONF_NOTIFIER_ACTIVITE_ARROSAGE,
    SUJET_ACTIVITE_TONDEUSE: CONF_NOTIFIER_ACTIVITE_TONDEUSE,
    SUJET_GARAGE_TONDEUSE: CONF_NOTIFIER_GARAGE_TONDEUSE,
}

_LIBELLES_FENETRE = {
    "maintenant": "maintenant",
    "ce_matin": "ce matin",
    "demain_matin": "demain matin",
    "soir": "ce soir",
    "attendre": "attendre",
    "apres_pluie": "après la pluie",
}


@dataclass(frozen=True)
class Alerte:
    """Un message à envoyer.

    `sujet` : une seule trace Home Assistant par sujet, la suivante remplace la précédente.
    `persistante` : laisser une trace dans les notifications de Home Assistant.
    `resolue` : le problème est réglé, la trace du sujet est retirée ; un message vide n'est
    alors envoyé à personne.
    """

    sujet: str
    titre: str
    message: str
    persistante: bool = True
    resolue: bool = False
    # Faux : seule la trace Home Assistant est mise à jour, rien ne part aux téléphones.
    pousser: bool = True
    # Importance déterminée par l'intégration, utilisée par le niveau minimal et les heures calmes.
    niveau: str = "action"


@dataclass(frozen=True)
class Mesure:
    """Une entrée qui mesure, lue au moment du contrôle.

    `en_panne` : aucune valeur utilisable, ou appareil muet. `depuis` : le début connu de la panne
    (dernier changement de l'entité, ou dernière nouvelle de son appareil).
    """

    cle: str
    dans_une_phrase: str
    nom: str
    en_panne: bool
    depuis: datetime | None = None


# ── Lecture tolérante ──────────────────────────────────────────────────────────────────────


def _nombre(valeur: Any) -> float | None:
    if isinstance(valeur, bool):
        return None
    try:
        nombre = float(valeur)
    except (TypeError, ValueError):
        return None
    return nombre if nombre == nombre else None  # NaN écarté


def _entier(valeur: Any, defaut: int = 0) -> int:
    nombre = _nombre(valeur)
    return int(nombre) if nombre is not None else defaut


def _hhmm(minute: Any) -> str | None:
    nombre = _nombre(minute)
    if nombre is None:
        return None
    total = int(nombre)
    return f"{total // 60:02d}:{total % 60:02d}"


def _heure(moment: Any) -> str | None:
    return moment.strftime("%H:%M") if isinstance(moment, datetime) else None


def _dans_le_fuseau(moment: Any, reference: datetime) -> datetime | None:
    """`moment` ramené au fuseau de `reference` (l'heure locale de la maison)."""
    if not isinstance(moment, datetime):
        return None
    if moment.tzinfo is None or reference.tzinfo is None:
        return moment
    return moment.astimezone(reference.tzinfo)


def _decimal(valeur: float) -> str:
    """« 17 » ou « 17,5 » : l'écriture française, sans zéro inutile."""
    arrondi = round(valeur, 1)
    if arrondi == int(arrondi):
        return str(int(arrondi))
    return f"{arrondi:.1f}".replace(".", ",")


def _heure_iso(valeur: Any, reference: datetime) -> str | None:
    """« 12:58 » pour un instant sérialisé (ISO, UTC) lu à l'heure de la maison."""
    if isinstance(valeur, datetime):
        return _heure(_dans_le_fuseau(valeur, reference))
    texte = str(valeur or "").strip()
    if not texte:
        return None
    if texte.endswith("Z"):
        texte = texte[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(texte)
    except ValueError:
        return None
    return _heure(_dans_le_fuseau(moment, reference))


# ── Le cycle de graines ────────────────────────────────────────────────────────────────────


def pourquoi_le_cycle_attend(
    *,
    raison: str | None,
    fenetre: str | None,
    vent_kmh: float | None,
    vent_max_kmh: float | None,
    fin_fenetre_minute: int | None,
    prevu_minute: int | None,
    maintenant_minute: int,
    echec_lancement: str | None = None,
) -> tuple[str, str]:
    """(pourquoi, que faire) pour un cycle de graines dû qui n'est pas parti.

    L'ordre compte : une fenêtre fermée est définitive pour la journée, le vent ne l'est pas.
    Le vent n'est nommé que si la mesure du jardin dépasse vraiment la limite réglée : une
    fausse piste ferait chercher au mauvais endroit.
    """
    code = str(raison or "").strip()
    fin = _hhmm(fin_fenetre_minute)
    if fin_fenetre_minute is not None and maintenant_minute >= int(fin_fenetre_minute):
        if prevu_minute is not None and int(prevu_minute) >= int(fin_fenetre_minute):
            pourquoi = f"Il tombait après la fermeture de la fenêtre des graines ({fin})."
        else:
            pourquoi = f"La fenêtre des graines a fermé à {fin} avant qu'il puisse partir."
        return pourquoi, "Il ne partira plus aujourd'hui : un arrosage à la main reste possible."
    if (
        vent_kmh is not None
        and vent_max_kmh is not None
        and vent_kmh >= vent_max_kmh
        and code in {"", "target_date_future", "window_unavailable", "outside_window", "semis_cycle_pending"}
    ):
        suite = f", jusqu'à {fin}" if fin else ""
        return (
            f"Le vent souffle à {_decimal(vent_kmh)} km/h, au-dessus de la limite de "
            f"{_decimal(vent_max_kmh)} km/h : l'eau serait emportée.",
            f"Rien à faire : il partira dès que le vent retombera sous la limite{suite}.",
        )
    if code == "auto_irrigation_disabled":
        return (
            "L'arrosage automatique est coupé.",
            "Réactive « Arrosage automatique autorisé » pour que les cycles reprennent.",
        )
    if code == "safety_lock":
        return (
            "Le verrou de sécurité de l'arrosage est posé : une vanne ne s'est pas fermée "
            "normalement lors d'un arrosage.",
            "Vérifie les vannes et la pompe avant tout.",
        )
    if code == "startup_guard":
        return (
            "Home Assistant a redémarré et attend des mesures valides.",
            "Rien à faire si cela ne dure pas ; sinon, vérifie la station météo.",
        )
    if code == "watering_in_progress":
        return "Un autre arrosage occupe les vannes.", "Rien à faire : le cycle suivra."
    if code in {"outside_window", "outside_evening_window"}:
        return "Le cycle attend l'ouverture de la fenêtre des graines.", "Rien à faire."
    if code == "irrigation_blocked":
        return (
            "L'arrosage est retenu par un blocage (pluie, tondeuse, produit…).",
            "Le détail est sur la page « Gazon », carte « Blocage arrosage auto ».",
        )
    if code in {"auto_not_allowed", "execution_not_allowed"}:
        return (
            "La décision n'autorise pas l'arrosage automatique en ce moment.",
            "Le conseil du jour est sur la page « Gazon ».",
        )
    if code == "window_unavailable":
        return (
            "La décision attend de meilleures conditions (fenêtre « attendre »).",
            "Le conseil du jour est sur la page « Gazon ».",
        )
    if code == "target_date_future":
        mesure = f" Vent au jardin : {_decimal(vent_kmh)} km/h." if vent_kmh is not None else ""
        libelle = _LIBELLES_FENETRE.get(str(fenetre or ""), str(fenetre or "inconnue"))
        return (
            f"La décision a repoussé le cycle (fenêtre « {libelle} »).{mesure}",
            "Il partira quand la décision repassera à « maintenant ».",
        )
    if code in {"ready", "post_application_ready", "no_plan_available"}:
        detail = f" : {echec_lancement}" if echec_lancement else "."
        return (
            f"Le cycle devait partir mais ne s'est pas lancé{detail}",
            "Vérifie les vannes et le journal de Home Assistant.",
        )
    if not code:
        return (
            "Aucune évaluation récente du lancement.",
            "Vérifie que l'intégration tourne (page « Gazon »).",
        )
    return (
        f"Le cycle n'est pas parti (motif technique « {code} »).",
        "Le détail est sur la page « Gazon », carte « Blocage arrosage auto ».",
    )


def _identifiant_activite(source: Mapping[str, Any] | None, *cles: str) -> str | None:
    if not isinstance(source, Mapping):
        return None
    for cle in cles:
        valeur = source.get(cle)
        if valeur not in (None, ""):
            return str(valeur)
    return None


def _details_arrosage(source: Mapping[str, Any], *, fin: bool = False) -> str:
    morceaux: list[str] = []
    mm = _nombre(source.get("executed_mm" if fin else "target_mm"))
    if mm is not None:
        morceaux.append(f"{_decimal(mm)} mm {'appliqués' if fin else 'prévus'}")
    zones = _entier(source.get("zones_done" if fin else "zone_count"))
    if zones > 0:
        morceaux.append(f"{zones} zone{'s' if zones > 1 else ''}")
    heure = _heure_iso(source.get("ended_at" if fin else "started_at"), datetime.now().astimezone())
    if heure:
        morceaux.append(f"à {heure}")
    return ", ".join(morceaux)


def _phase_tondeuse(source: Mapping[str, Any] | None) -> str | None:
    if not isinstance(source, Mapping):
        return None
    operation = str(source.get("operation") or "").strip().lower()
    if source.get("docked") is True or operation in {"docked", "charging", "idle", "parked", "home"}:
        return "station"
    if source.get("returning") is True or operation in {"returning", "going_home", "homing", "retour_station"}:
        return "retour"
    if source.get("mowing") is True or operation in {
        "mowing", "cutting", "edgecut", "in_operation", "working", "starting", "zoning", "tonte_en_cours",
    }:
        return "tonte"
    return None


def _evaluer_activites(
    etat: dict[str, Any],
    *,
    sujets_actifs: set[str],
    arrosage: Mapping[str, Any] | None,
    tondeuse: Mapping[str, Any] | None,
    garage: Mapping[str, Any] | None,
) -> list[Alerte]:
    """Transforme des changements d'état confirmés en messages dédupliqués et persistants."""
    suivi = etat.get("activites")
    if not isinstance(suivi, dict):
        suivi = {}
        etat["activites"] = suivi
    alertes: list[Alerte] = []

    actif_id = _identifiant_activite(arrosage, "active_id")
    termine_id = _identifiant_activite(arrosage, "completed_id")
    if not suivi.get("arrosage_initialise"):
        suivi.update({
            "arrosage_initialise": True,
            "arrosage_actif": actif_id,
            "arrosage_termine": termine_id,
        })
    else:
        precedent_actif = suivi.get("arrosage_actif")
        precedent_termine = suivi.get("arrosage_termine")
        if (
            SUJET_ACTIVITE_ARROSAGE in sujets_actifs
            and actif_id
            and actif_id != precedent_actif
            and isinstance(arrosage, Mapping)
        ):
            details = _details_arrosage(arrosage)
            alertes.append(Alerte(
                sujet=SUJET_ACTIVITE_ARROSAGE,
                titre="💧 Arrosage démarré",
                message="Le cycle d'arrosage vient de démarrer" + (f" : {details}." if details else "."),
                persistante=False,
                niveau="information",
            ))
        if (
            SUJET_ACTIVITE_ARROSAGE in sujets_actifs
            and termine_id
            and termine_id != precedent_termine
            and isinstance(arrosage, Mapping)
        ):
            statut = str(arrosage.get("completion_status") or "completed")
            succes = statut == "completed"
            details = _details_arrosage(arrosage, fin=True)
            alertes.append(Alerte(
                sujet=SUJET_ACTIVITE_ARROSAGE,
                titre="💧 Arrosage terminé" if succes else "⚠️ Arrosage interrompu",
                message=(
                    "Le cycle d'arrosage est terminé" if succes
                    else "Le cycle d'arrosage ne s'est pas terminé normalement"
                ) + (f" : {details}." if details else "."),
                persistante=not succes,
                niveau="information" if succes else "action",
            ))
        suivi["arrosage_actif"] = actif_id
        suivi["arrosage_termine"] = termine_id

    phase = _phase_tondeuse(tondeuse)
    tondeuse_error = str(tondeuse.get("error") or "").strip() if isinstance(tondeuse, Mapping) else ""
    if not suivi.get("tondeuse_initialisee"):
        suivi.update({
            "tondeuse_initialisee": True,
            "tondeuse_phase": phase,
            "tondeuse_error": tondeuse_error or None,
        })
    else:
        precedente = suivi.get("tondeuse_phase")
        erreur_precedente = str(suivi.get("tondeuse_error") or "")
        if SUJET_ACTIVITE_TONDEUSE in sujets_actifs and tondeuse_error and tondeuse_error != erreur_precedente:
            alertes.append(Alerte(
                sujet=SUJET_ACTIVITE_TONDEUSE,
                titre="⚠️ Tondeuse : commande impossible",
                message=f"Le contrôleur de la tondeuse signale : {tondeuse_error}.",
                niveau="action",
            ))
        elif SUJET_ACTIVITE_TONDEUSE in sujets_actifs and not tondeuse_error and erreur_precedente:
            alertes.append(Alerte(
                sujet=SUJET_ACTIVITE_TONDEUSE,
                titre="",
                message="",
                resolue=True,
            ))
        elif SUJET_ACTIVITE_TONDEUSE in sujets_actifs and phase and phase != precedente:
            titre, message = {
                "tonte": ("🤖 Tonte démarrée", "La tondeuse a démarré sa tonte."),
                "retour": ("🤖 Retour demandé", "La tondeuse retourne à sa station."),
                "station": ("🤖 Tondeuse rentrée", "La tondeuse est revenue à sa station."),
            }[phase]
            alertes.append(Alerte(
                sujet=SUJET_ACTIVITE_TONDEUSE,
                titre=titre,
                message=message,
                persistante=False,
                niveau="information",
            ))
        suivi["tondeuse_phase"] = phase
        suivi["tondeuse_error"] = tondeuse_error or None

    garage_data = garage if isinstance(garage, Mapping) else {}
    garage_configure = garage_data.get("configured") is True
    garage_state = str(garage_data.get("state") or "").lower() if garage_configure else None
    garage_state = garage_state if garage_state in {"open", "closed"} else None
    garage_error = str(garage_data.get("error") or "").strip() if garage_configure else ""
    if not suivi.get("garage_initialise"):
        suivi.update({
            "garage_initialise": True,
            "garage_state": garage_state,
            "garage_error": garage_error or None,
        })
    else:
        precedente = suivi.get("garage_state")
        erreur_precedente = str(suivi.get("garage_error") or "")
        if SUJET_GARAGE_TONDEUSE in sujets_actifs and garage_error and garage_error != erreur_precedente:
            alertes.append(Alerte(
                sujet=SUJET_GARAGE_TONDEUSE,
                titre="⚠️ Garage de la tondeuse : commande impossible",
                message=f"Le garage de la tondeuse signale : {garage_error}.",
                niveau="action",
            ))
        elif SUJET_GARAGE_TONDEUSE in sujets_actifs and not garage_error and erreur_precedente:
            alertes.append(Alerte(
                sujet=SUJET_GARAGE_TONDEUSE,
                titre="",
                message="",
                resolue=True,
            ))
        elif SUJET_GARAGE_TONDEUSE in sujets_actifs and garage_state and garage_state != precedente:
            ouvert = garage_state == "open"
            alertes.append(Alerte(
                sujet=SUJET_GARAGE_TONDEUSE,
                titre="🏠 Garage de la tondeuse",
                message=f"Le garage de la tondeuse est maintenant {'ouvert' if ouvert else 'fermé'}.",
                persistante=False,
                niveau="information",
            ))
        suivi["garage_state"] = garage_state
        suivi["garage_error"] = garage_error or None
    return alertes


def evaluer_alertes(
    memoire: Any,
    *,
    maintenant: datetime,
    progression: Mapping[str, Any] | None,
    en_cours: bool,
    raison: str | None,
    fenetre: str | None,
    vent_kmh: float | None,
    vent_max_kmh: float | None,
    fin_fenetre_minute: int | None,
    motif_decision: str | None,
    echec_lancement: str | None,
    verrou: bool,
    erreur_verrou: str | None = None,
    zone_verrou: str | None = None,
    delai_graines: timedelta = DELAI_RETARD_GRAINES,
    mesures: Sequence[Mesure] = (),
    erreur_tondeuse: str | None = None,
    libelle_erreur_tondeuse: str | None = None,
    activite_arrosage: Mapping[str, Any] | None = None,
    activite_tondeuse: Mapping[str, Any] | None = None,
    activite_garage: Mapping[str, Any] | None = None,
    sujets_actifs: Collection[str] | None = None,
) -> tuple[list[Alerte], dict[str, Any]]:
    """Les alertes à envoyer maintenant, et la mémoire à garder pour ne rien envoyer deux fois.

    La mémoire est PERSISTÉE : un redémarrage (fréquent ici) ne doit ni renvoyer une alerte déjà
    reçue, ni oublier un cycle en retard dont on attend le rattrapage.
    """
    etat: dict[str, Any] = copy.deepcopy(dict(memoire)) if isinstance(memoire, Mapping) else {}
    alertes: list[Alerte] = []
    actifs = set(OPTIONS_PAR_SUJET) if sujets_actifs is None else set(sujets_actifs)
    jour = maintenant.date().isoformat()
    if etat.get("jour") != jour:
        # Nouvelle journée : un retard d'hier resté sans rattrapage ne veut plus rien dire, sa
        # trace est retirée plutôt que laissée à mentir.
        anciens = etat.get("graines")
        if SUJET_GRAINES in actifs and isinstance(anciens, dict) and any(
            isinstance(suivi, dict) and not suivi.get("rattrape") for suivi in anciens.values()
        ):
            alertes.append(Alerte(sujet=SUJET_GRAINES, titre="", message="", resolue=True))
        etat["jour"] = jour
        etat["graines"] = {}
        etat["graines_suspendues"] = False
    suivis = etat.get("graines")
    if not isinstance(suivis, dict):
        suivis = {}
        etat["graines"] = suivis

    # 1. Verrou de sécurité : une fois quand il se pose ; sa levée retire la trace.
    if SUJET_VERROU not in actifs:
        if etat.pop("verrou", False):
            alertes.append(Alerte(sujet=SUJET_VERROU, titre="", message="", resolue=True))
    elif verrou and not etat.get("verrou"):
        etat["verrou"] = True
        zone = f" ({zone_verrou})" if zone_verrou else ""
        erreur = f" Erreur : {erreur_verrou}." if erreur_verrou else ""
        alertes.append(
            Alerte(
                sujet=SUJET_VERROU,
                titre="⚠️ Arrosage automatique verrouillé",
                message=(
                    f"Une vanne ne s'est pas fermée normalement{zone}. Plus aucun arrosage "
                    f"automatique ne partira tant que le verrou est posé.{erreur} Vérifie les "
                    "vannes et la pompe, puis utilise « Lever le verrou de sécurité ». Cette "
                    "action rétablit l'automatisme sans effacer le mode Semis ou Sursemis."
                ),
                niveau="critique",
            )
        )
    elif not verrou and etat.get("verrou"):
        etat["verrou"] = False
        alertes.append(Alerte(sujet=SUJET_VERROU, titre="", message="", resolue=True))

    # 2. Erreur de tondeuse : une alerte par code, puis retrait de la trace au retour normal.
    erreur_robot = str(erreur_tondeuse or "").strip()
    # ⚠️ UNE PAUSE PLUIE N'EST PAS UNE PANNE (0.96.0) : la Landroid publie `rain_delay` sur son
    # capteur d'ERREUR. Sans ce filtre, chaque averse envoyait « Tondeuse : erreur détectée ».
    if erreur_robot.lower() in _RAIN_ERROR_VALUES:
        erreur_robot = ""
    precedente = str(etat.get("tondeuse") or "").strip()
    if SUJET_TONDEUSE not in actifs:
        if etat.pop("tondeuse", None):
            alertes.append(Alerte(sujet=SUJET_TONDEUSE, titre="", message="", resolue=True))
    elif erreur_robot and erreur_robot != precedente:
        etat["tondeuse"] = erreur_robot
        libelle_robot = str(libelle_erreur_tondeuse or erreur_robot).strip().replace("_", " ")
        alertes.append(Alerte(
            sujet=SUJET_TONDEUSE,
            titre="Tondeuse : erreur détectée",
            message=(
                f"La tondeuse signale : {libelle_robot}. Vérifie le robot et son application avant "
                "de relancer une tonte."
            ),
        ))
    elif not erreur_robot and precedente:
        etat.pop("tondeuse", None)
        alertes.append(Alerte(sujet=SUJET_TONDEUSE, titre="", message="", resolue=True))

    # 3. Mesures manquantes : une alerte par épisode, la trace suit la liste, le retour se dit.
    if SUJET_MESURES in actifs:
        alertes.extend(_alertes_mesures(etat, mesures, maintenant))
    elif etat.pop("mesures", None):
        alertes.append(Alerte(sujet=SUJET_MESURES, titre="", message="", resolue=True))

    alertes.extend(_evaluer_activites(
        etat,
        sujets_actifs=actifs,
        arrosage=activite_arrosage,
        tondeuse=activite_tondeuse,
        garage=activite_garage,
    ))

    # Une catégorie désactivée oublie ses retards : si elle est réactivée pendant un problème,
    # le problème sera alors signalé au prochain contrôle au lieu d'être considéré comme déjà vu.
    if SUJET_GRAINES not in actifs:
        if any(isinstance(s, dict) and not s.get("rattrape") for s in suivis.values()):
            alertes.append(Alerte(sujet=SUJET_GRAINES, titre="", message="", resolue=True))
        etat["graines"] = {}
        etat["graines_suspendues"] = False
        return alertes, etat

    if not isinstance(progression, Mapping):
        return alertes, etat

    faits = _entier(progression.get("cycles_completed_today"))
    cible = _entier(progression.get("daily_cycles_target"), defaut=faits)
    restants = _entier(progression.get("cycles_remaining_today"), defaut=max(0, cible - faits))

    # 3. Rattrapages : un cycle signalé en retard a fini par avoir lieu.
    fin_dernier = _heure(_dans_le_fuseau(progression.get("last_cycle_at"), maintenant))
    for rang, suivi in sorted(suivis.items()):
        if not isinstance(suivi, dict) or suivi.get("rattrape"):
            continue
        if faits <= _entier(rang, defaut=10**6):
            continue
        suivi["rattrape"] = True
        fin_texte = f" (terminé à {fin_dernier})" if fin_dernier else ""
        alertes.append(
            Alerte(
                sujet=SUJET_GRAINES,
                titre="🌱 Graines : cycle rattrapé",
                message=(
                    f"Le cycle prévu à {suivi.get('prevu') or '?'} a bien eu lieu{fin_texte}. "
                    f"Cycles faits aujourd'hui : {faits} sur {cible}."
                ),
                persistante=False,
                resolue=True,
                niveau="information",
            )
        )

    # 4. Retard : le cycle est dû depuis plus longtemps que le délai réglé et rien ne coule.
    prevu = _dans_le_fuseau(progression.get("next_due_at"), maintenant)
    if (
        str(progression.get("state") or "") != "ready"
        or restants <= 0
        or en_cours
        or prevu is None
        or maintenant < prevu + delai_graines
    ):
        return alertes, etat
    heure_prevue = _heure(prevu) or "?"
    code = str(raison or "").strip()
    if code in RAISONS_SANS_BESOIN:
        # Le moteur renonce lui-même (pluie, sol humide, froid) : une information par jour.
        if not etat.get("graines_suspendues"):
            etat["graines_suspendues"] = True
            libelle = block_reason_display_label(motif_decision)
            motif = f" ({libelle.lower()})" if libelle else ""
            alertes.append(
                Alerte(
                    sujet=SUJET_GRAINES,
                    titre="🌧️ Graines : cycles suspendus",
                    message=(
                        f"Le moteur a suspendu le cycle de {heure_prevue}{motif} : le sol n'en a "
                        f"pas besoin pour l'instant. Rien à faire. Cycles faits aujourd'hui : "
                        f"{faits} sur {cible}."
                    ),
                    persistante=False,
                    niveau="information",
                )
            )
        return alertes, etat
    rang = str(faits)
    if rang in suivis:
        return alertes, etat
    suivis[rang] = {"prevu": heure_prevue, "rattrape": False}
    pourquoi, que_faire = pourquoi_le_cycle_attend(
        raison=code or None,
        fenetre=fenetre,
        vent_kmh=vent_kmh,
        vent_max_kmh=vent_max_kmh,
        fin_fenetre_minute=fin_fenetre_minute,
        prevu_minute=prevu.hour * 60 + prevu.minute,
        maintenant_minute=maintenant.hour * 60 + maintenant.minute,
        echec_lancement=echec_lancement,
    )
    alertes.append(
        Alerte(
            sujet=SUJET_GRAINES,
            titre=f"🌱 Graines : le cycle de {heure_prevue} n'est pas parti",
            message=f"{pourquoi} {que_faire} Cycles faits aujourd'hui : {faits} sur {cible}.",
        )
    )
    return alertes, etat


def _alertes_mesures(etat: dict[str, Any], mesures: Sequence[Mesure], maintenant: datetime) -> list[Alerte]:
    """Les mesures en panne depuis au moins `DELAI_MESURE_MANQUANTE`, dites une fois par épisode."""
    suivi = etat.get("mesures")
    if not isinstance(suivi, dict):
        suivi = {}
    manquantes: list[Mesure] = []
    for mesure in mesures:
        if not mesure.en_panne or mesure.depuis is None:
            continue
        depuis = _dans_le_fuseau(mesure.depuis, maintenant) or mesure.depuis
        if maintenant - depuis >= DELAI_MESURE_MANQUANTE:
            manquantes.append(mesure)
    signalees = [str(c) for c in suivi.get("cles") or []]
    cles = sorted(m.cle for m in manquantes)
    if not manquantes:
        if not suivi.get("signalee"):
            etat.pop("mesures", None)
            return []
        etat.pop("mesures", None)
        return [Alerte(
            sujet=SUJET_MESURES,
            titre="📡 Météo : mesures revenues",
            message=f"Toutes les mesures sont revenues à {_heure(maintenant)}.",
            persistante=False,
            resolue=True,
            niveau="information",
        )]
    if suivi.get("signalee") and cles == sorted(signalees):
        return []
    etat["mesures"] = {"signalee": True, "cles": cles}
    return [Alerte(
        sujet=SUJET_MESURES,
        titre="📡 Météo : des mesures manquent",
        message=_message_mesures(manquantes, maintenant),
        # Une alerte déjà envoyée dont la liste change : la trace suit, le téléphone ne resonne pas.
        pousser=not suivi.get("signalee"),
    )]


def _message_mesures(manquantes: Sequence[Mesure], maintenant: datetime) -> str:
    morceaux = []
    for mesure in sorted(manquantes, key=lambda m: _dans_le_fuseau(m.depuis, maintenant) or maintenant):
        depuis = _heure(_dans_le_fuseau(mesure.depuis, maintenant))
        detail = ", ".join(x for x in (mesure.nom, f"depuis {depuis}" if depuis else "") if x)
        morceaux.append(f"{mesure.dans_une_phrase} ({detail})" if detail else mesure.dans_une_phrase)
    liste = " ; ".join(morceaux)
    if all(m.cle == CONF_ENTITE_METEO for m in manquantes):
        suite = (
            "Sans elle, la pluie annoncée et la température du jour ne sont plus connues. "
            "Vérifie l'intégration météo."
        )
    elif any(m.cle == CONF_ENTITE_METEO for m in manquantes):
        suite = (
            "Les mesures manquantes n'ont même plus de prévision pour les remplacer. "
            "Vérifie ces appareils et l'intégration météo."
        )
    else:
        suite = (
            "En attendant, l'intégration se sert des prévisions de l'entité météo, moins justes "
            "pour ton jardin. Vérifie ces appareils (piles, réseau)."
        )
    return f"Gazon Intelligent ne reçoit plus : {liste}. {suite}"


def mesure_d_une_entite(
    *,
    cle: str,
    dans_une_phrase: str,
    nom: str,
    etat: Any,
    dernier_changement: datetime | None,
    numerique: bool,
    derniere_nouvelle_appareil: datetime | None,
    maintenant: datetime,
) -> Mesure:
    """La lecture d'une entrée : sans valeur utilisable, ou appareil muet depuis trois heures.

    `derniere_nouvelle_appareil` : la mise à jour la plus récente parmi les entités de l'appareil
    (`None` quand l'entrée n'a pas d'appareil connu, ou un seul : on ne juge alors que la valeur).
    """
    if not valeur_utilisable(etat, numerique=numerique):
        return Mesure(cle, dans_une_phrase, nom, True, dernier_changement)
    if derniere_nouvelle_appareil is not None:
        derniere = _dans_le_fuseau(derniere_nouvelle_appareil, maintenant) or derniere_nouvelle_appareil
        if maintenant - derniere >= DELAI_APPAREIL_MUET:
            return Mesure(cle, dans_une_phrase, nom, True, derniere_nouvelle_appareil)
    return Mesure(cle, dans_une_phrase, nom, False, None)


# ── Résumé lisible ─────────────────────────────────────────────────────────────────────────


def _date_courte(valeur: Any) -> str | None:
    if isinstance(valeur, datetime):
        return valeur.strftime("%d/%m")
    if isinstance(valeur, date):
        return valeur.strftime("%d/%m")
    texte = str(valeur or "").strip()
    if len(texte) >= 10 and texte[4] == "-" and texte[7] == "-":
        return f"{texte[8:10]}/{texte[5:7]}"
    return texte or None


def resume_du_gazon(
    snapshot: Mapping[str, Any],
    *,
    maintenant: datetime,
    arrosage_auto: bool | None = None,
    blocage: str | None = None,
) -> list[str]:
    """L'état du gazon en quelques lignes, pour un téléphone ou pour l'IA.

    Uniquement ce que l'intégration publie déjà : aucune coordonnée, aucun nom de lieu.
    """
    lignes: list[str] = []
    phase = str(snapshot.get("phase_dominante") or snapshot.get("phase_active") or "").strip()
    sous_phase = str(snapshot.get("sous_phase") or "").strip()
    if phase:
        texte = f"Phase : {phase}"
        if sous_phase and sous_phase != phase:
            age = _nombre(snapshot.get("sous_phase_age_days"))
            texte += f" ({sous_phase}" + (f", jour {int(age)}" if age is not None else "") + ")"
        fin = _date_courte(snapshot.get("date_fin"))
        if fin and phase != "Normal":
            texte += f", jusqu'au {fin}"
        lignes.append(texte + ".")

    cible = _entier(snapshot.get("semis_daily_cycles_target"), defaut=0)
    if cible > 0:
        faits = _entier(snapshot.get("semis_cycles_completed_today"))
        dose = _nombre(snapshot.get("surface_cycle_mm"))
        texte = f"Cycles de graines faits aujourd'hui : {faits} sur {cible}"
        if dose:
            texte += f" ({_decimal(dose)} mm chacun)"
        prochain = _heure_iso(snapshot.get("semis_followup_due_at"), maintenant)
        if faits < cible and prochain:
            texte += f", prochain vers {prochain}"
        lignes.append(texte + ".")
    else:
        objectif = _nombre(snapshot.get("objectif_mm"))
        if objectif is not None:
            if objectif > 0:
                lignes.append(f"Arrosage du jour : {_decimal(objectif)} mm demandés.")
            else:
                lignes.append("Arrosage du jour : aucun besoin.")

    fenetre = str(snapshot.get("fenetre_optimale") or "").strip()
    if fenetre:
        lignes.append(f"Moment conseillé : {_LIBELLES_FENETRE.get(fenetre, fenetre)}.")
    if arrosage_auto is not None:
        texte = "Arrosage automatique : " + ("activé" if arrosage_auto else "coupé")
        if blocage:
            texte += f" ({blocage})"
        lignes.append(texte + ".")

    reserve = _nombre(snapshot.get("reserve_actuelle_mm"))
    utile = _nombre(snapshot.get("reserve_utile_mm"))
    if reserve is not None:
        lignes.append(
            f"Réserve du sol : {_decimal(reserve)}"
            + (f" / {_decimal(utile)}" if utile else "")
            + " mm."
        )

    meteo: list[str] = []
    temperature = _nombre(snapshot.get("temperature"))
    if temperature is not None:
        meteo.append(f"{_decimal(temperature)} °C")
    vent = _nombre(snapshot.get("vent"))
    if vent is not None:
        meteo.append(f"vent {_decimal(vent)} km/h")
    pluie_demain = _nombre(snapshot.get("pluie_demain"))
    if pluie_demain is not None:
        meteo.append(f"pluie prévue demain {_decimal(pluie_demain)} mm")
    if meteo:
        lignes.append("Météo : " + ", ".join(meteo) + ".")

    tonte = snapshot.get("tonte_autorisee")
    if tonte is not None:
        texte = "Tonte : " + ("autorisée" if tonte else "non autorisée")
        statut = str(snapshot.get("tonte_statut") or "").strip()
        if statut and not tonte:
            texte += f" ({statut.replace('_', ' ')})"
        derniere = _date_courte(snapshot.get("derniere_tonte_date"))
        if derniere:
            texte += f", dernière le {derniere}"
        lignes.append(texte + ".")
    levee = _date_courte(snapshot.get("plantules_levee_date"))
    premiere_coupe = _date_courte(snapshot.get("plantules_premiere_coupe_date"))
    if levee or premiere_coupe:
        morceaux = []
        if levee:
            morceaux.append(f"levée attendue le {levee}")
        if premiere_coupe:
            morceaux.append(f"première coupe le {premiere_coupe}")
        lignes.append("Semis : " + ", ".join(morceaux) + ".")

    application = snapshot.get("derniere_application")
    if isinstance(application, Mapping):
        produit = str(application.get("libelle") or application.get("produit") or "").strip()
        quand = _date_courte(application.get("date") or application.get("date_action"))
        if produit:
            lignes.append(f"Dernier produit : {produit}" + (f" le {quand}" if quand else "") + ".")

    risque = str(snapshot.get("risque_gazon") or "").strip()
    if risque:
        lignes.append(f"Risque pour le gazon : {risque.replace('_', ' ')}.")
    conseil = str(snapshot.get("conseil_principal") or "").strip()
    if conseil:
        lignes.append(f"Conseil du moteur : {conseil}")
    return lignes


# ── Options de l'entrée ────────────────────────────────────────────────────────────────────


def _options_puis_donnees(entry: Any) -> list[Mapping[str, Any]]:
    return [
        source
        for source in (getattr(entry, "options", None), getattr(entry, "data", None))
        if isinstance(source, Mapping)
    ]


def cibles_configurees(entry: Any) -> list[str]:
    """Les téléphones (entités `notify.*`) choisis dans les options, sans doublon."""
    for source in _options_puis_donnees(entry):
        if CONF_NOTIFICATION_CIBLES not in source:
            continue
        brut = source.get(CONF_NOTIFICATION_CIBLES)
        valeurs: Sequence[Any]
        if isinstance(brut, str):
            valeurs = [brut]
        elif isinstance(brut, (list, tuple)):
            valeurs = brut
        else:
            valeurs = []
        cibles: list[str] = []
        for valeur in valeurs:
            texte = str(valeur or "").strip()
            if texte.startswith("notify.") and texte not in cibles:
                cibles.append(texte)
        return cibles
    return []


def alertes_voulues(entry: Any) -> bool:
    for source in _options_puis_donnees(entry):
        if source.get(CONF_ALERTES_ACTIVES) is not None:
            return bool(source[CONF_ALERTES_ACTIVES])
    return DEFAULT_ALERTES_ACTIVES


def mode_notifications(entry: Any) -> str:
    for source in _options_puis_donnees(entry):
        valeur = str(source.get(CONF_MODE_NOTIFICATIONS) or "").strip()
        if valeur in MODES_NOTIFICATIONS:
            return valeur
    return DEFAULT_MODE_NOTIFICATIONS


def source_notifications(entry: Any) -> str:
    """Qui rédige le texte envoyé au téléphone ; le moteur reste seul juge des faits."""
    for source in _options_puis_donnees(entry):
        valeur = str(source.get(CONF_SOURCE_NOTIFICATIONS) or "").strip()
        if valeur in SOURCES_NOTIFICATIONS:
            return valeur
    return DEFAULT_SOURCE_NOTIFICATIONS


def niveau_minimal(entry: Any) -> str:
    for source in _options_puis_donnees(entry):
        valeur = str(source.get(CONF_NOTIFICATION_NIVEAU_MINIMAL) or "").strip()
        if valeur in NIVEAUX_NOTIFICATIONS:
            return valeur
    return DEFAULT_NOTIFICATION_NIVEAU_MINIMAL


def _minute_option(entry: Any, cle: str, defaut: int) -> int:
    for source in _options_puis_donnees(entry):
        if source.get(cle) is None:
            continue
        valeur = _entier(source.get(cle), defaut)
        if 0 <= valeur < 24 * 60:
            return valeur
    return defaut


def heures_calmes(entry: Any) -> tuple[bool, int, int]:
    active = DEFAULT_NOTIFICATION_HEURES_CALMES
    for source in _options_puis_donnees(entry):
        if source.get(CONF_NOTIFICATION_HEURES_CALMES) is not None:
            active = bool(source[CONF_NOTIFICATION_HEURES_CALMES])
            break
    return (
        active,
        _minute_option(entry, CONF_NOTIFICATION_HEURES_CALMES_DEBUT, DEFAULT_NOTIFICATION_HEURES_CALMES_DEBUT),
        _minute_option(entry, CONF_NOTIFICATION_HEURES_CALMES_FIN, DEFAULT_NOTIFICATION_HEURES_CALMES_FIN),
    )


def _est_dans_heures_calmes(entry: Any, maintenant: datetime) -> bool:
    active, debut, fin = heures_calmes(entry)
    if not active or debut == fin:
        return False
    minute = maintenant.hour * 60 + maintenant.minute
    if debut < fin:
        return debut <= minute < fin
    return minute >= debut or minute < fin


def sujets_voulus(entry: Any) -> frozenset[str]:
    """Les familles choisies ; toutes sont actives par défaut pour les anciennes entrées."""
    actifs: set[str] = set()
    sources = _options_puis_donnees(entry)
    for sujet, cle in OPTIONS_PAR_SUJET.items():
        valeur: Any = False if sujet in SUJETS_ACTIVITE else DEFAULT_NOTIFICATION_CATEGORIE_ACTIVE
        for source in sources:
            if source.get(cle) is not None:
                valeur = source[cle]
                break
        if bool(valeur):
            actifs.add(sujet)
    return frozenset(actifs)


def identifiant_trace(entry_id: str, sujet: str) -> str:
    return f"{DOMAIN}_{entry_id}_{sujet}"


# ── Envois (Home Assistant) ────────────────────────────────────────────────────────────────


async def async_envoyer(hass: Any, cibles: Sequence[str], titre: str, message: str) -> list[str]:
    """Envoie à chaque téléphone ; rend ceux qui ont été joints. Un téléphone en panne
    n'empêche pas les autres."""
    jointes: list[str] = []
    for cible in cibles:
        try:
            await hass.services.async_call(
                "notify",
                "send_message",
                {"entity_id": cible, "title": titre, "message": message},
                blocking=True,
            )
        except Exception as err:  # noqa: BLE001 - un téléphone injoignable ne bloque rien
            _LOGGER.warning("Notification vers %s impossible : %s", cible, err)
            continue
        jointes.append(cible)
    return jointes


async def _async_trace(hass: Any, identifiant: str, alerte: Alerte) -> None:
    """La trace dans les notifications de Home Assistant : posée, remplacée ou retirée."""
    service = "dismiss" if alerte.resolue else "create"
    donnees: dict[str, Any] = {"notification_id": identifiant}
    if not alerte.resolue:
        donnees.update({"title": alerte.titre, "message": alerte.message})
    try:
        await hass.services.async_call("persistent_notification", service, donnees, blocking=True)
    except Exception as err:  # noqa: BLE001 - la trace est un confort, jamais un blocage
        _LOGGER.debug("Trace %s (%s) impossible : %s", identifiant, service, err)


async def async_publier(
    hass: Any,
    entry: Any,
    alertes: Sequence[Alerte],
    *,
    maintenant: datetime | None = None,
    contexte: Sequence[str] = (),
) -> None:
    cibles = cibles_configurees(entry)
    minimum = niveau_minimal(entry)
    rang = {niveau: index for index, niveau in enumerate(NIVEAUX_NOTIFICATIONS)}
    instant = maintenant or datetime.now().astimezone()
    calme = _est_dans_heures_calmes(entry, instant)
    for alerte in alertes:
        if alerte.resolue or alerte.persistante:
            await _async_trace(hass, identifiant_trace(entry.entry_id, alerte.sujet), alerte)
        niveau = alerte.niveau if alerte.niveau in rang else "action"
        retenue_par_niveau = rang[niveau] < rang[minimum]
        retenue_par_calme = calme and niveau != "critique"
        if alerte.message and alerte.pousser and cibles and not (
            retenue_par_niveau or retenue_par_calme
        ):
            message = alerte.message
            if source_notifications(entry) == "conseiller_gazon":
                instructions = ia.consigne_notification(
                    alerte.titre,
                    alerte.message,
                    niveau,
                    contexte,
                    maintenant=instant,
                )
                try:
                    message = await ia.async_demander(
                        hass,
                        instructions,
                        entite=ia.entite_effective(hass, entry),
                        delai_s=ia.DELAI_NOTIFICATION_S,
                    )
                    message = message[: ia.MESSAGE_NOTIFICATION_MAX_CARACTERES]
                except ia.IaIndisponible as err:
                    _LOGGER.warning(
                        "Conseiller Gazon indisponible pour la notification %s : %s. "
                        "Le message de l'intégration est envoyé.",
                        alerte.sujet,
                        err,
                    )
            await async_envoyer(hass, cibles, alerte.titre, message)
