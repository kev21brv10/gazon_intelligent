import importlib
import sys
import types
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT / "custom_components" / "gazon_intelligent"
custom_components = types.ModuleType("custom_components")
custom_components.__path__ = [str(PACKAGE_DIR.parent)]  # type: ignore[attr-defined]
gazon_package = types.ModuleType("custom_components.gazon_intelligent")
gazon_package.__path__ = [str(PACKAGE_DIR)]  # type: ignore[attr-defined]
sys.modules.setdefault("custom_components", custom_components)
sys.modules.setdefault("custom_components.gazon_intelligent", gazon_package)
compute_estimated_water_consumption = importlib.import_module(
    "custom_components.gazon_intelligent.water"
).compute_estimated_water_consumption
reglages = importlib.import_module("custom_components.gazon_intelligent.reglages")


def test_surface_setting_is_optional_until_the_lawn_area_is_known():
    setting = reglages.reglage("surface_gazon_m2")

    assert setting.defaut == 0.0
    assert setting.unite == "m²"


def test_estimated_consumption_uses_255_square_metres_and_year_windows():
    result = compute_estimated_water_consumption(
        [
            {"type": "arrosage", "date": "2026-01-01", "total_mm": 2.0},
            {"type": "arrosage", "date": "2026-09-01", "total_mm": 3.0},
            {"type": "arrosage", "date": "2026-09-22", "total_mm": 4.0},
            {"type": "tonte", "date": "2026-09-22"},
        ],
        surface_m2=255,
        today=date(2026, 9, 22),
    )

    assert result["today_l"] == 1020
    assert result["month_l"] == 1785
    assert result["year_l"] == 2295
    assert result["coverage_start"] == "2026-01-01"
    assert result["year_complete"] is True


def test_estimated_consumption_never_claims_a_complete_year_without_old_history():
    result = compute_estimated_water_consumption(
        [{"type": "arrosage", "date": "2026-07-10", "objectif_mm": 5.0}],
        surface_m2=255,
        today=date(2026, 9, 22),
    )

    assert result["year_l"] == 1275
    assert result["coverage_start"] == "2026-07-10"
    assert result["year_complete"] is False
