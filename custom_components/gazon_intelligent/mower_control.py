"""Décisions sûres du pilote de tondeuse et de son garage facultatif.

Ce module est pur : il ne connaît ni Home Assistant ni ses services. Le coordinateur exécute
éventuellement l'action retournée, uniquement en mode ``actif``. Le mode ``observation`` publie
la même décision sans commander de matériel.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from .mower_control_constants import (
    DEFAULT_MOWER_CONTROL_COMMAND_COOLDOWN_MINUTES,
    DEFAULT_MOWER_CONTROL_MIN_BATTERY,
    DEFAULT_MOWER_CONTROL_MODE,
    DEFAULT_MOWER_START_WINDOW_POLICY,
    DEFAULT_MOWER_GARAGE_CLOSE_AFTER_DOCK,
    DEFAULT_MOWER_GARAGE_CLOSE_DELAY_MINUTES,
    DEFAULT_MOWER_GARAGE_OPEN_BEFORE_START,
    DEFAULT_MOWER_GARAGE_OPEN_FOR_RETURN,
    DEFAULT_MOWER_GARAGE_OPEN_LEAD_MINUTES,
    MOWER_CONTROL_MODES,
    MOWER_START_WINDOW_POLICIES,
)

_OUTSIDE_OPERATIONS = frozenset({"tonte", "mowing", "starting", "zoning", "edgecut"})
_RETURNING_OPERATIONS = frozenset({"returning", "retour_station", "going_home"})
_COVER_OPEN = frozenset({"open"})
_COVER_OPENING = frozenset({"opening"})
_COVER_CLOSED = frozenset({"closed"})
_COVER_CLOSING = frozenset({"closing"})


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _enabled(value: Any, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _instant(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed


def _elapsed(now: datetime, value: Any, minutes: float) -> bool:
    parsed = _instant(value)
    if parsed is None:
        return False
    if parsed.tzinfo is None and now.tzinfo is not None:
        parsed = parsed.replace(tzinfo=now.tzinfo)
    elif parsed.tzinfo is not None and now.tzinfo is None:
        now = now.replace(tzinfo=parsed.tzinfo)
    return now - parsed >= timedelta(minutes=max(0.0, minutes))


def _within_cooldown(now: datetime, value: Any, minutes: float) -> bool:
    """Return true only for a valid, recent timestamp.

    A missing or damaged persisted timestamp must not block a material command forever.
    """
    parsed = _instant(value)
    return parsed is not None and not _elapsed(now, value, minutes)


def _result(
    mode: str,
    state: str,
    reason: str,
    *,
    action: str | None = None,
    runtime_updates: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "mower_control_mode": mode,
        "mower_control_state": state,
        "mower_control_reason": reason,
        "mower_control_pending_action": action,
        "mower_control_runtime_updates": dict(runtime_updates or {}),
    }


def evaluate_mower_control(
    snapshot: Mapping[str, Any],
    *,
    now: datetime,
    mode: str = DEFAULT_MOWER_CONTROL_MODE,
    settings: Mapping[str, Any] | None = None,
    runtime: Mapping[str, Any] | None = None,
    irrigation_active: bool = False,
    cover_entity: str | None = None,
    cover_state: str | None = None,
    bootstrap_complete: bool = False,
) -> dict[str, Any]:
    """Décide d'une unique action, sans jamais l'exécuter.

    Priorités : libérer le garage d'une tondeuse dehors, rappeler une tondeuse si le gazon ne
    permet plus la coupe, refermer après une rentrée prouvée, puis seulement envisager un départ.
    """
    settings = settings or {}
    runtime = runtime or {}
    if mode not in MOWER_CONTROL_MODES:
        mode = DEFAULT_MOWER_CONTROL_MODE
    if mode == "desactive":
        return _result(mode, "desactive", "Pilotage automatique désactivé.")
    if not bootstrap_complete:
        return _result(mode, "demarrage", "Premier cycle d'observation après le démarrage.")

    entity_id = str(snapshot.get("tondeuse_source_entity") or "")
    if not entity_id.startswith("lawn_mower."):
        return _result(mode, "bloque", "Aucune tondeuse unique et valide n'est configurée.")

    operation = str(snapshot.get("mower_operation_state") or "").lower()
    outside = snapshot.get("mower_is_outside") is True
    returning = snapshot.get("mower_is_returning") is True or operation in _RETURNING_OPERATIONS
    mowing = snapshot.get("mower_is_mowing") is True or operation in _OUTSIDE_OPERATIONS
    strong_dock = snapshot.get("mower_dock_signal_fort") is True or operation in {"docked", "charging"}
    cover = str(cover_state or "").lower() if cover_entity else ""
    open_before_start = _enabled(
        settings.get("tondeuse_garage_ouvrir_avant_depart"), DEFAULT_MOWER_GARAGE_OPEN_BEFORE_START
    )
    open_for_return = _enabled(
        settings.get("tondeuse_garage_ouvrir_pour_retour"), DEFAULT_MOWER_GARAGE_OPEN_FOR_RETURN
    )
    close_after_dock = _enabled(
        settings.get("tondeuse_garage_fermer_apres_retour"), DEFAULT_MOWER_GARAGE_CLOSE_AFTER_DOCK
    )

    cooldown = _number(settings.get("tondeuse_pilotage_delai_commandes"))
    if cooldown is None:
        cooldown = DEFAULT_MOWER_CONTROL_COMMAND_COOLDOWN_MINUTES

    def command(action: str, state: str, reason: str) -> dict[str, Any]:
        last_action = runtime.get("last_action")
        if last_action == action and _within_cooldown(now, runtime.get("last_action_at"), cooldown):
            return _result(mode, "temporisation", f"Commande {action} déjà envoyée récemment.")
        return _result(mode, state, reason, action=action)

    # Une tondeuse dehors ne doit jamais trouver son volet fermé, même avant un ordre de retour.
    if cover_entity and (outside or returning) and cover in _COVER_CLOSED | _COVER_CLOSING:
        if open_for_return:
            return command("open_cover", "ouverture_garage", "Ouverture du garage avant le retour de la tondeuse.")
        return _result(mode, "bloque_garage", "Le retour attend l'ouverture manuelle du garage.")

    # On rappelle uniquement quand le GAZON retire son autorisation. Une donnée machine incertaine
    # ne suffit pas : elle pourrait produire des rappels inutiles à chaque indisponibilité réseau.
    if (outside or mowing) and snapshot.get("gazon_permet_tonte") is False and not returning:
        return command("dock", "retour_demande", "Les conditions du gazon ne permettent plus la tonte.")

    close_delay = _number(settings.get("tondeuse_garage_delai_fermeture"))
    if close_delay is None:
        close_delay = DEFAULT_MOWER_GARAGE_CLOSE_DELAY_MINUTES
    runtime_clear: dict[str, Any] = {}
    if cover_entity and strong_dock and snapshot.get("action_possible") is not True:
        docked_since = runtime.get("docked_since")
        updates = {} if docked_since else {"docked_since": now.isoformat()}
        if cover in _COVER_OPEN | _COVER_OPENING:
            if not close_after_dock:
                return _result(mode, "rangee", "Tondeuse rentrée ; fermeture automatique désactivée.", runtime_updates=updates)
            if not docked_since or not _elapsed(now, docked_since, close_delay):
                return _result(
                    mode,
                    "attente_fermeture_garage",
                    "Rentrée confirmée ; délai de sécurité avant fermeture.",
                    runtime_updates=updates,
                )
            return command("close_cover", "fermeture_garage", "Rentrée confirmée ; fermeture du garage.")
        if updates:
            return _result(mode, "rangee", "Tondeuse rentrée au garage.", runtime_updates=updates)
    elif runtime.get("docked_since") is not None:
        # Le signal fort a disparu : l'ancien instant ne doit jamais autoriser une fermeture.
        runtime_clear = {"docked_since": None}

    if snapshot.get("action_possible") is not True:
        return _result(mode, "attente", "La décision de tonte n'autorise pas un départ.", runtime_updates=runtime_clear)

    window_state = str(snapshot.get("mowing_window_state") or "").strip().lower()
    window_policy = str(
        settings.get("tondeuse_creneaux_depart") or DEFAULT_MOWER_START_WINDOW_POLICY
    ).strip().lower()
    if window_policy not in MOWER_START_WINDOW_POLICIES:
        window_policy = DEFAULT_MOWER_START_WINDOW_POLICY
    allowed_windows = {
        "ideal_seulement": {"ideal"},
        "ideal_acceptable": {"ideal", "acceptable"},
        "tout_non_bloque": {"ideal", "acceptable", "discouraged"},
    }[window_policy]
    if window_state not in allowed_windows:
        labels = {
            "ideal": "idéal",
            "acceptable": "acceptable",
            "discouraged": "déconseillé",
            "blocked": "bloqué",
        }
        actuel = labels.get(window_state, "inconnu")
        attendu = {
            "ideal_seulement": "un créneau idéal",
            "ideal_acceptable": "un créneau idéal ou acceptable",
            "tout_non_bloque": "un créneau non bloqué",
        }[window_policy]
        return _result(
            mode,
            "attente_creneau",
            f"Départ réglé sur {attendu} ; le créneau actuel est {actuel}.",
            runtime_updates=runtime_clear,
        )
    if snapshot.get("tondeuse_connectee") is not True or snapshot.get("tondeuse_prete") is not True:
        return _result(mode, "bloque", "La tondeuse n'est pas connectée et prête.", runtime_updates=runtime_clear)
    if snapshot.get("mower_is_docked") is not True:
        return _result(mode, "attente", "La tondeuse n'est pas confirmée à sa station.", runtime_updates=runtime_clear)
    if irrigation_active:
        return _result(mode, "bloque", "Un arrosage est en cours.", runtime_updates=runtime_clear)

    count = _number(snapshot.get("mower_pass_count_today"))
    limit = _number(snapshot.get("mowing_daily_session_limit"))
    if count is None or limit is None or count >= limit:
        return _result(mode, "quota_atteint", "Le nombre maximal de tontes du jour est atteint ou inconnu.", runtime_updates=runtime_clear)

    battery = _number(snapshot.get("mower_battery", snapshot.get("tondeuse_batterie")))
    minimum = _number(settings.get("tondeuse_pilotage_batterie_min"))
    if minimum is None:
        minimum = DEFAULT_MOWER_CONTROL_MIN_BATTERY
    if battery is None or battery < minimum:
        return _result(mode, "attente_batterie", "La batterie n'a pas atteint le seuil de départ.", runtime_updates=runtime_clear)

    if cover_entity:
        if cover in _COVER_CLOSED | _COVER_CLOSING:
            if open_before_start:
                return command("open_cover", "ouverture_garage", "Ouverture du garage avant le départ.")
            return _result(mode, "bloque_garage", "Le départ attend l'ouverture manuelle du garage.")
        if cover in _COVER_OPENING:
            return _result(mode, "attente_garage", "Le garage est en cours d'ouverture.", runtime_updates=runtime_clear)
        if cover not in _COVER_OPEN:
            return _result(mode, "bloque_garage", "L'ouverture du garage n'est pas confirmée.", runtime_updates=runtime_clear)
        opened_at = runtime.get("garage_opened_at")
        lead = _number(settings.get("tondeuse_garage_avance_ouverture"))
        if lead is None:
            lead = DEFAULT_MOWER_GARAGE_OPEN_LEAD_MINUTES
        if not opened_at:
            return _result(
                mode,
                "attente_garage",
                "Garage ouvert ; délai de sécurité avant le départ.",
                runtime_updates={**runtime_clear, "garage_opened_at": now.isoformat()},
            )
        if not _elapsed(now, opened_at, lead):
            return _result(mode, "attente_garage", "Délai d'ouverture du garage en cours.", runtime_updates=runtime_clear)

    return command("start_mowing", "depart_demande", "Toutes les conditions de départ sont réunies.")
