"""Contrat exécutable des réglages ajoutés pendant l'étape 7."""

from __future__ import annotations

import importlib
import json
import shutil
import subprocess
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT / "custom_components" / "gazon_intelligent"
PANNEAU = PACKAGE_DIR / "frontend" / "gazon-intelligent-panel.js"
NODE = shutil.which("node")
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
reglages_module = importlib.import_module("custom_components.gazon_intelligent.reglages")

SCRIPT = r"""
const fs = require("fs");
const vm = require("vm");
const chemin = JSON.parse(fs.readFileSync(0, "utf8")).chemin;
const ctx = {
  HTMLElement: class {},
  customElements: { get: () => undefined, define: (_nom, classe) => { ctx.Classe = classe; } },
  console,
};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(chemin, "utf8"), ctx);

const panel = Object.create(ctx.Classe.prototype);
panel._hass = { user: { is_admin: true } };
panel._brouillonAlertes = {};
panel._brouillonChoix = {};
panel._donnees = {
  notifications: {
    cibles: [], alertes: true, mode: "veille_intelligente", source: "conseiller_gazon",
    niveau_minimal: "action",
    heures_calmes: { active: true, debut: 1290, fin: 405 },
    categories: { arrosage_graines: true, securite_arrosage: true, capteurs_meteo: true, tondeuse: true },
    telephones: [], ias: [], ia_choisie: "", ia_disponible: false,
  },
};
const alertes = panel._alertesReglagesHtml();
panel._changerAlerte("heures_calmes", { active: true, debut: 1320, fin: 420 });

const pluie = {
  cle: "arrosage_sensibilite_pluie", titre: "Comment tenir compte de la pluie annoncée ?",
  aide: "Aide", defaut: 1, minimum: .75, maximum: 1.25, pas: .25, unite: "×",
  genre: "nombre", avertissement: "Réglage sensible : test.",
};
panel._brouillon = {};
panel._valeur = () => 1;
const pluieHtml = panel._sensibilitePluieHtml(pluie);

const constantes = vm.runInContext("({ PROFILS_GAZON })", ctx);
const profilOrnement = constantes.PROFILS_GAZON.find((p) => p.cle === "ornement");
const clesProfil = Object.keys(profilOrnement.valeurs);
panel._donnees.registre = {
  reglages: clesProfil.map((cle) => ({ cle })),
  choix: [{ cle: "tondeuse_creneaux_depart", defaut: "ideal_seulement" }],
};
panel._donnees.choix = { tondeuse_creneaux_depart: "ideal_seulement" };
panel._reglage = (cle) => panel._donnees.registre.reglages.find((r) => r.cle === cle);
panel._valeur = (cle) => profilOrnement.valeurs[cle];
const profils = panel._profilGazonHtml();

process.stdout.write(JSON.stringify({
  alertes,
  heuresBrouillon: panel._brouillonAlertes.heures_calmes,
  pluieHtml,
  profils,
  profilsGazon: constantes.PROFILS_GAZON,
}));
"""


def _rendre() -> dict[str, object]:
    assert NODE
    resultat = subprocess.run(
        [NODE, "-e", SCRIPT],
        input=json.dumps({"chemin": str(PANNEAU)}),
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return json.loads(resultat.stdout)


@unittest.skipUnless(NODE, "Node n'est pas installé")
class ReglagesEtape7Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rendu = _rendre()

    def test_notifications_affichent_niveau_et_heures_calmes(self) -> None:
        html = str(self.rendu["alertes"])
        self.assertIn("Qui rédige les notifications ?", html)
        self.assertIn("Gazon Intelligent", html)
        self.assertIn("Conseiller Gazon", html)
        self.assertNotIn("Veille intelligente", html)
        self.assertIn("Urgences seulement", html)
        self.assertIn('data-alerte-heure="debut" value="21:30"', html)
        self.assertIn('data-alerte-heure="fin" value="06:45"', html)
        self.assertIn("Une vanne bloquée reste toujours urgente", html)
        self.assertEqual(self.rendu["heuresBrouillon"], {"active": True, "debut": 1320, "fin": 420})

    def test_pluie_est_presentee_en_trois_profils_lisibles(self) -> None:
        html = str(self.rendu["pluieHtml"])
        for libelle in ("Prudente pour le gazon", "Équilibrée", "Économe en eau"):
            self.assertIn(libelle, html)
        self.assertIn('data-valeur="1" aria-pressed="true"', html)
        self.assertNotIn('type="range"', html)

    def test_trois_profils_sont_des_raccourcis_sans_securites_physiques(self) -> None:
        html = str(self.rendu["profils"])
        profils = self.rendu["profilsGazon"]
        cles_par_profil = {p["cle"]: set(p["valeurs"].keys()) for p in profils}
        self.assertEqual(set(cles_par_profil), {"ornement", "jeu", "rustique"})
        self.assertIn("Gazon d&#39;ornement", html)
        self.assertIn("Gazon de jeu", html)
        self.assertIn("Gazon rustique, économe en eau", html)
        self.assertIn('data-action="profil-gazon"', html)
        self.assertIn("Il ne modifie jamais les protections des vannes", html)
        for cles in cles_par_profil.values():
            self.assertIn("tonte_hauteur_par_mois", cles)
            self.assertIn("arrosage_sensibilite_pluie", cles)
            self.assertFalse(any("vanne" in cle or "pompe" in cle or "zone" in cle for cle in cles))
        profils = {p["cle"]: p for p in self.rendu["profilsGazon"]}
        self.assertEqual(profils["ornement"]["choix"]["tondeuse_creneaux_depart"], "ideal_seulement")
        self.assertEqual(profils["jeu"]["choix"]["tondeuse_creneaux_depart"], "ideal_acceptable")
        self.assertEqual(profils["rustique"]["choix"]["tondeuse_creneaux_depart"], "ideal_acceptable")
        # Les valeurs testées (celles du profil « ornement ») font que ce profil est actif :
        # son bouton est désactivé, les deux autres (dont les valeurs diffèrent) restent actifs.
        self.assertIn('data-profil="ornement" disabled', html)
        self.assertNotIn('data-profil="jeu" disabled', html)
        self.assertNotIn('data-profil="rustique" disabled', html)

    def test_chaque_valeur_de_profil_tient_dans_les_bornes_du_reglage(self) -> None:
        par_cle = {r.cle: r for r in reglages_module.REGLAGES}
        for profil in self.rendu["profilsGazon"]:
            for cle, valeur in profil["valeurs"].items():
                with self.subTest(profil=profil["cle"], cle=cle):
                    reglage = par_cle[cle]
                    valeurs = valeur if isinstance(valeur, list) else [valeur]
                    for v in valeurs:
                        self.assertGreaterEqual(v, reglage.minimum)
                        self.assertLessEqual(v, reglage.maximum)
                        pas_relatif = (v - reglage.minimum) / reglage.pas
                        self.assertAlmostEqual(pas_relatif, round(pas_relatif), places=6)


if __name__ == "__main__":
    unittest.main()
