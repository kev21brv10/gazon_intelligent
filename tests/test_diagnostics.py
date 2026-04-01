from __future__ import annotations

import asyncio
import unittest
from dataclasses import dataclass, field
from pathlib import Path
import sys
import types


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


def _install_homeassistant_stubs() -> None:
    def ensure_module(name: str) -> types.ModuleType:
        module = sys.modules.get(name)
        if module is None:
            module = types.ModuleType(name)
            sys.modules[name] = module
        return module

    ensure_module("homeassistant")

    config_entries_mod = ensure_module("homeassistant.config_entries")
    if not hasattr(config_entries_mod, "ConfigEntry"):
        @dataclass
        class ConfigEntry:
            entry_id: str = "entry123"
            title: str = "Gazon Intelligent"
            version: int = 2
            data: dict[str, object] = field(default_factory=dict)
            options: dict[str, object] = field(default_factory=dict)

        config_entries_mod.ConfigEntry = ConfigEntry

    core_mod = ensure_module("homeassistant.core")
    if not hasattr(core_mod, "HomeAssistant"):
        @dataclass
        class HomeAssistant:
            data: dict[str, object] = field(default_factory=dict)

        core_mod.HomeAssistant = HomeAssistant


_ensure_package("custom_components", PACKAGE_DIR.parent)
_ensure_package("custom_components.gazon_intelligent", PACKAGE_DIR)
_install_homeassistant_stubs()

from custom_components.gazon_intelligent.const import DOMAIN
from custom_components.gazon_intelligent import diagnostics


@dataclass
class _FakeEntry:
    entry_id: str = "entry123"
    title: str = "Gazon Intelligent"
    version: int = 2
    data: dict[str, object] = field(default_factory=dict)
    options: dict[str, object] = field(default_factory=dict)


@dataclass
class _FakeCoordinator:
    entry: _FakeEntry
    data: dict[str, object] = field(default_factory=dict)
    last_result: object | None = None
    history: list[dict[str, object]] = field(default_factory=list)
    memory: dict[str, object] = field(default_factory=dict)
    products: dict[str, dict[str, object]] = field(default_factory=dict)
    soil_balance: dict[str, object] = field(default_factory=dict)
    _loaded: bool = True
    auto_irrigation_enabled: bool = True
    mode: str = "Sursemis"
    date_action: object | None = None


class DiagnosticsTests(unittest.TestCase):
    def test_config_entry_diagnostics_uses_current_snapshot(self) -> None:
        entry = _FakeEntry(
            data={
                "zone_1": "switch.zone_1",
                "debit_zone_1": 10.0,
                "type_sol": "limoneux",
            },
            options={"capteur_temperature": "sensor.temp"},
        )
        snapshot = {
            "mode": "Sursemis",
            "phase_active": "Sursemis",
            "phase_dominante": "Sursemis",
            "sous_phase": "Enracinement",
            "objectif_mm": 0.0,
            "arrosage_recommande": False,
            "type_arrosage": "personnalise",
            "niveau_action": "surveiller",
            "fenetre_optimale": "attendre",
            "risque_gazon": "modere",
            "tonte_autorisee": False,
            "tonte_statut": "interdite",
            "conseil_principal": "sol déjà humide",
            "action_recommandee": "Surveille l'humidité",
            "action_a_eviter": "Multiplier les petits cycles.",
            "raison_decision": "sol déjà humide",
            "assistant": {"action": "aucune_action", "moment": "attendre"},
        }
        coordinator = _FakeCoordinator(
            entry=entry,
            data=snapshot,
            history=[
                {
                    "date": "2026-03-23",
                    "type": "Sursemis",
                    "summary": "Dernier arrosage 0.5 mm",
                    "source": "zone_session",
                    "objectif_mm": 0.5,
                    "total_mm": 0.5,
                }
            ],
            memory={
                "historique_total": 1,
                "derniere_phase_active": "Sursemis",
                "dernier_arrosage": "2026-03-23",
                "feedback_observation": "ok",
                "auto_irrigation_enabled": True,
            },
            products={"prod_1": {"nom": "Test"}},
            soil_balance={"hydric_balance_level": "équilibré"},
        )
        hass = types.SimpleNamespace(data={DOMAIN: {entry.entry_id: coordinator}})

        payload = asyncio.run(diagnostics.async_get_config_entry_diagnostics(hass, entry))

        self.assertEqual(payload["config_entry"]["entry_id"], "entry123")
        self.assertEqual(payload["config_entry"]["title"], "Gazon Intelligent")
        self.assertEqual(payload["config_entry"]["data"]["zone_1"], "switch.zone_1")
        self.assertEqual(payload["runtime"]["mode"], "Sursemis")
        self.assertEqual(payload["runtime"]["history_count"], 1)
        self.assertEqual(payload["runtime"]["products_count"], 1)
        self.assertEqual(payload["runtime"]["memory"]["feedback_observation"], "ok")
        self.assertEqual(payload["decision"]["assistant"]["action"], "aucune_action")
        self.assertEqual(payload["history_tail"][0]["summary"], "Dernier arrosage 0.5 mm")

    def test_config_entry_diagnostics_falls_back_to_last_result(self) -> None:
        entry = _FakeEntry()
        snapshot = {
            "mode": "Normal",
            "phase_active": "Normal",
            "objective_mm": 0.0,
            "objectif_mm": 0.0,
        }

        coordinator = _FakeCoordinator(
            entry=entry,
            data={},
            last_result=types.SimpleNamespace(to_snapshot=lambda: snapshot),
        )
        hass = types.SimpleNamespace(data={DOMAIN: {entry.entry_id: coordinator}})

        payload = asyncio.run(diagnostics.async_get_config_entry_diagnostics(hass, entry))

        self.assertEqual(payload["decision"]["mode"], "Normal")
        self.assertEqual(payload["decision"]["phase_active"], "Normal")


if __name__ == "__main__":
    unittest.main()
