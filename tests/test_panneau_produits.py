"""La page « Gazon » ne perd rien quand elle réécrit une fiche produit.

`register_product` REMPLACE la fiche entière : un champ que la page ne renvoie pas est effacé. La
page renvoie donc la liste `CHAMPS_PRODUIT`, reprise de la fiche complète. Ce test vérifie que
cette liste couvre chaque champ du service ET chaque champ que le moteur garde dans une fiche,
et que les listes de choix de la page sont celles du service.
"""

from __future__ import annotations

import re
import sys
import types
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT / "custom_components" / "gazon_intelligent"
PANNEAU = PACKAGE_DIR / "frontend" / "gazon-intelligent-panel.js"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ensure_package(name: str, path: Path) -> None:
    if name in sys.modules:
        return
    module = types.ModuleType(name)
    module.__path__ = [str(path)]  # type: ignore[attr-defined]
    sys.modules[name] = module


def _install_homeassistant_dt_stub() -> None:
    if "homeassistant.util.dt" in sys.modules:
        return
    homeassistant_module = sys.modules.setdefault("homeassistant", types.ModuleType("homeassistant"))
    util_module = sys.modules.setdefault("homeassistant.util", types.ModuleType("homeassistant.util"))
    homeassistant_module.util = util_module  # type: ignore[attr-defined]
    dt_module = types.ModuleType("homeassistant.util.dt")
    dt_module.now = lambda: datetime(2026, 4, 4, 14, 15, tzinfo=ZoneInfo("Europe/Paris"))  # type: ignore[attr-defined]
    sys.modules["homeassistant.util.dt"] = dt_module
    util_module.dt = dt_module  # type: ignore[attr-defined]


_ensure_package("custom_components", PACKAGE_DIR.parent)
_ensure_package("custom_components.gazon_intelligent", PACKAGE_DIR)
_install_homeassistant_dt_stub()

memory = __import__("custom_components.gazon_intelligent.memory", fromlist=["_"])


def _champs_du_service(service: str) -> dict[str, list[str]]:
    """Champs d'un service de `services.yaml` et leurs options, sans dépendre de PyYAML."""
    lignes = (PACKAGE_DIR / "services.yaml").read_text(encoding="utf-8").splitlines()
    debut = lignes.index(f"{service}:")
    champs: dict[str, list[str]] = {}
    dans_les_champs = False
    courant = None
    for ligne in lignes[debut + 1:]:
        if ligne and not ligne[0].isspace():
            break
        if ligne == "  fields:":
            dans_les_champs = True
            continue
        if not dans_les_champs:
            continue
        nom = re.fullmatch(r"    ([a-z_]+):", ligne)
        if nom:
            courant = nom.group(1)
            champs[courant] = []
            continue
        option = re.fullmatch(r"\s+- (.+)", ligne)
        if option and courant:
            champs[courant].append(option.group(1).strip())
    return champs


def _liste_js(nom: str) -> list[str]:
    source = PANNEAU.read_text(encoding="utf-8")
    bloc = re.search(rf"const {nom} = \[(.*?)\];", source, re.S)
    assert bloc, nom
    return re.findall(r'"([^"]+)"', bloc.group(1))


def _cles_js(nom: str) -> list[str]:
    source = PANNEAU.read_text(encoding="utf-8")
    bloc = re.search(rf"const {nom} = \{{(.*?)\}};", source, re.S)
    assert bloc, nom
    return re.findall(r'(?:^|,)\s*"?([A-Za-z_]+)"?\s*:', bloc.group(1))


class LaPageRenvoieToutesLesFichesProduitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = _champs_du_service("register_product")
        self.page = _liste_js("CHAMPS_PRODUIT")

    def test_la_page_renvoie_chaque_champ_du_service(self) -> None:
        self.assertEqual(sorted(self.page), sorted(set(self.service) - {"product_id"}))
        self.assertEqual(len(self.page), len(set(self.page)), "un champ en double")

    def test_la_page_renvoie_chaque_champ_que_le_moteur_garde(self) -> None:
        # Une fiche remplie au maximum : tout ce que le moteur en garde doit revenir à l'écriture.
        complet = {
            "nom": "Essai", "type": "Fertilisation", "dose_conseillee": "30 g/m²", "usage_mode": "entretien",
            "max_applications_per_year": 3, "reapplication_after_days": 30, "delai_avant_tonte_jours": 2,
            "phase_compatible": ["Entretien"], "application_months": [3, 4], "application_type": "sol",
            "application_requires_watering_after": True, "application_post_watering_mm": 5.0,
            "application_irrigation_block_hours": 1.0, "application_irrigation_delay_minutes": 10.0,
            "application_irrigation_mode": "auto", "application_label_notes": "Étiquette", "note": "Note",
            "temperature_min": 5.0, "temperature_max": 30.0,
        }
        fiche = memory.normalize_product_record("essai", complet)
        self.assertIsNotNone(fiche)
        calcules = {"id", "application_months_label"}  # recalculés par le moteur à chaque écriture
        self.assertEqual(sorted(set(fiche) - calcules), sorted(self.page))

    def test_les_listes_de_la_page_sont_celles_du_service(self) -> None:
        self.assertEqual(sorted(_liste_js("TYPES_PRODUIT")), sorted(self.service["type"]))
        self.assertEqual(sorted(_cles_js("USAGES_PRODUIT")), sorted(self.service["usage_mode"]))
        self.assertEqual(sorted(_cles_js("PHASES_PRODUIT")), sorted(self.service["phase_compatible"]))
        self.assertEqual(
            sorted(_cles_js("MODES_ARROSAGE_PRODUIT")), sorted(self.service["application_irrigation_mode"])
        )
        self.assertEqual(sorted(self.service["application_type"]), ["foliaire", "sol"])

    def test_l_identifiant_tire_du_nom_est_celui_du_moteur(self) -> None:
        # La page enlève les accents ; le moteur garde les lettres. Sans accent, ils coïncident.
        for nom, attendu in (("Kick Pro", "kick_pro"), ("H2Pro TriSmart", "h2pro_trismart"), ("  Floranid Twin Permanent ", "floranid_twin_permanent")):
            with self.subTest(nom=nom):
                self.assertEqual(memory.normalize_product_id(nom), attendu)


if __name__ == "__main__":
    unittest.main()
