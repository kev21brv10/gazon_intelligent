"""Commandes manuelles de la tondeuse (page Gazon) : départ, bordure, retour, pause — volet compris.

Ce module est pur : il ne connaît ni Home Assistant ni ses services. Le coordinateur lui passe l'état
de la tondeuse et du volet, exécute l'action retournée, et enregistre l'état de la commande.

⚠️ POURQUOI UNE ORCHESTRATION CÔTÉ SERVEUR. Un départ demande une SÉQUENCE : ouvrir le volet,
attendre sa confirmation et le délai de sécurité, puis seulement envoyer le départ. Faite depuis le
navigateur, elle s'arrête dès que l'onglet se ferme, et personne ne contrôle l'état du volet entre
deux ordres. Ici chaque étape est rejugée à chaque cycle, avec l'état réel.

MODE MANUEL. Tant qu'une commande manuelle est en cours, le pilote automatique ne rappelle pas la
tondeuse, ne ferme pas le volet et ne relance rien — sans changer le réglage du pilotage. Une seule
règle du pilote reste active : une tondeuse dehors ne doit jamais trouver son volet fermé. Après un
RETOUR manuel, les départs automatiques sont suspendus un moment : sinon le pilote, voyant une
tondeuse à quai et des conditions favorables, la renverrait aussitôt.

Les commandes ne dépendent pas du mode du pilote (désactivé, observation, actif) : c'est une action
explicite de l'utilisateur. Les gardes matérielles, elles, restent.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from . import garage_guard

COMMANDES = ("demarrer", "bordure", "retour", "pause", "reprendre")
DEPARTS = frozenset({"demarrer", "bordure"})
# Ces commandes passent devant une commande en cours : elles ne mettent jamais la machine en
# danger, et c'est ce qu'on veut au milieu d'une sortie (« stop, rentre », « pause »).
PRIORITAIRES = frozenset({"retour", "pause", "reprendre"})

# Batterie minimale pour un départ manuel : en dessous, la tondeuse rentrerait presque aussitôt
# (même seuil que celui qui classe un retour « batterie vide » au carnet des passes).
MANUAL_MIN_BATTERY = 20.0
# Combien de temps un départ peut attendre l'ouverture confirmée du volet avant d'être abandonné
# (de quoi laisser jouer les trois tentatives du volet, espacées de 2 min, et son délai de mouvement).
MANUAL_GARAGE_WAIT_MAX_MINUTES = 8.0
# Combien de temps attendre un signe de sortie après l'envoi du départ.
MANUAL_START_CONFIRM_MAX_MINUTES = 5.0
# Le mode manuel d'un départ dure au plus ceci (la tondeuse gère seule ses recharges).
MANUAL_MAX_OUTING_MINUTES = 240.0
# Pour une coupe de bordure : sa durée choisie + cette marge de rentrée.
MANUAL_EDGE_MARGIN_MINUTES = 20.0
# Une pause garde le mode manuel : le pilote ne la défait pas en rappelant la tondeuse.
MANUAL_PAUSE_MINUTES = 60.0
# Départs automatiques suspendus après un retour manuel.
MANUAL_HOLD_AFTER_RETURN_MINUTES = 240.0
# Durée d'une coupe de bordure (service `landroid_cloud.ots` : 10 à 120 minutes).
EDGE_MIN_MINUTES = 10
EDGE_MAX_MINUTES = 120
EDGE_DEFAULT_MINUTES = 30
# Délai de sécurité par défaut après l'ouverture du volet (comme le pilote).
_DEFAULT_OPEN_LEAD_MINUTES = 2.0

ACTIVE_STEPS = frozenset({
    "ouverture_garage", "attente_garage", "depart_envoye", "dehors", "retour_envoye", "pause_envoyee",
    "reprise_envoyee",
})
TERMINAL_STEPS = frozenset({"termine", "annule", "erreur", "expire"})

_OUTSIDE_OPERATIONS = frozenset({"tonte", "mowing", "starting", "zoning", "edgecut", "transit"})


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _instant(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _minutes_since(now: datetime, value: Any) -> float | None:
    parsed = _instant(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None and now.tzinfo is not None:
        parsed = parsed.replace(tzinfo=now.tzinfo)
    elif parsed.tzinfo is not None and now.tzinfo is None:
        now = now.replace(tzinfo=parsed.tzinfo)
    return (now - parsed) / timedelta(minutes=1)


def _in_the_future(now: datetime, value: Any) -> bool:
    elapsed = _minutes_since(now, value)
    return elapsed is not None and elapsed < 0.0


def edge_duration(value: Any) -> int:
    """Durée de bordure valide (10 à 120 min), 30 par défaut ; une valeur illisible est ramenée."""
    number = _number(value)
    if number is None:
        return EDGE_DEFAULT_MINUTES
    return int(min(EDGE_MAX_MINUTES, max(EDGE_MIN_MINUTES, round(number))))


def is_active(state: Mapping[str, Any] | None, now: datetime) -> bool:
    """Une commande manuelle est en cours (le pilote automatique doit s'effacer)."""
    if not isinstance(state, Mapping) or state.get("etape") not in ACTIVE_STEPS:
        return False
    return _in_the_future(now, state.get("jusqu_a"))


def suspension_active(runtime: Mapping[str, Any] | None, now: datetime) -> bool:
    """Les départs automatiques sont suspendus après un retour manuel."""
    return isinstance(runtime, Mapping) and _in_the_future(now, runtime.get("suspension_jusqu_a"))


def _strong_dock(snapshot: Mapping[str, Any]) -> bool:
    operation = str(snapshot.get("mower_operation_state") or "").lower()
    return snapshot.get("mower_dock_signal_fort") is True or operation in {"docked", "charging"}


def _outside(snapshot: Mapping[str, Any]) -> bool:
    operation = str(snapshot.get("mower_operation_state") or "").lower()
    return (
        snapshot.get("mower_is_outside") is True
        or snapshot.get("mower_is_mowing") is True
        or snapshot.get("mower_is_returning") is True
        or operation in _OUTSIDE_OPERATIONS
    )


def _paused(snapshot: Mapping[str, Any]) -> bool:
    """La tondeuse est en pause — que ce soit depuis cette page, depuis l'appli du constructeur ou à la main.

    ⚠️ L'état de travail ne suffit pas : `en_pause` n'existe que tondeuse À QUAI ; dehors, le suivi du
    travail rend `en_cours` (ou `sans_mesure`). Seul l'état de la machine dit qu'elle est en pause.
    """
    operation = str(snapshot.get("mower_operation_state") or "").lower()
    status = str(snapshot.get("tondeuse_statut") or "").lower()
    job = str(snapshot.get("mower_job_completion_state") or "").lower()
    return operation in {"paused", "pause"} or status == "pause" or job == "en_pause"


def _battery(snapshot: Mapping[str, Any]) -> float | None:
    return _number(snapshot.get("mower_battery", snapshot.get("tondeuse_batterie")))


def validate_request(
    commande: Any,
    snapshot: Mapping[str, Any],
    *,
    state: Mapping[str, Any] | None,
    now: datetime,
    irrigation_active: bool,
    edgecut_available: bool,
    cover_known: bool = True,
) -> str | None:
    """Pourquoi une commande est REFUSÉE tout de suite, ou None si elle peut être prise.

    Jugé à la demande ET rejugé à chaque cycle (voir `evaluate`) : l'état change entre-temps.
    """
    if commande not in COMMANDES:
        return "Commande inconnue."
    en_cours = state.get("commande") if is_active(state, now) and isinstance(state, Mapping) else None
    if en_cours is not None and (commande not in PRIORITAIRES or commande == en_cours):
        return "Une commande manuelle est déjà en cours : attendre sa fin ou l'annuler."
    if snapshot.get("tondeuse_connectee") is not True:
        return "La tondeuse n'est pas connectée."
    if commande == "bordure" and not edgecut_available:
        return "La coupe de bordure n'est pas disponible avec cette tondeuse."
    if commande in DEPARTS | {"retour", "reprendre"} and not cover_known:
        return "Le volet ne répond pas : la tondeuse ne peut pas sortir ni rentrer."
    if commande in DEPARTS:
        if snapshot.get("tondeuse_prete") is not True:
            return "La tondeuse n'est pas prête."
        if not _strong_dock(snapshot):
            return "La tondeuse doit être à sa base pour partir."
        battery = _battery(snapshot)
        if battery is not None and battery < MANUAL_MIN_BATTERY:
            return f"La batterie est trop basse pour partir ({battery:g} %, minimum {MANUAL_MIN_BATTERY:g} %)."
        if irrigation_active:
            return "Un arrosage est en cours : la tondeuse ne part pas pendant l'eau."
    if commande == "retour" and _strong_dock(snapshot) and not _outside(snapshot):
        return "La tondeuse est déjà à sa base."
    if commande == "pause" and not _outside(snapshot):
        return "La tondeuse n'est pas dehors : rien à mettre en pause."
    if commande == "reprendre":
        if not _outside(snapshot):
            return "La tondeuse n'est pas dehors : rien à reprendre."
        if en_cours != "pause" and not _paused(snapshot):
            return "La tondeuse n'est pas en pause."
    return None


def new_state(
    commande: str,
    now: datetime,
    *,
    duree_min: Any = None,
) -> dict[str, Any]:
    """L'état d'une commande qui vient d'être acceptée."""
    duree = edge_duration(duree_min) if commande == "bordure" else None
    if commande == "bordure":
        total = float(duree or EDGE_DEFAULT_MINUTES) + MANUAL_EDGE_MARGIN_MINUTES
    elif commande == "pause":
        total = MANUAL_PAUSE_MINUTES
    else:
        total = MANUAL_MAX_OUTING_MINUTES
    return {
        "commande": commande,
        "duree_min": duree,
        "demande_a": now.isoformat(),
        "fini_a": None,
        "etape": {"pause": "pause_envoyee", "reprendre": "reprise_envoyee"}.get(commande, "ouverture_garage"),
        "garage_confirme_a": None,
        "envoye_a": None,
        "vu_dehors": False,
        "jusqu_a": (now + timedelta(minutes=total)).isoformat(),
        "erreur": None,
    }


def cancel(state: Mapping[str, Any] | None, now: datetime) -> dict[str, Any]:
    """Annule la commande en cours : le mode manuel s'arrête, le pilote reprend la main."""
    base = dict(state) if isinstance(state, Mapping) else {}
    base.update({"etape": "annule", "erreur": None, "fini_a": now.isoformat()})
    return base


def _result(
    state: Mapping[str, Any],
    etape: str,
    reason: str,
    *,
    action: dict[str, Any] | None = None,
    updates: Mapping[str, Any] | None = None,
    finished: bool = False,
    suspension_minutes: float | None = None,
) -> dict[str, Any]:
    return {
        "etape": etape,
        "reason": reason,
        "action": action,
        "updates": {**dict(updates or {}), "etape": etape},
        "finished": finished,
        "suspension_minutes": suspension_minutes,
    }


def _open_lead(settings: Mapping[str, Any] | None) -> float:
    value = _number((settings or {}).get("tondeuse_garage_avance_ouverture"))
    return _DEFAULT_OPEN_LEAD_MINUTES if value is None else max(0.0, value)


def _min_open_position(settings: Mapping[str, Any] | None) -> float:
    value = _number((settings or {}).get("tondeuse_garage_ouverture_min"))
    return 95.0 if value is None else min(100.0, max(0.0, value))


def evaluate(
    snapshot: Mapping[str, Any],
    *,
    now: datetime,
    state: Mapping[str, Any],
    cover_entity: str | None,
    cover_state: Any,
    cover_position: Any,
    settings: Mapping[str, Any] | None,
    garage_runtime: Mapping[str, Any],
    irrigation_active: bool,
    edgecut_available: bool,
) -> dict[str, Any]:
    """L'étape suivante d'une commande en cours : {etape, reason, action, updates, finished}.

    `action` : None, ou {"service": "domaine.service", "data": {...}} à exécuter. Le coordinateur
    n'exécute que la première ; l'état est rejugé au cycle suivant.
    """
    etape = str(state.get("etape") or "")
    commande = str(state.get("commande") or "")
    if etape in TERMINAL_STEPS or commande not in COMMANDES:
        return _result(state, etape or "termine", "Aucune commande en cours.", finished=True)
    if not _in_the_future(now, state.get("jusqu_a")):
        return _result(state, "expire", "La commande manuelle a expiré : le pilote reprend la main.", finished=True)

    cover = str(cover_state or "").strip().lower()
    min_open = _min_open_position(settings)
    confirmed = (
        cover == "open"
        and (_number(cover_position) is None or float(_number(cover_position) or 0.0) >= min_open)
    )
    cover_known = cover not in {"", "none", "unavailable", "unknown"}
    # ⚠️ UNE TONDEUSE DEHORS NE DOIT JAMAIS TROUVER SON VOLET FERMÉ, quel que soit le mode du pilote.
    # Le pilote tient cette règle, mais seulement en mode actif (désactivé : il s'arrête avant ;
    # observation : il ne fait qu'afficher). Or une commande manuelle marche dans les trois modes :
    # tant qu'elle dure, c'est elle qui rouvre un volet refermé en route (à la main, par une
    # automatisation…). Même registre d'ordres que le pilote : pas de doublon.
    needs_open = bool(cover_entity) and cover_known and _outside(snapshot) and not confirmed and cover != "opening"

    def waiting(step: str, reason: str, *, updates: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if needs_open:
            blocage = garage_guard.command_gate("open_cover", garage_runtime, settings, now)
            if blocage is not None:
                return _result(state, step, blocage["reason"], updates=updates)
            return _result(
                state, step, "Volet fermé devant une tondeuse dehors : ouverture du volet.",
                action={"service": "cover.open_cover", "data": {}}, updates=updates,
            )
        return _result(state, step, reason, updates=updates)

    # ── Pause : un seul ordre, puis le mode manuel tient le temps d'une pause ──
    if commande == "pause":
        if not state.get("envoye_a"):
            return _result(
                state, "pause_envoyee", "Pause demandée à la tondeuse.",
                action={"service": "lawn_mower.pause", "data": {}},
                updates={"envoye_a": now.isoformat()},
            )
        return waiting("pause_envoyee", "Tondeuse en pause : le pilote ne la rappelle pas.")

    # Volet à OUVRIR ET CONFIRMÉ avant l'ordre (retour, reprise). None = confirmé, ou aucun volet.
    def cover_first(*, mute: str, late: str, opening: str, open_it: str) -> dict[str, Any] | None:
        if not cover_entity:
            return None
        if not cover_known:
            return _result(state, "erreur", mute, finished=True, updates={"erreur": "volet_indisponible"})
        if confirmed:
            return None
        blocage = None if cover == "opening" else garage_guard.command_gate(
            "open_cover", garage_runtime, settings, now
        )
        if blocage is not None and blocage["state"] == "volet_bloque":
            return _result(state, "erreur", blocage["reason"], finished=True, updates={"erreur": "volet_bloque"})
        waited_total = _minutes_since(now, state.get("demande_a"))
        if waited_total is not None and waited_total >= MANUAL_GARAGE_WAIT_MAX_MINUTES:
            return _result(state, "erreur", late, finished=True, updates={"erreur": "volet_non_ouvert"})
        if cover == "opening":
            return _result(state, "attente_garage", opening)
        if blocage is not None:
            return _result(state, "attente_garage", blocage["reason"])
        return _result(state, "ouverture_garage", open_it, action={"service": "cover.open_cover", "data": {}})

    # ── Reprise après une pause : la tondeuse est dehors ──
    # ⚠️ Même ordre que le retour : volet ouvert ET confirmé AVANT l'ordre. Elle est dehors, mais rien
    # ne garantit que le volet est encore ouvert (refermé à la main, par une automatisation) ; la
    # reprise ne doit jamais la laisser repartir vers un volet qu'on ne sait pas ouvert.
    # Une fois l'ordre parti, la commande est « dehors » : elle suit le chemin d'un départ (le mode
    # manuel tient jusqu'à la fin du travail ou l'échéance).
    if commande == "reprendre" and not state.get("envoye_a"):
        if not _outside(snapshot):
            return _result(state, "erreur", "La tondeuse n'est plus dehors : reprise abandonnée.", finished=True,
                           updates={"erreur": "pas_dehors"})
        attente = cover_first(
            mute="Le volet ne répond pas : la reprise n'est pas lancée.",
            late="Le volet n'est pas ouvert après plusieurs minutes : reprise non lancée.",
            opening="Ouverture du volet en cours avant la reprise.",
            open_it="Ouverture du volet avant la reprise.",
        )
        if attente is not None:
            return attente
        return _result(
            state, "dehors", "Reprise demandée à la tondeuse.",
            action={"service": "lawn_mower.start_mowing", "data": {}},
            updates={"envoye_a": now.isoformat(), "vu_dehors": True},
        )

    # ── Retour : volet ouvert d'abord, puis le retour ──
    if commande == "retour":
        if state.get("envoye_a"):
            if _strong_dock(snapshot) and not _outside(snapshot):
                return _result(
                    state, "termine", "La tondeuse est rentrée.", finished=True,
                    suspension_minutes=MANUAL_HOLD_AFTER_RETURN_MINUTES,
                )
            return waiting("retour_envoye", "Retour demandé : la tondeuse rentre.")
        attente = cover_first(
            mute="Le volet ne répond pas : le retour n'est pas lancé.",
            late="Le volet n'est pas ouvert après plusieurs minutes : retour non lancé.",
            opening="Ouverture du volet en cours avant le retour.",
            open_it="Ouverture du volet avant le retour.",
        )
        if attente is not None:
            return attente
        return _result(
            state, "retour_envoye", "Retour demandé à la tondeuse.",
            action={"service": "lawn_mower.dock", "data": {}},
            updates={"envoye_a": now.isoformat()},
            suspension_minutes=MANUAL_HOLD_AFTER_RETURN_MINUTES,
        )

    # ── Départ (normal ou coupe de bordure) ──
    if etape == "depart_envoye":
        if _outside(snapshot):
            return waiting("dehors", "La tondeuse est dehors : le pilote ne la rappelle pas.",
                           updates={"vu_dehors": True})
        waited = _minutes_since(now, state.get("envoye_a"))
        if waited is not None and waited >= MANUAL_START_CONFIRM_MAX_MINUTES:
            return _result(state, "erreur", "Aucune sortie confirmée après le départ.", finished=True,
                           updates={"erreur": "depart_non_confirme"})
        return _result(state, "depart_envoye", "Départ envoyé : attente de la sortie de la tondeuse.")
    if etape == "dehors":
        # ⚠️ « Travail TERMINÉ » seulement — jamais « repos » : l'état de travail est « repos » AVANT que
        # la tâche ait été vue inachevée, donc pendant le rebond de démarrage de la tondeuse
        # (`starting` → `docked` quelques secondes → `starting`, mesuré). Une recharge au milieu du
        # travail (70 min) ne termine rien non plus : le pilote n'a pas à reprendre la main.
        done = state.get("vu_dehors") and _strong_dock(snapshot) and not _outside(snapshot) and (
            str(snapshot.get("mower_job_completion_state") or "").lower() == "termine"
        )
        if done:
            return _result(state, "termine", "Travail terminé : la tondeuse est rentrée.", finished=True)
        return waiting("dehors", "La tondeuse travaille : le pilote ne la rappelle pas.")

    # Étapes d'ouverture du volet puis départ.
    waited_total = _minutes_since(now, state.get("demande_a"))
    if state.get("envoye_a"):
        return _result(state, "depart_envoye", "Départ envoyé : attente de la sortie de la tondeuse.")
    if snapshot.get("tondeuse_connectee") is not True or snapshot.get("tondeuse_prete") is not True:
        return _result(state, "erreur", "La tondeuse n'est plus prête : départ abandonné.", finished=True,
                       updates={"erreur": "tondeuse_indisponible"})
    if not _strong_dock(snapshot):
        return _result(state, "erreur", "La tondeuse n'est plus à sa base : départ abandonné.", finished=True,
                       updates={"erreur": "pas_a_quai"})
    if irrigation_active:
        return _result(state, "erreur", "Un arrosage a démarré : départ abandonné.", finished=True,
                       updates={"erreur": "arrosage"})
    battery = _battery(snapshot)
    if battery is not None and battery < MANUAL_MIN_BATTERY:
        return _result(state, "erreur", "La batterie est trop basse : départ abandonné.", finished=True,
                       updates={"erreur": "batterie"})
    if commande == "bordure" and not edgecut_available:
        return _result(state, "erreur", "La coupe de bordure n'est plus disponible.", finished=True,
                       updates={"erreur": "bordure_indisponible"})

    if cover_entity:
        if not cover_known:
            return _result(state, "erreur", "Le volet ne répond pas : départ abandonné.", finished=True,
                           updates={"erreur": "volet_indisponible"})
        if not confirmed:
            # Le plafond de tentatives du volet prime : « bloqué » dit mieux ce qui se passe que
            # « pas ouvert après X minutes ».
            blocage = None if cover == "opening" else garage_guard.command_gate(
                "open_cover", garage_runtime, settings, now
            )
            if blocage is not None and blocage["state"] == "volet_bloque":
                return _result(state, "erreur", blocage["reason"], finished=True, updates={"erreur": "volet_bloque"})
            if waited_total is not None and waited_total >= MANUAL_GARAGE_WAIT_MAX_MINUTES:
                return _result(state, "erreur", "Le volet n'est pas ouvert après plusieurs minutes : départ abandonné.",
                               finished=True, updates={"erreur": "volet_non_ouvert"})
            if cover == "opening":
                return _result(state, "attente_garage", "Ouverture du volet en cours avant le départ.",
                               updates={"garage_confirme_a": None})
            if blocage is not None:
                return _result(state, "attente_garage", blocage["reason"])
            return _result(state, "ouverture_garage", "Ouverture du volet avant le départ.",
                           action={"service": "cover.open_cover", "data": {}},
                           updates={"garage_confirme_a": None})
        confirmed_at = state.get("garage_confirme_a")
        if not confirmed_at:
            return _result(state, "attente_garage", "Volet ouvert : délai de sécurité avant le départ.",
                           updates={"garage_confirme_a": now.isoformat()})
        elapsed = _minutes_since(now, confirmed_at)
        lead = _open_lead(settings)
        if elapsed is None or elapsed < lead:
            return _result(state, "attente_garage", "Volet ouvert : délai de sécurité avant le départ.")

    if commande == "bordure":
        action: dict[str, Any] = {
            "service": "landroid_cloud.ots",
            "data": {"boundary": True, "runtime": edge_duration(state.get("duree_min"))},
        }
        reason = "Coupe de bordure demandée à la tondeuse."
    else:
        action = {"service": "lawn_mower.start_mowing", "data": {}}
        reason = "Départ demandé à la tondeuse."
    return _result(state, "depart_envoye", reason, action=action, updates={"envoye_a": now.isoformat()})
