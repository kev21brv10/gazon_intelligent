from __future__ import annotations

import unittest
from importlib import util
from pathlib import Path
import sys


def _load_entity_migration_module():
    module_path = (
        Path(__file__).resolve().parents[1]
        / "custom_components"
        / "gazon_intelligent"
        / "entity_migration.py"
    )
    spec = util.spec_from_file_location("gazon_intelligent_entity_migration", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Impossible de charger {module_path}")
    module = util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


entity_migration = _load_entity_migration_module()


class _FakeEntity:
    def __init__(self, entity_id: str, unique_id: str, config_entry_id: str) -> None:
        self.entity_id = entity_id
        self.unique_id = unique_id
        self.config_entry_id = config_entry_id


class _FakeEntityRegistry:
    def __init__(self, entities: list[_FakeEntity]) -> None:
        self.entities = {entity.entity_id: entity for entity in entities}
        self.removed: list[str] = []

    def async_remove(self, entity_id: str) -> None:
        self.removed.append(entity_id)
        self.entities.pop(entity_id, None)


class EntityMigrationTests(unittest.TestCase):
    def test_current_entities_are_not_obsolete(self) -> None:
        self.assertFalse(
            entity_migration.is_obsolete_entity_unique_id("entry123_mode", "entry123")
        )
        self.assertFalse(
            entity_migration.is_obsolete_entity_unique_id("entry123_phase_active", "entry123")
        )

    def test_legacy_entities_are_marked_obsolete(self) -> None:
        self.assertTrue(
            entity_migration.is_obsolete_entity_unique_id("entry123_bilan_hydrique", "entry123")
        )
        self.assertTrue(
            entity_migration.is_obsolete_entity_unique_id("entry123_score_tonte", "entry123")
        )
        self.assertTrue(
            entity_migration.is_obsolete_entity_unique_id("entry123_type_sol", "entry123")
        )

    def test_cleanup_obsolete_entities_removes_only_old_entries(self) -> None:
        registry = _FakeEntityRegistry(
            [
                _FakeEntity("sensor.gazon_intelligent_phase_active", "entry123_phase_active", "entry123"),
                _FakeEntity("sensor.gazon_intelligent_bilan_hydrique", "entry123_bilan_hydrique", "entry123"),
                _FakeEntity("sensor.gazon_intelligent_score_tonte", "entry123_score_tonte", "entry123"),
                _FakeEntity("sensor.other", "other_entry_mode", "other_entry"),
            ]
        )

        removed = self._run_cleanup(registry)

        self.assertEqual(
            removed,
            ["sensor.gazon_intelligent_bilan_hydrique", "sensor.gazon_intelligent_score_tonte"],
        )
        self.assertIn("sensor.gazon_intelligent_phase_active", registry.entities)
        self.assertNotIn("sensor.gazon_intelligent_bilan_hydrique", registry.entities)
        self.assertNotIn("sensor.gazon_intelligent_score_tonte", registry.entities)

    def _run_cleanup(self, registry: _FakeEntityRegistry) -> list[str]:
        import asyncio

        return asyncio.run(
            entity_migration.async_cleanup_obsolete_entities(
                hass=None,
                entry_id="entry123",
                entity_registry=registry,
            )
        )
