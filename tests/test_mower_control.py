from __future__ import annotations

import importlib
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT / "custom_components" / "gazon_intelligent"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ensure_package(name: str, path: Path) -> None:
    if name in sys.modules:
        return
    module = types.ModuleType(name)
    module.__path__ = [str(path)]  # type: ignore[attr-defined]
    sys.modules[name] = module


_ensure_package("custom_components", PACKAGE_DIR.parent)
_ensure_package("custom_components.gazon_intelligent", PACKAGE_DIR)
evaluate_mower_control = importlib.import_module(
    "custom_components.gazon_intelligent.mower_control"
).evaluate_mower_control


NOW = datetime(2026, 9, 19, 10, 0, tzinfo=timezone.utc)


def ready(**updates):
    snapshot = {
        "tondeuse_source_entity": "lawn_mower.esperance_jr",
        "tondeuse_connectee": True,
        "tondeuse_prete": True,
        "mower_is_docked": True,
        "mower_is_outside": False,
        "mower_is_mowing": False,
        "mower_is_returning": False,
        "mower_operation_state": "docked",
        "mower_dock_signal_fort": True,
        "mower_battery": 100,
        "mower_pass_count_today": 0,
        "mowing_daily_session_limit": 2,
        "mowing_window_state": "ideal",
        "gazon_permet_tonte": True,
        "action_possible": True,
    }
    snapshot.update(updates)
    return snapshot


def decide(snapshot=None, **kwargs):
    return evaluate_mower_control(
        snapshot or ready(),
        now=NOW,
        mode=kwargs.pop("mode", "actif"),
        bootstrap_complete=kwargs.pop("bootstrap_complete", True),
        **kwargs,
    )


def test_disabled_and_startup_guard_never_propose_a_command():
    assert decide(mode="desactive")["mower_control_pending_action"] is None
    assert decide(bootstrap_complete=False)["mower_control_state"] == "demarrage"


def test_ready_mower_starts_without_optional_garage():
    result = decide()
    assert result["mower_control_pending_action"] == "start_mowing"


def test_start_window_policy_filters_departures_without_affecting_hard_blocks():
    ideal = decide(ready(mowing_window_state="ideal"))
    assert ideal["mower_control_pending_action"] == "start_mowing"

    for window in ("acceptable", "discouraged", "blocked", None):
        result = decide(ready(mowing_window_state=window))
        assert result["mower_control_pending_action"] is None
        assert result["mower_control_state"] == "attente_creneau"

    acceptable = decide(
        ready(mowing_window_state="acceptable"),
        settings={"tondeuse_creneaux_depart": "ideal_acceptable"},
    )
    assert acceptable["mower_control_pending_action"] == "start_mowing"

    discouraged = decide(
        ready(mowing_window_state="discouraged"),
        settings={"tondeuse_creneaux_depart": "tout_non_bloque"},
    )
    assert discouraged["mower_control_pending_action"] == "start_mowing"

    blocked = decide(
        ready(mowing_window_state="blocked"),
        settings={"tondeuse_creneaux_depart": "tout_non_bloque"},
    )
    assert blocked["mower_control_pending_action"] is None


def test_invalid_start_window_policy_falls_back_to_ideal_only():
    result = decide(
        ready(mowing_window_state="acceptable"),
        settings={"tondeuse_creneaux_depart": "nimporte_quoi"},
    )
    assert result["mower_control_state"] == "attente_creneau"


def test_window_policy_never_prevents_recall_of_mower_already_outside():
    outside = ready(
        mowing_window_state="blocked",
        mower_is_docked=False,
        mower_is_outside=True,
        mower_is_mowing=True,
        mower_operation_state="tonte",
        gazon_permet_tonte=False,
        action_possible=False,
    )
    assert decide(outside)["mower_control_pending_action"] == "dock"


def test_every_start_guard_blocks_independently():
    cases = (
        ({"action_possible": False}, {}, "attente"),
        ({"tondeuse_connectee": False}, {}, "bloque"),
        ({"tondeuse_prete": False}, {}, "bloque"),
        ({"mower_is_docked": False}, {}, "attente"),
        ({"mower_battery": None}, {}, "attente_batterie"),
        ({"mower_battery": 79}, {"settings": {"tondeuse_pilotage_batterie_min": 80}}, "attente_batterie"),
        ({"mower_pass_count_today": 2}, {}, "quota_atteint"),
        ({}, {"irrigation_active": True}, "bloque"),
    )
    for changes, options, state in cases:
        result = decide(ready(**changes), **options)
        assert result["mower_control_pending_action"] is None
        assert result["mower_control_state"] == state


def test_duplicate_command_is_blocked_during_cooldown():
    result = decide(runtime={"last_action": "start_mowing", "last_action_at": (NOW - timedelta(minutes=2)).isoformat()})
    assert result["mower_control_pending_action"] is None
    assert result["mower_control_state"] == "temporisation"

    shorter = decide(
        settings={"tondeuse_pilotage_delai_commandes": 1},
        runtime={"last_action": "start_mowing", "last_action_at": (NOW - timedelta(minutes=2)).isoformat()},
    )
    assert shorter["mower_control_pending_action"] == "start_mowing"


def test_missing_or_invalid_command_timestamp_does_not_block_forever():
    for last_action_at in (None, "date-invalide"):
        result = decide(runtime={"last_action": "start_mowing", "last_action_at": last_action_at})
        assert result["mower_control_pending_action"] == "start_mowing"


def test_mower_is_docked_only_when_lawn_permission_is_withdrawn():
    outside = ready(
        mower_is_docked=False,
        mower_is_outside=True,
        mower_is_mowing=True,
        mower_operation_state="tonte",
        gazon_permet_tonte=False,
        action_possible=False,
    )
    assert decide(outside)["mower_control_pending_action"] == "dock"
    outside["gazon_permet_tonte"] = True
    outside["action_possible"] = False
    assert decide(outside)["mower_control_pending_action"] is None


def test_garage_is_optional_and_closed_garage_opens_before_start():
    assert decide()["mower_control_pending_action"] == "start_mowing"
    result = decide(cover_entity="cover.garage_tondeuse", cover_state="closed")
    assert result["mower_control_pending_action"] == "open_cover"


def test_missing_or_invalid_mower_entity_blocks_everything():
    for entity in ("", "sensor.esperance_jr", "lawn_mower_esperance_jr"):
        result = decide(ready(tondeuse_source_entity=entity))
        assert result["mower_control_state"] == "bloque"
        assert result["mower_control_pending_action"] is None


def test_outside_flag_alone_reopens_garage_even_without_a_recognized_operation_state():
    # `mower_is_outside` doit compter même quand `mower_operation_state` (ex. valeur brute
    # inattendue du cloud constructeur) ne correspond à aucun des libellés connus.
    snapshot = ready(
        mower_is_docked=False,
        mower_is_outside=True,
        mower_is_returning=False,
        mower_is_mowing=False,
        mower_operation_state="idle",
    )
    result = decide(snapshot, cover_entity="cover.garage_tondeuse", cover_state="closed")
    assert result["mower_control_pending_action"] == "open_cover"


def test_returning_flag_alone_reopens_garage_even_without_a_recognized_operation_state():
    snapshot = ready(
        mower_is_docked=False,
        mower_is_outside=False,
        mower_is_returning=True,
        mower_is_mowing=False,
        mower_operation_state="idle",
    )
    result = decide(snapshot, cover_entity="cover.garage_tondeuse", cover_state="closed")
    assert result["mower_control_pending_action"] == "open_cover"


def test_mowing_flag_alone_triggers_recall_even_without_a_recognized_operation_state():
    snapshot = ready(
        mower_is_docked=False,
        mower_is_outside=False,
        mower_is_returning=False,
        mower_is_mowing=True,
        mower_operation_state="idle",
        gazon_permet_tonte=False,
        action_possible=False,
    )
    assert decide(snapshot)["mower_control_pending_action"] == "dock"


def test_departure_waits_while_garage_is_still_opening():
    result = decide(cover_entity="cover.garage_tondeuse", cover_state="opening")
    assert result["mower_control_state"] == "attente_garage"
    assert result["mower_control_pending_action"] is None


def test_each_garage_automation_can_be_disabled_independently():
    manual_start = decide(
        cover_entity="cover.garage_tondeuse",
        cover_state="closed",
        settings={"tondeuse_garage_ouvrir_avant_depart": False},
    )
    assert manual_start["mower_control_state"] == "bloque_garage"
    assert manual_start["mower_control_pending_action"] is None

    outside = ready(mower_is_docked=False, mower_is_outside=True, mower_operation_state="returning")
    manual_return = decide(
        outside,
        cover_entity="cover.garage_tondeuse",
        cover_state="closed",
        settings={"tondeuse_garage_ouvrir_pour_retour": False},
    )
    assert manual_return["mower_control_state"] == "bloque_garage"
    assert manual_return["mower_control_pending_action"] is None

    docked = decide(
        ready(action_possible=False),
        cover_entity="cover.garage_tondeuse",
        cover_state="open",
        settings={"tondeuse_garage_fermer_apres_retour": False},
        runtime={"docked_since": (NOW - timedelta(minutes=5)).isoformat()},
    )
    assert docked["mower_control_state"] == "rangee"
    assert docked["mower_control_pending_action"] is None


def test_open_garage_waits_then_allows_start():
    first = decide(cover_entity="cover.garage_tondeuse", cover_state="open")
    assert first["mower_control_state"] == "attente_garage"
    opened_at = (NOW - timedelta(minutes=3)).isoformat()
    result = decide(
        cover_entity="cover.garage_tondeuse",
        cover_state="open",
        runtime={"garage_opened_at": opened_at},
    )
    assert result["mower_control_pending_action"] == "start_mowing"

    longer = decide(
        cover_entity="cover.garage_tondeuse",
        cover_state="open",
        settings={"tondeuse_garage_avance_ouverture": 5},
        runtime={"garage_opened_at": opened_at},
    )
    assert longer["mower_control_state"] == "attente_garage"
    assert longer["mower_control_pending_action"] is None


def test_unknown_garage_never_allows_start():
    result = decide(cover_entity="cover.garage_tondeuse", cover_state="unknown")
    assert result["mower_control_state"] == "bloque_garage"
    assert result["mower_control_pending_action"] is None


def test_outside_mower_reopens_garage_before_returning():
    snapshot = ready(mower_is_docked=False, mower_is_outside=True, mower_operation_state="returning")
    result = decide(snapshot, cover_entity="cover.garage_tondeuse", cover_state="closed")
    assert result["mower_control_pending_action"] == "open_cover"


def test_garage_closes_only_after_strong_dock_signal_and_delay():
    weak = ready(mower_dock_signal_fort=False, mower_operation_state="idle", action_possible=False)
    result = decide(
        weak,
        cover_entity="cover.garage_tondeuse",
        cover_state="open",
        runtime={"docked_since": (NOW - timedelta(minutes=5)).isoformat()},
    )
    assert result["mower_control_pending_action"] is None
    strong = ready(action_possible=False)
    result = decide(
        strong,
        cover_entity="cover.garage_tondeuse",
        cover_state="open",
        settings={"tondeuse_garage_delai_fermeture": 2},
        runtime={"docked_since": (NOW - timedelta(minutes=3)).isoformat()},
    )
    assert result["mower_control_pending_action"] == "close_cover"

    delayed = decide(
        strong,
        cover_entity="cover.garage_tondeuse",
        cover_state="open",
        settings={"tondeuse_garage_delai_fermeture": 10},
        runtime={"docked_since": (NOW - timedelta(minutes=3)).isoformat()},
    )
    assert delayed["mower_control_state"] == "attente_fermeture_garage"


def test_docked_with_closed_garage_and_stale_docked_since_does_not_crash():
    # Tondeuse déjà à quai depuis un cycle précédent (docked_since renseigné), garage déjà
    # refermé, gazon qui ne réautorise pas de départ : aucune décision de garage à prendre, la
    # fonction doit simplement continuer vers les gardes de départ, jamais planter.
    snapshot = ready(action_possible=False)
    result = decide(
        snapshot,
        cover_entity="cover.garage_tondeuse",
        cover_state="closed",
        runtime={"docked_since": (NOW - timedelta(minutes=5)).isoformat()},
    )
    assert result["mower_control_state"] == "attente"
    assert result["mower_control_pending_action"] is None
    assert result["mower_control_runtime_updates"] == {}
