from __future__ import annotations

import asyncio
import importlib
import unittest
from dataclasses import dataclass
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


_ensure_package("custom_components", PACKAGE_DIR.parent)
_ensure_package("custom_components.gazon_intelligent", PACKAGE_DIR)

integration = importlib.import_module("custom_components.gazon_intelligent.migration")


@dataclass
class _FakeEntry:
    entry_id: str = "entry123"
    version: int = 1


class _FakeConfigEntries:
    def __init__(self) -> None:
        self.updated_versions: list[int] = []

    def async_update_entry(self, entry: _FakeEntry, version: int) -> None:
        entry.version = version
        self.updated_versions.append(version)


class _FakeHass:
    def __init__(self) -> None:
        self.config_entries = _FakeConfigEntries()


class MigrationRuntimeTests(unittest.TestCase):
    def test_async_migrate_entry_updates_version_and_cleans(self) -> None:
        calls: list[tuple[object, str]] = []
        align_calls: list[tuple[object, str]] = []

        async def fake_cleanup(hass, entry_id, entity_registry=None):
            calls.append((hass, entry_id))
            return ["sensor.gazon_intelligent_score_tonte"]

        async def fake_align(hass, entry_id, entity_registry=None):
            align_calls.append((hass, entry_id))
            return [("sensor.old", "sensor.new")]

        original = integration.async_cleanup_obsolete_entities
        original_align = integration.async_align_entity_ids
        integration.async_cleanup_obsolete_entities = fake_cleanup
        integration.async_align_entity_ids = fake_align
        try:
            hass = _FakeHass()
            entry = _FakeEntry()
            result = asyncio.run(integration.async_migrate_entry(hass, entry))
        finally:
            integration.async_cleanup_obsolete_entities = original
            integration.async_align_entity_ids = original_align

        self.assertTrue(result)
        self.assertEqual(entry.version, 3)
        self.assertEqual(calls, [(hass, "entry123")])
        self.assertEqual(align_calls, [(hass, "entry123")])
        self.assertEqual(hass.config_entries.updated_versions, [3])
