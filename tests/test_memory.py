from __future__ import annotations

import unittest
from datetime import date
from importlib import util
from pathlib import Path
import sys


def _load_memory_module():
    module_path = (
        Path(__file__).resolve().parents[1]
        / "custom_components"
        / "gazon_intelligent"
        / "memory.py"
    )
    spec = util.spec_from_file_location("gazon_intelligent_memory", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Impossible de charger {module_path}")
    module = util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


memory = _load_memory_module()


class MemoryCatalogTests(unittest.TestCase):
    def test_normalize_product_record_keeps_simple_catalog_fields(self) -> None:
        record = memory.normalize_product_record(
            "Engrais Printemps",
            {
                "nom": "Engrais printemps",
                "type": "Fertilisation",
                "dose_conseillee": "12.5",
                "reapplication_after_days": "21",
                "delai_avant_tonte_jours": "2",
                "phase_compatible": "Normal, Reprise",
                "note": "Appliquer au matin",
            },
        )

        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record["id"], "engrais_printemps")
        self.assertEqual(record["nom"], "Engrais printemps")
        self.assertEqual(record["type"], "Fertilisation")
        self.assertEqual(record["dose_conseillee"], "12.5")
        self.assertEqual(record["reapplication_after_days"], 21)
        self.assertEqual(record["delai_avant_tonte_jours"], 2)
        self.assertEqual(record["phase_compatible"], ["Normal", "Reprise"])

    def test_build_application_summary_includes_product_id(self) -> None:
        summary = memory.build_application_summary(
            {
                "type": "Fertilisation",
                "date": "2026-03-18",
                "produit_id": "engrais_printemps",
                "produit": "Engrais printemps",
                "dose": "12.5",
                "zone": "zone_1",
                "note": "Test",
                "reapplication_after_days": 21,
                "source": "service",
            }
        )

        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertEqual(summary["produit_id"], "engrais_printemps")
        self.assertEqual(summary["libelle"], "Engrais printemps")
        self.assertEqual(summary["reapplication_after_days"], 21)

    def test_compute_next_reapplication_date_prefers_latest_item(self) -> None:
        next_date = memory.compute_next_reapplication_date(
            [
                {"type": "Fertilisation", "date": "2026-03-01", "reapplication_after_days": 21},
                {"type": "Biostimulant", "date": "2026-03-10", "reapplication_after_days": 25},
            ],
            today=date(2026, 3, 18),
        )

        self.assertEqual(next_date, "2026-04-04")
