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
    DEFAULT_MOWER_GARAGE_MIN_OPEN_POSITION,
    MOWER_CONTROL_MODES,
    MOWER_MANAGED_START_TIMEOUT_MINUTES,
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
    cover_position: Any = None,
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
    completion_state = str(snapshot.get("mower_job_completion_state") or "").lower()
    progress = _number(snapshot.get("mower_job_progress_pct"))

    # Un départ envoyé par l'intégration ouvre un seul cycle autonome. Une fois la machine
    # sortie, ses retours batterie et ses redéparts appartiennent au constructeur : nous ne
    # renvoyons jamais `start_mowing` à chaque recharge. Seul un `dock` demandé par CE pilote
    # crée une dette de reprise, acquittée par une unique commande quand les gardes reviennent.
    runtime_updates: dict[str, Any] = {}
    start_pending = runtime.get("managed_start_pending") is True
    cycle_active = runtime.get("managed_cycle_active") is True
    resume_required = runtime.get("resume_required") is True
    managed_job_seen_incomplete = runtime.get("managed_job_seen_incomplete") is True
    managed_job_id = runtime.get("managed_job_id")
    observed_job_id = snapshot.get("mower_job_followed_id") or snapshot.get("mower_job_id")
    # ⚠️ Un signal FRAIS est exigé (0.97.25, signalé en relecture de la PR #52). `mower_job_progress_pct`
    # peut encore afficher le pourcentage d'un ANCIEN travail (interrompu, jamais remis à zéro)
    # au moment même où la commande est envoyée : sans comparaison à une référence, n'importe
    # quelle valeur sous 100 % suffisait à faire croire un départ confirmé alors que la tondeuse
    # n'avait jamais quitté sa station — le cycle managed_cycle_active s'armait pour rien, et
    # l'intégration ne relançait plus jamais la tondeuse.
    start_baseline_job_id = runtime.get("managed_start_baseline_job_id")
    start_baseline_progress = _number(runtime.get("managed_start_baseline_progress"))
    fresh_job = observed_job_id not in (None, "") and str(observed_job_id) != str(
        start_baseline_job_id or ""
    )
    fresh_progress = (
        progress is not None
        and start_baseline_progress is not None
        and progress > start_baseline_progress
    )
    observed_activity = (
        outside
        or mowing
        or completion_state in {"en_cours", "en_pause"}
        or fresh_job
        or fresh_progress
    )
    if start_pending and observed_activity:
        start_pending = False
        cycle_active = True
        runtime_updates.update(
            {
                "managed_start_pending": False,
                "managed_cycle_active": True,
                "managed_start_baseline_job_id": None,
                "managed_start_baseline_progress": None,
                "managed_start_requested_at": None,
            }
        )
    if cycle_active and progress is not None and progress < 100.0:
        managed_job_seen_incomplete = True
        runtime_updates["managed_job_seen_incomplete"] = True
        if observed_job_id not in (None, ""):
            managed_job_id = str(observed_job_id)
            runtime_updates["managed_job_id"] = managed_job_id

    cycle_just_completed = (
        cycle_active
        and (
            completion_state == "termine"
            or (
                managed_job_seen_incomplete
                and progress is not None
                and progress >= 100.0
                and (
                    managed_job_id in (None, "")
                    or observed_job_id in (None, "")
                    or str(observed_job_id) == str(managed_job_id)
                )
            )
        )
        and not outside
        and not mowing
        and not returning
    )
    if cycle_just_completed:
        start_pending = False
        cycle_active = False
        resume_required = False
        runtime_updates.update(
            {
                "managed_start_pending": False,
                "managed_cycle_active": False,
                "resume_required": False,
                "resume_reason": None,
                "resume_requested_at": None,
                "managed_job_seen_incomplete": False,
                "managed_job_id": None,
                "managed_start_baseline_job_id": None,
                "managed_start_baseline_progress": None,
                "managed_start_requested_at": None,
            }
        )

    effective_runtime = dict(runtime)
    effective_runtime.update(runtime_updates)

    def result(
        state: str,
        reason: str,
        *,
        action: str | None = None,
        updates: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return _result(
            mode,
            state,
            reason,
            action=action,
            runtime_updates={**runtime_updates, **dict(updates or {})},
        )

    cover = str(cover_state or "").lower() if cover_entity else ""
    position = _number(cover_position) if cover_entity else None
    minimum_position = _number(settings.get("tondeuse_garage_ouverture_min"))
    if minimum_position is None:
        minimum_position = DEFAULT_MOWER_GARAGE_MIN_OPEN_POSITION
    minimum_position = min(100.0, max(0.0, minimum_position))
    position_insuffisante = (
        cover in _COVER_OPEN and position is not None and position < minimum_position
    )
    ouverture_confirmee = cover in _COVER_OPEN and not position_insuffisante
    ouverture_a_completer = cover in _COVER_CLOSED | _COVER_CLOSING or position_insuffisante
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
        last_action = effective_runtime.get("last_action")
        if last_action == action and _within_cooldown(
            now, effective_runtime.get("last_action_at"), cooldown
        ):
            return result("temporisation", f"Commande {action} déjà envoyée récemment.")
        return result(state, reason, action=action)

    # Une tondeuse dehors ne doit jamais trouver son volet fermé, même avant un ordre de retour.
    if cover_entity and (outside or returning) and ouverture_a_completer:
        if open_for_return:
            raison = (
                f"Ouverture du garage à compléter avant le retour ({position:g} %, minimum {minimum_position:g} %)."
                if position_insuffisante
                else "Ouverture du garage avant le retour de la tondeuse."
            )
            return command("open_cover", "ouverture_garage", raison)
        return result("bloque_garage", "Le retour attend l'ouverture manuelle du garage.")

    # On rappelle uniquement quand le GAZON retire son autorisation. Une donnée machine incertaine
    # ne suffit pas : elle pourrait produire des rappels inutiles à chaque indisponibilité réseau.
    if (outside or mowing) and snapshot.get("gazon_permet_tonte") is False and not returning:
        return command("dock", "retour_demande", "Les conditions du gazon ne permettent plus la tonte.")

    # Tant que le départ accepté n'a pas encore été observé, ne rien répéter et garder un garage
    # éventuel disponible. Dès que le cycle est actif, les retours batterie et les redéparts sont
    # ceux du constructeur : fermer le volet ou renvoyer start_mowing casserait cette autonomie.
    # Le cas `resume_required` passe volontairement plus bas : l'intégration a alors interrompu
    # elle-même le cycle et reprend la responsabilité jusqu'à son unique commande de reprise.
    if start_pending:
        if _elapsed(now, runtime.get("managed_start_requested_at"), MOWER_MANAGED_START_TIMEOUT_MINUTES):
            return result(
                "depart_non_confirme",
                "Départ envoyé mais aucun signal de sortie confirmée après un long délai : "
                "à vérifier sur la tondeuse.",
            )
        return result(
            "depart_envoye",
            "Départ envoyé ; attente de la sortie effective de la tondeuse.",
        )
    if cycle_active and not resume_required:
        return result(
            "cycle_autonome",
            (
                "Cycle autonome en cours : la tondeuse gère seule ses recharges et ses redéparts."
                if strong_dock
                else "Cycle autonome en cours sous la responsabilité de la tondeuse."
            ),
        )

    close_delay = _number(settings.get("tondeuse_garage_delai_fermeture"))
    if close_delay is None:
        close_delay = DEFAULT_MOWER_GARAGE_CLOSE_DELAY_MINUTES
    runtime_clear: dict[str, Any] = {}
    if cover_entity and strong_dock and snapshot.get("action_possible") is not True:
        docked_since = runtime.get("docked_since")
        updates = {} if docked_since else {"docked_since": now.isoformat()}
        if cover in _COVER_OPEN | _COVER_OPENING:
            if not close_after_dock:
                return result("rangee", "Tondeuse rentrée ; fermeture automatique désactivée.", updates=updates)
            if not docked_since or not _elapsed(now, docked_since, close_delay):
                return result(
                    "attente_fermeture_garage",
                    "Rentrée confirmée ; délai de sécurité avant fermeture.",
                    updates=updates,
                )
            return command("close_cover", "fermeture_garage", "Rentrée confirmée ; fermeture du garage.")
        if updates:
            return result("rangee", "Tondeuse rentrée au garage.", updates=updates)
    elif runtime.get("docked_since") is not None:
        # Le signal fort a disparu : l'ancien instant ne doit jamais autoriser une fermeture.
        runtime_clear = {"docked_since": None}

    if snapshot.get("action_possible") is not True:
        if resume_required:
            return result(
                "reprise_attente",
                "Reprise attendue : les conditions de tonte ne sont pas encore revenues.",
                updates=runtime_clear,
            )
        return result(
            "attente",
            "La décision de tonte n'autorise pas un départ.",
            updates=runtime_clear,
        )

    if cycle_just_completed:
        return result(
            "cycle_termine",
            "Le cycle lancé par Gazon Intelligent est terminé.",
            updates=runtime_clear,
        )

    # Une reprise n'est pas un nouveau travail : elle ignore donc le choix de créneau et le quota
    # quotidien. Les gardes matérielles et de sécurité restent, elles, obligatoires.
    if resume_required:
        if snapshot.get("tondeuse_connectee") is not True or snapshot.get("tondeuse_prete") is not True:
            return result(
                "reprise_attente",
                "Reprise attendue : la tondeuse n'est pas connectée et prête.",
                updates=runtime_clear,
            )
        if snapshot.get("mower_is_docked") is not True:
            return result(
                "reprise_attente",
                "Reprise attendue : le retour à la station n'est pas encore confirmé.",
                updates=runtime_clear,
            )
        if irrigation_active:
            return result(
                "reprise_attente",
                "Reprise attendue : un arrosage est en cours.",
                updates=runtime_clear,
            )

        battery = _number(snapshot.get("mower_battery", snapshot.get("tondeuse_batterie")))
        minimum = _number(settings.get("tondeuse_pilotage_batterie_min"))
        if minimum is None:
            minimum = DEFAULT_MOWER_CONTROL_MIN_BATTERY
        if battery is None or battery < minimum:
            return result(
                "reprise_attente_batterie",
                "Reprise attendue : la batterie n'a pas atteint le seuil choisi.",
                updates=runtime_clear,
            )

        if cover_entity:
            if ouverture_a_completer:
                if open_before_start:
                    return command(
                        "open_cover",
                        "ouverture_garage_reprise",
                        "Ouverture du garage avant la reprise interrompue par Gazon Intelligent.",
                    )
                return result(
                    "bloque_garage",
                    "La reprise attend l'ouverture manuelle du garage.",
                    updates=runtime_clear,
                )
            if cover in _COVER_OPENING:
                return result(
                    "attente_garage",
                    "Le garage est en cours d'ouverture avant la reprise.",
                    updates=runtime_clear,
                )
            if not ouverture_confirmee:
                return result(
                    "bloque_garage",
                    "L'ouverture du garage n'est pas confirmée pour la reprise.",
                    updates=runtime_clear,
                )
            opened_at = effective_runtime.get("garage_opened_at")
            lead = _number(settings.get("tondeuse_garage_avance_ouverture"))
            if lead is None:
                lead = DEFAULT_MOWER_GARAGE_OPEN_LEAD_MINUTES
            if not opened_at:
                return result(
                    "attente_garage",
                    "Garage ouvert ; délai de sécurité avant la reprise.",
                    updates={**runtime_clear, "garage_opened_at": now.isoformat()},
                )
            if not _elapsed(now, opened_at, lead):
                return result(
                    "attente_garage",
                    "Délai d'ouverture du garage en cours avant la reprise.",
                    updates=runtime_clear,
                )

        return command(
            "start_mowing",
            "reprise_demandee",
            "Reprise unique après le retour demandé par Gazon Intelligent.",
        )

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
        return result(
            "attente_creneau",
            f"Départ réglé sur {attendu} ; le créneau actuel est {actuel}.",
            updates=runtime_clear,
        )
    if snapshot.get("tondeuse_connectee") is not True or snapshot.get("tondeuse_prete") is not True:
        return result("bloque", "La tondeuse n'est pas connectée et prête.", updates=runtime_clear)
    if snapshot.get("mower_is_docked") is not True:
        return result("attente", "La tondeuse n'est pas confirmée à sa station.", updates=runtime_clear)
    if irrigation_active:
        return result("bloque", "Un arrosage est en cours.", updates=runtime_clear)

    count = _number(snapshot.get("mower_pass_count_today"))
    limit = _number(snapshot.get("mowing_daily_session_limit"))
    if count is None or limit is None or count >= limit:
        return result("quota_atteint", "Le nombre maximal de tontes du jour est atteint ou inconnu.", updates=runtime_clear)

    battery = _number(snapshot.get("mower_battery", snapshot.get("tondeuse_batterie")))
    minimum = _number(settings.get("tondeuse_pilotage_batterie_min"))
    if minimum is None:
        minimum = DEFAULT_MOWER_CONTROL_MIN_BATTERY
    if battery is None or battery < minimum:
        return result("attente_batterie", "La batterie n'a pas atteint le seuil de départ.", updates=runtime_clear)

    if cover_entity:
        if ouverture_a_completer:
            if open_before_start:
                raison = (
                    f"Ouverture du garage à compléter ({position:g} %, minimum {minimum_position:g} %)."
                    if position_insuffisante
                    else "Ouverture du garage avant le départ."
                )
                return command("open_cover", "ouverture_garage", raison)
            return result("bloque_garage", "Le départ attend l'ouverture manuelle du garage.")
        if cover in _COVER_OPENING:
            return result("attente_garage", "Le garage est en cours d'ouverture.", updates=runtime_clear)
        if not ouverture_confirmee:
            return result("bloque_garage", "L'ouverture du garage n'est pas confirmée.", updates=runtime_clear)
        opened_at = effective_runtime.get("garage_opened_at")
        lead = _number(settings.get("tondeuse_garage_avance_ouverture"))
        if lead is None:
            lead = DEFAULT_MOWER_GARAGE_OPEN_LEAD_MINUTES
        if not opened_at:
            return result(
                "attente_garage",
                "Garage ouvert ; délai de sécurité avant le départ.",
                updates={**runtime_clear, "garage_opened_at": now.isoformat()},
            )
        if not _elapsed(now, opened_at, lead):
            return result("attente_garage", "Délai d'ouverture du garage en cours.", updates=runtime_clear)

    return command("start_mowing", "depart_demande", "Toutes les conditions de départ sont réunies.")
