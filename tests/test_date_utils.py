from __future__ import annotations

import unittest
from datetime import date
from importlib import util
from pathlib import Path
import sys


def _load_date_utils_module():
    module_path = (
        Path(__file__).resolve().parents[1]
        / "custom_components"
        / "gazon_intelligent"
        / "date_utils.py"
    )
    spec = util.spec_from_file_location("gazon_intelligent_date_utils", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Impossible de charger {module_path}")
    module = util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


date_utils = _load_date_utils_module()


class DateUtilsTests(unittest.TestCase):
    def test_parse_optional_date_accepts_french_format(self) -> None:
        self.assertEqual(date_utils.parse_optional_date("18/03/2026"), date(2026, 3, 18))

    def test_parse_optional_date_accepts_existing_iso_format(self) -> None:
        self.assertEqual(date_utils.parse_optional_date("2026-03-18"), date(2026, 3, 18))

