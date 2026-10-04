"""Garde-fous du volet de garage : tentatives, reprise, alerte « volet bloqué », ouverture à la main.

Ce module est pur : il ne connaît ni Home Assistant ni ses services. `mower_control` l'interroge
avant d'envoyer un ordre de volet ; le coordinateur tient le registre des ordres envoyés (dans
l'état runtime du pilote) et publie l'alerte.

⚠️ POURQUOI. Avant lui, un volet qui acceptait un ordre sans bouger (message radio perdu, moteur
coincé) était relancé toutes les dix minutes — le délai PARTAGÉ par toutes les commandes — sans
plafond de tentatives et sans la moindre alerte : le pilote attendait ou renvoyait indéfiniment, et
seule une erreur du SERVICE était signalée, jamais un volet qui ne bouge pas. Et un volet ouvert à
la main, tondeuse à quai, était refermé après le délai normal de la rentrée (1 à 2 minutes), alors
qu'aucune rentrée n'avait eu lieu.

Le registre tient une SÉRIE : les ordres successifs du même sens, tant que la cible n'est pas
atteinte. Une série qui n'a pas épuisé ses tentatives est oubliée au bout d'une heure sans ordre. Une
série ÉPUISÉE — plafond atteint, volet bloqué — tient jusqu'à ce que le volet atteigne sa position
(ou 24 h) : le pilote n'envoie plus rien et l'alerte reste affichée, jusqu'à réparation. Décision du
propriétaire : sans cela, l'oubli au bout d'une heure relançait trois ordres, effaçait l'alerte puis
la renvoyait à chaque série.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from math import ceil
from typing import Any

# Si le volet ne bouge pas, combien attendre avant de renvoyer l'ordre. Remplace, pour le volet,
# le délai commun à toutes les commandes (10 min) : un ordre raté ne doit pas retarder un départ
# d'autant.
DEFAULT_GARAGE_RETRY_DELAY_MINUTES = 2.0
# Au-delà, depuis le premier ordre de la série, un volet qui n'a pas atteint sa position est
# « bloqué » : l'alerte part. Ouverture ou fermeture complète : une dizaine de secondes chez
# l'installation de référence, la marge est large.
DEFAULT_GARAGE_MAX_TRAVEL_MINUTES = 3.0
# Plafond d'ordres automatiques pour une même série : ensuite, intervention manuelle.
DEFAULT_GARAGE_MAX_ATTEMPTS = 3
# Un volet ouvert À LA MAIN, tondeuse à quai, n'est pas refermé comme après une rentrée : il laisse
# plus de temps (quelqu'un l'a peut-être ouvert pour une autre raison).
DEFAULT_GARAGE_MANUAL_CLOSE_DELAY_MINUTES = 30.0
# Une série NON épuisée dont le dernier ordre date de plus d'une heure est oubliée : ce sont deux
# pannes différentes, pas une suite d'échecs.
GARAGE_SERIES_WINDOW_MINUTES = 60.0
# Une série ÉPUISÉE (plafond de tentatives atteint) tient jusqu'à ce que le volet atteigne sa
# position ; au-delà de 24 h elle est oubliée, pour qu'un volet réparé sans que personne ne l'ait
# manœuvré ne reste pas bloqué indéfiniment.
GARAGE_BLOCK_WINDOW_MINUTES = 24 * 60.0
# Un volet indisponible n'est signalé (tondeuse dehors) qu'après ce délai de grâce.
GARAGE_UNAVAILABLE_GRACE_MINUTES = 5.0
# Marge avant d'alerter d'un volet fermé devant une tondeuse dehors : en mode actif le pilote (ou la commande
# manuelle) le rouvre au cycle suivant, et un volet met une dizaine de secondes à s'ouvrir.
GARAGE_CLOSED_OUTSIDE_GRACE_MINUTES = 3.0
# Une ouverture ou fermeture confirmée n'est notifiée que si c'est le pilote qui l'a ordonnée, il y a
# moins de ce délai : un volet manœuvré à la main ne dérange personne.
GARAGE_NOTIFY_WINDOW_MINUTES = 15.0
# Le défaut du délai de fermeture après une rentrée (même valeur que `mower_control_constants`,
# répétée ici pour ne pas créer de dépendance circulaire).
_DEFAULT_CLOSE_DELAY_MINUTES = 2.0
_DEFAULT_MIN_OPEN_POSITION = 95.0

COVER_ACTIONS = frozenset({"open_cover", "close_cover"})

# Clés du registre, dans l'état runtime persistant du pilote.
KEY_COMMAND = "garage_commande"
KEY_COMMAND_AT = "garage_commande_a"
KEY_SERIES_START = "garage_serie_debut"
KEY_ATTEMPTS = "garage_tentatives"
KEY_OPENED_BY_PILOT = "garage_ouvert_par_pilote"
# Depuis quand le volet est vu ouvert. Sert au délai de fermeture d'un volet ouvert À LA MAIN :
# mesuré depuis la rentrée de la tondeuse, il serait écoulé d'emblée (quai depuis des heures) et le
# volet serait refermé à la première évaluation — c'est ce que l'essai du 03/10/2026 a montré.
KEY_OPEN_SINCE = "garage_ouvert_depuis"
# Depuis quand le volet est vu indisponible. Un volet « indisponible » juste après un redémarrage de
# Home Assistant est normal pendant une ou deux minutes : on n'alerte qu'au-delà d'un délai de grâce.
KEY_UNAVAILABLE_SINCE = "garage_indisponible_depuis"
# Depuis quand le volet est vu non ouvert alors que la tondeuse est dehors.
KEY_CLOSED_OUTSIDE_SINCE = "garage_ferme_dehors_depuis"
# Le volet auquel appartient ce registre. Changer de volet (remplacement, autre entité) ne doit pas
# transmettre au nouveau les ordres, les tentatives et le blocage de l'ancien : un nouveau volet
# fermé serait sinon tenu pour « bloqué » pendant 24 h.
KEY_ENTITY = "garage_entite"
_ENTITY_BOUND_KEYS = (
    KEY_COMMAND, KEY_COMMAND_AT, KEY_SERIES_START, KEY_OPENED_BY_PILOT, KEY_OPEN_SINCE, KEY_UNAVAILABLE_SINCE,
    KEY_CLOSED_OUTSIDE_SINCE,
)

ALERT_UNAVAILABLE = "volet_indisponible"
ALERT_STUCK = "volet_bloque"
ALERT_CLOSED_OUTSIDE = "volet_ferme_dehors"

_UNKNOWN_COVER_STATES = frozenset({"", "none", "unavailable", "unknown"})


def _number(value: Any, default: float) -> float:
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number == number else default


def _setting(settings: Mapping[str, Any] | None, key: str, default: float) -> float:
    return _number((settings or {}).get(key), default)


def _instant(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _minutes_since(now: datetime, value: Any) -> float | None:
    """Minutes écoulées depuis un instant ISO, ou None s'il est absent ou illisible.

    ⚠️ Un instant absent ou abîmé n'est jamais « récent » : il ne doit pas bloquer un ordre de
    matériel pour toujours.
    """
    parsed = _instant(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None and now.tzinfo is not None:
        parsed = parsed.replace(tzinfo=now.tzinfo)
    elif parsed.tzinfo is not None and now.tzinfo is None:
        now = now.replace(tzinfo=parsed.tzinfo)
    return (now - parsed) / timedelta(minutes=1)


def _maximum(settings: Mapping[str, Any] | None) -> int:
    return max(1, int(_setting(settings, "tondeuse_garage_tentatives_max", DEFAULT_GARAGE_MAX_ATTEMPTS)))


def exhausted(runtime: Mapping[str, Any], settings: Mapping[str, Any] | None = None) -> bool:
    """La série d'ordres a atteint le plafond de tentatives : le volet est bloqué."""
    return bool(runtime.get(KEY_COMMAND)) and int(_number(runtime.get(KEY_ATTEMPTS), 0.0)) >= _maximum(settings)


def series_alive(
    runtime: Mapping[str, Any],
    now: datetime,
    settings: Mapping[str, Any] | None = None,
) -> bool:
    """Une série d'ordres de volet est en cours : sa cible n'a pas été atteinte ni la série oubliée.

    Oubliée au bout d'une heure sans ordre ; sauf si elle est ÉPUISÉE, auquel cas elle tient jusqu'à
    24 h (le volet est bloqué : le pilote s'arrête et l'alerte reste, jusqu'à réparation).
    """
    if not runtime.get(KEY_COMMAND):
        return False
    elapsed = _minutes_since(now, runtime.get(KEY_COMMAND_AT))
    if elapsed is None or elapsed < 0.0:
        return False
    limit = GARAGE_BLOCK_WINDOW_MINUTES if exhausted(runtime, settings) else GARAGE_SERIES_WINDOW_MINUTES
    return elapsed < limit


def target_reached(
    action: str,
    cover_state: Any,
    position: Any,
    min_open_position: float = _DEFAULT_MIN_OPEN_POSITION,
) -> bool:
    """Le volet est-il là où l'ordre voulait l'amener ?"""
    cover = str(cover_state or "").strip().lower()
    if action == "open_cover":
        if cover != "open":
            return False
        if isinstance(position, bool):
            return True
        try:
            return float(position) >= min_open_position
        except (TypeError, ValueError):
            return True  # Pas de position publiée : l'état « ouvert » suffit, comme pour le pilote.
    if action == "close_cover":
        return cover == "closed"
    return False


def command_gate(
    action: str,
    runtime: Mapping[str, Any],
    settings: Mapping[str, Any] | None,
    now: datetime,
) -> dict[str, str] | None:
    """Faut-il retenir un ordre de volet ? None s'il peut partir, sinon {state, reason}.

    Une nouvelle série (autre sens, ou série oubliée) part toujours. Dans une série : plafond de
    tentatives, puis délai de reprise PROPRE au volet.
    """
    if action not in COVER_ACTIONS:
        return None
    if runtime.get(KEY_COMMAND) != action or not series_alive(runtime, now, settings):
        return None
    attempts = int(_number(runtime.get(KEY_ATTEMPTS), 0.0))
    maximum = _maximum(settings)
    if attempts >= maximum:
        return {
            "state": "volet_bloque",
            "reason": (
                f"Le volet n'a pas atteint sa position après {attempts} tentatives : "
                "intervention manuelle nécessaire."
            ),
        }
    delay = _setting(settings, "tondeuse_garage_delai_reprise", DEFAULT_GARAGE_RETRY_DELAY_MINUTES)
    elapsed = _minutes_since(now, runtime.get(KEY_COMMAND_AT))
    if elapsed is not None and elapsed < delay:
        remaining = max(1, ceil(delay - elapsed))
        return {
            "state": "temporisation",
            "reason": f"Ordre de volet déjà envoyé : nouvelle tentative dans {remaining} min.",
        }
    return None


def after_command(
    runtime: Mapping[str, Any],
    action: str,
    instant_iso: str,
    now: datetime,
    *,
    settings: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Mises à jour du registre après un ordre de volet ENVOYÉ avec succès à Home Assistant."""
    if action not in COVER_ACTIONS:
        return {}
    continuing = runtime.get(KEY_COMMAND) == action and series_alive(runtime, now, settings)
    attempts = (int(_number(runtime.get(KEY_ATTEMPTS), 0.0)) if continuing else 0) + 1
    updates: dict[str, Any] = {
        KEY_COMMAND: action,
        KEY_COMMAND_AT: instant_iso,
        KEY_ATTEMPTS: attempts,
        KEY_SERIES_START: (
            runtime.get(KEY_SERIES_START) if continuing and runtime.get(KEY_SERIES_START) else instant_iso
        ),
    }
    if action == "open_cover":
        updates[KEY_OPENED_BY_PILOT] = True
    return updates


def entity_updates(runtime: Mapping[str, Any], cover_entity: str | None) -> dict[str, Any]:
    """Lie le registre au volet configuré ; un AUTRE volet repart d'un registre vierge.

    Un registre d'avant cette liaison (aucune entité mémorisée) est adopté tel quel : on ne sait pas à
    quel volet il appartenait, et l'effacer à l'aveugle changerait le comportement en silence.
    """
    if not cover_entity:
        return {}
    known = runtime.get(KEY_ENTITY)
    if known == cover_entity:
        return {}
    updates: dict[str, Any] = {KEY_ENTITY: cover_entity}
    if known:
        updates.update({key: None for key in _ENTITY_BOUND_KEYS})
        updates[KEY_ATTEMPTS] = 0
    return updates


def _open_confirmed(cover: str, position: Any, min_open_position: float) -> bool:
    """Le volet est ouvert ET assez grand pour laisser passer la tondeuse (position inconnue : ouvert)."""
    if cover != "open":
        return False
    number = _number(position, -1.0)
    return number < 0.0 or number >= min_open_position


def reset_updates(
    runtime: Mapping[str, Any],
    cover_state: Any,
    position: Any,
    now: datetime,
    min_open_position: float = _DEFAULT_MIN_OPEN_POSITION,
    *,
    settings: Mapping[str, Any] | None = None,
    mower_away: bool = False,
) -> dict[str, Any]:
    """Ce qu'il faut effacer du registre au vu de l'état ACTUEL du volet.

    - cible atteinte, ou série oubliée : plus de série en cours (une série épuisée n'est pas oubliée
      avant 24 h : le pilote reste arrêté jusqu'à réparation) ;
    - volet fermé : il n'a plus été ouvert par le pilote — SAUF si l'ordre d'ouverture vient de
      partir et que le volet n'a pas encore bougé (on perdrait le fait que c'est nous qui ouvrons).
    """
    updates: dict[str, Any] = {}
    command = runtime.get(KEY_COMMAND)
    alive = series_alive(runtime, now, settings)
    if command and (not alive or target_reached(command, cover_state, position, min_open_position)):
        updates.update({KEY_COMMAND: None, KEY_COMMAND_AT: None, KEY_ATTEMPTS: 0, KEY_SERIES_START: None})
        alive = False
    cover = str(cover_state or "").strip().lower()
    closed = cover == "closed"
    opening_pending = alive and command == "open_cover"
    # Vu FERMÉ : on sait que la prochaine ouverture n'est pas encore celle du pilote. C'est ce « faux »
    # explicite qui désigne une ouverture à la main — l'absence de trace (jamais vu fermé, état
    # d'avant cette version) reste traitée comme avant, délai normal, pour ne rien changer en silence.
    if closed and runtime.get(KEY_OPENED_BY_PILOT) is not False and not opening_pending:
        updates[KEY_OPENED_BY_PILOT] = False
    if cover in {"open", "opening"} and not runtime.get(KEY_OPEN_SINCE):
        updates[KEY_OPEN_SINCE] = now.isoformat()
    elif closed and runtime.get(KEY_OPEN_SINCE):
        updates[KEY_OPEN_SINCE] = None
    if cover in _UNKNOWN_COVER_STATES:
        if not runtime.get(KEY_UNAVAILABLE_SINCE):
            updates[KEY_UNAVAILABLE_SINCE] = now.isoformat()
    elif runtime.get(KEY_UNAVAILABLE_SINCE):
        updates[KEY_UNAVAILABLE_SINCE] = None
    # Volet non ouvert devant une tondeuse dehors : depuis quand (l'alerte attend une marge).
    not_open_outside = mower_away and cover not in _UNKNOWN_COVER_STATES and not _open_confirmed(
        cover, position, min_open_position
    )
    if not_open_outside:
        if not runtime.get(KEY_CLOSED_OUTSIDE_SINCE):
            updates[KEY_CLOSED_OUTSIDE_SINCE] = now.isoformat()
    elif runtime.get(KEY_CLOSED_OUTSIDE_SINCE):
        updates[KEY_CLOSED_OUTSIDE_SINCE] = None
    return updates


def close_delay(
    settings: Mapping[str, Any] | None,
    runtime: Mapping[str, Any],
) -> tuple[float, bool]:
    """(délai en minutes avant fermeture, volet ouvert à la main ?).

    Ouvert par le pilote — ou origine inconnue : le délai de rentrée habituel. Ouvert à la main (vu
    fermé, puis ouvert sans ordre du pilote) : un délai plus long, jamais plus court que le normal.
    """
    normal = _setting(settings, "tondeuse_garage_delai_fermeture", _DEFAULT_CLOSE_DELAY_MINUTES)
    if runtime.get(KEY_OPENED_BY_PILOT) is not False:
        return normal, False
    manual = _setting(
        settings, "tondeuse_garage_delai_fermeture_manuel", DEFAULT_GARAGE_MANUAL_CLOSE_DELAY_MINUTES
    )
    return max(manual, normal), True


def notifiable_state(
    cover_state: Any,
    last_action: Any,
    last_action_at: Any,
    now: datetime,
) -> str | None:
    """L'état du volet à annoncer au téléphone, ou None s'il n'y a rien à annoncer.

    ⚠️ « Utile seulement » : une ouverture ou une fermeture n'est annoncée que si le PILOTE l'a
    ordonnée il y a peu et que l'état lui correspond. Un volet manœuvré à la main (page, appli,
    télécommande) ne notifie pas : on le sait, on est devant.
    """
    cover = str(cover_state or "").strip().lower()
    if last_action == "open_cover":
        coherent = cover in {"open", "opening"}
    elif last_action == "close_cover":
        coherent = cover in {"closed", "closing"}
    else:
        return None
    elapsed = _minutes_since(now, last_action_at)
    if not coherent or elapsed is None or not 0.0 <= elapsed < GARAGE_NOTIFY_WINDOW_MINUTES:
        return None
    return cover


def close_reference(
    runtime: Mapping[str, Any],
    docked_since: Any,
    opened_by_hand: bool,
) -> Any:
    """L'instant depuis lequel on compte le délai avant fermeture.

    Après une rentrée normale : depuis la rentrée. Pour un volet ouvert À LA MAIN : le plus tardif de
    la rentrée et de l'ouverture — on laisse le délai écoulé depuis qu'on l'a ouvert, pas depuis une
    rentrée qui peut dater de plusieurs heures.
    """
    if not opened_by_hand:
        return docked_since
    docked = _instant(docked_since)
    opened = _instant(runtime.get(KEY_OPEN_SINCE))
    if opened is None:
        return docked_since
    if docked is None:
        return runtime.get(KEY_OPEN_SINCE)
    if docked.tzinfo is None and opened.tzinfo is not None:
        docked = docked.replace(tzinfo=opened.tzinfo)
    elif opened.tzinfo is None and docked.tzinfo is not None:
        opened = opened.replace(tzinfo=docked.tzinfo)
    return runtime.get(KEY_OPEN_SINCE) if opened > docked else docked_since


def alert(
    *,
    cover_entity: str | None,
    cover_state: Any,
    position: Any,
    mower_away: bool,
    runtime: Mapping[str, Any],
    settings: Mapping[str, Any] | None,
    now: datetime,
    min_open_position: float = _DEFAULT_MIN_OPEN_POSITION,
) -> dict[str, str] | None:
    """Une anomalie du volet à signaler ? {code, motif}, ou None.

    `mower_away` : la tondeuse est dehors, en retour ou en train de tondre.
    ⚠️ À évaluer APRÈS `reset_updates` : un volet qui a atteint sa cible entre deux cycles n'est pas
    bloqué, même si le temps écoulé dépasse la marge.
    """
    if not cover_entity:
        return None
    cover = str(cover_state or "").strip().lower()
    if mower_away and cover in _UNKNOWN_COVER_STATES:
        silence = _minutes_since(now, runtime.get(KEY_UNAVAILABLE_SINCE))
        if silence is None or silence < GARAGE_UNAVAILABLE_GRACE_MINUTES:
            return None
        return {
            "code": ALERT_UNAVAILABLE,
            "motif": (
                "Le volet ne répond pas alors que la tondeuse est dehors : "
                "elle risque de ne pas pouvoir rentrer."
            ),
        }
    stuck = _stuck_alert(cover_state, position, runtime, settings, now, min_open_position)
    if stuck is not None:
        return stuck
    # ⚠️ Le plus grave et le moins visible : une tondeuse dehors devant un volet fermé. Le pilote ne le
    # rouvre qu'en mode actif, la commande manuelle que pendant sa durée ; en observation ou désactivé,
    # rien d'autre ne le dit. Signalé dans TOUS les modes, sans rien actionner.
    if mower_away and cover not in _UNKNOWN_COVER_STATES and not _open_confirmed(cover, position, min_open_position):
        since = _minutes_since(now, runtime.get(KEY_CLOSED_OUTSIDE_SINCE))
        if since is not None and since >= GARAGE_CLOSED_OUTSIDE_GRACE_MINUTES:
            return {
                "code": ALERT_CLOSED_OUTSIDE,
                "motif": (
                    "Le volet n'est pas ouvert alors que la tondeuse est dehors : "
                    "elle risque de ne pas pouvoir rentrer."
                ),
            }
    return None


def _stuck_alert(
    cover_state: Any,
    position: Any,
    runtime: Mapping[str, Any],
    settings: Mapping[str, Any] | None,
    now: datetime,
    min_open_position: float,
) -> dict[str, str] | None:
    command = runtime.get(KEY_COMMAND)
    if not command or not series_alive(runtime, now, settings):
        return None
    if target_reached(str(command), cover_state, position, min_open_position):
        return None
    attempts = int(_number(runtime.get(KEY_ATTEMPTS), 0.0))
    maximum = _maximum(settings)
    limit = _setting(settings, "tondeuse_garage_delai_max_mouvement", DEFAULT_GARAGE_MAX_TRAVEL_MINUTES)
    elapsed = _minutes_since(now, runtime.get(KEY_SERIES_START) or runtime.get(KEY_COMMAND_AT))
    if attempts >= maximum or (elapsed is not None and elapsed >= limit):
        sens = "d'ouverture" if command == "open_cover" else "de fermeture"
        return {
            "code": ALERT_STUCK,
            "motif": (
                f"Le volet n'a pas atteint sa position après l'ordre {sens} "
                f"({attempts} tentative{'s' if attempts > 1 else ''}) : à vérifier sur place."
            ),
        }
    return None
