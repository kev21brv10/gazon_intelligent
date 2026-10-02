"""Le créneau idéal du soir, dessiné par la page, est celui que le moteur publie.

Le moteur ne rend « idéal » qu'à l'INTÉRIEUR de la fenêtre acceptable du soir
(`decision_mowing._resolve_mowing_window`) : avec des réglages qui font déborder la
sous-fenêtre idéale avant l'ouverture du soir, la page annonçait un créneau idéal que la
tondeuse ne recevrait jamais. Les tests rejouent les deux côtés, minute par minute.
"""

from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path
import shutil
import subprocess
import sys
import types
import unittest
from zoneinfo import ZoneInfo

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

dm = __import__("custom_components.gazon_intelligent.decision_mowing", fromlist=["_"])

PANNEAU = ROOT / "custom_components" / "gazon_intelligent" / "frontend" / "gazon-intelligent-panel.js"
NODE = shutil.which("node")

COUCHER = 20 * 60
LEVER = 7 * 60
PREMIERE_MINUTE = 10 * 60
DERNIERE_MINUTE = 22 * 60

SCRIPT = r"""
const fs = require("fs");
const vm = require("vm");
const { chemin, cas } = JSON.parse(fs.readFileSync(0, "utf8"));
const ctx = {
  HTMLElement: class {},
  customElements: { get: () => undefined, define: (nom, classe) => { ctx.Classe = classe; } },
  console, structuredClone,
};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(chemin, "utf8"), ctx);
const page = Object.create(ctx.Classe.prototype);
const sorties = cas.map((c) => {
  const classes = [];
  for (let m = c.debut; m < c.fin; m++) classes.push(ctx.classeTonte(m, c.reglages, c.soleil));
  return { classes, texte: page._dessinSoirTonte(c.reglages, { soleil: c.soleil }) };
});
process.stdout.write(JSON.stringify(sorties));
"""

DEFAUTS = {
    "tonte_fenetre_ideale_debut": dm._MOWING_WINDOW_IDEAL_START * 60,
    "tonte_fenetre_ideale_fin": dm._MOWING_WINDOW_IDEAL_END * 60,
    "tonte_soir_avant_coucher": dm._MOWING_EVENING_START_BEFORE_SUNSET_MIN,
    "tonte_soir_apres_coucher": dm._MOWING_EVENING_END_AFTER_SUNSET_MIN,
    "tonte_soir_ideal_debut_avant_coucher": dm._MOWING_EVENING_IDEAL_START_BEFORE_SUNSET_MIN,
    "tonte_soir_ideal_fin_avant_coucher": dm._MOWING_EVENING_IDEAL_END_BEFORE_SUNSET_MIN,
}


def _page(scenarios: list[dict]) -> list[dict]:
    assert NODE
    cas = [
        {
            "reglages": {**DEFAUTS, **reglages},
            "soleil": {"lever": LEVER, "coucher": COUCHER},
            "debut": PREMIERE_MINUTE,
            "fin": DERNIERE_MINUTE,
        }
        for reglages in scenarios
    ]
    sortie = subprocess.run(
        [NODE, "-e", SCRIPT],
        input=json.dumps({"chemin": str(PANNEAU), "cas": cas}),
        capture_output=True, text=True, check=True, timeout=60,
    )
    return json.loads(sortie.stdout)


def _moteur(minute: int, reglages: dict) -> str:
    """Le verdict publié par le moteur à cette minute, par temps neutre (20 °C, 5 km/h)."""
    ctx = dm.DecisionContext(
        history=[], today=date(2026, 9, 1), hour_of_day=minute / 60.0,
        temperature=20.0, vent=5.0,
    )
    ctx.reglages = {**DEFAUTS, **reglages}
    etat, _ = dm._resolve_mowing_window(ctx, weather_profile={"sunset_minute": COUCHER})
    return etat


def _h(minutes: int) -> str:
    """L'heure telle que la page l'écrit (`heureFr` : espaces insécables)."""
    return f"{minutes // 60}\u00a0h\u00a0{minutes % 60:02d}"


def _minutes(classes: list[str], nom: str) -> list[int]:
    return [PREMIERE_MINUTE + i for i, classe in enumerate(classes) if classe == nom]


@unittest.skipUnless(NODE, "Node n'est pas installé")
class LeCreneauIdealDuSoirDeLaPageSuitLeMoteurTests(unittest.TestCase):
    SCENARIOS = {
        "reglages par defaut": {},
        # Réglages signalés en revue : le moteur n'est idéal qu'à partir de 19 h, la page
        # l'était dès 18 h parce qu'elle ne bornait pas la sous-fenêtre sur le soir.
        "soir resserre a 1 h": {"tonte_soir_avant_coucher": 60},
        # La sous-fenêtre idéale (18 h → 18 h 30) tombe ENTIÈREMENT avant l'ouverture du soir :
        # aucun créneau idéal n'existe ce jour-là, côté moteur comme côté page.
        "ideal avant l'ouverture du soir": {
            "tonte_soir_avant_coucher": 60,
            "tonte_soir_ideal_debut_avant_coucher": 120,
            "tonte_soir_ideal_fin_avant_coucher": 90,
        },
        # L'ouverture du soir est plus tardive que la fin du créneau idéal : fenêtre vide.
        "soir ouvert apres la fin de l'ideal": {
            "tonte_soir_avant_coucher": 20,
            "tonte_soir_ideal_debut_avant_coucher": 120,
            "tonte_soir_ideal_fin_avant_coucher": 30,
        },
        # Le soir ouvre avant la fin du meilleur moment : l'idéal du matin passe le relais.
        "relais du matin": {
            "tonte_soir_avant_coucher": 400,
            "tonte_soir_ideal_debut_avant_coucher": 400,
            "tonte_soir_ideal_fin_avant_coucher": 30,
        },
    }

    @classmethod
    def setUpClass(cls) -> None:
        noms = list(cls.SCENARIOS)
        cls.rendus = dict(zip(noms, _page([cls.SCENARIOS[nom] for nom in noms])))

    def test_chaque_minute_est_ideale_ou_acceptable_comme_dans_le_moteur(self) -> None:
        for nom, reglages in self.SCENARIOS.items():
            classes = self.rendus[nom]["classes"]
            for decalage, classe_page in enumerate(classes):
                minute = PREMIERE_MINUTE + decalage
                etat = _moteur(minute, reglages)
                with self.subTest(scenario=nom, minute=f"{minute // 60}:{minute % 60:02d}"):
                    self.assertEqual(classe_page == "ideal", etat == "ideal")
                    self.assertEqual(classe_page == "possible", etat == "acceptable")

    def test_le_texte_ne_promet_pas_un_ideal_avant_l_ouverture_du_soir(self) -> None:
        # Soir resserré à 1 h : ouverture 19 h, idéal 19 h → 19 h 30 (et non 18 h → 19 h 30).
        texte = self.rendus["soir resserre a 1 h"]["texte"]
        self.assertIn(f"de <b>{_h(19 * 60)}</b> à <b>{_h(20 * 60 + 30)}</b>", texte)
        self.assertIn(f"dont de <b>{_h(19 * 60)}</b> à <b>{_h(19 * 60 + 30)}</b> en créneau idéal", texte)
        self.assertNotIn(_h(18 * 60), texte)

    def test_le_texte_se_tait_quand_aucun_creneau_ideal_n_existe(self) -> None:
        for nom in ("ideal avant l'ouverture du soir", "soir ouvert apres la fin de l'ideal"):
            with self.subTest(scenario=nom):
                rendu = self.rendus[nom]
                self.assertNotIn("créneau idéal", rendu["texte"])
                self.assertNotIn("dont de", rendu["texte"])
                # Plus aucune minute idéale l'après-midi ni le soir : seul reste celui du matin.
                self.assertEqual(
                    [m for m in _minutes(rendu["classes"], "ideal") if m >= 14 * 60], []
                )

    def test_les_reglages_par_defaut_annoncent_l_ideal_du_soir(self) -> None:
        texte = self.rendus["reglages par defaut"]["texte"]
        self.assertIn(f"dont de <b>{_h(18 * 60)}</b> à <b>{_h(19 * 60 + 30)}</b> en créneau idéal", texte)

    def test_le_relais_du_matin_borne_aussi_le_creneau_annonce(self) -> None:
        # L'ouverture (13 h 20) tombe avant la fin du meilleur moment (14 h) : le soir commence
        # à 14 h, et l'idéal annoncé ne remonte pas avant.
        texte = self.rendus["relais du matin"]["texte"]
        self.assertIn(f"de <b>{_h(14 * 60)}</b> à <b>{_h(20 * 60 + 30)}</b>", texte)
        self.assertIn(f"dont de <b>{_h(14 * 60)}</b> à <b>{_h(19 * 60 + 30)}</b> en créneau idéal", texte)


if __name__ == "__main__":
    unittest.main()
