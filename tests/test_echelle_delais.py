"""L'échelle « secondes puis minutes » des délais du volet : 1, 2, 3, 4… secondes, puis 1 min, 2 min, etc.

Demande du 04/10/2026 : « tout en seconde pour 1, 2, 3, 4… et après 1 minute, 2 minutes, etc. ». Les six délais du
volet partagent une échelle à DEUX pas : de `minimum` à 60 s la valeur avance d'une seconde, puis d'une minute.
La page en a un double (positions du curseur, validation, cran voisin) : ici, la page et le registre doivent
donner EXACTEMENT les mêmes valeurs, cran par cran.
"""

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
reglages = importlib.import_module("custom_components.gazon_intelligent.reglages")

PANNEAU = PACKAGE_DIR / "frontend" / "gazon-intelligent-panel.js"
NODE = shutil.which("node")

LES_SIX = (
    "tondeuse_garage_delai_fermeture_tonte_secondes",
    "tondeuse_garage_avance_ouverture_secondes",
    "tondeuse_garage_delai_fermeture_secondes",
    "tondeuse_garage_delai_fermeture_manuel_secondes",
    "tondeuse_garage_delai_reprise_secondes",
    "tondeuse_garage_delai_max_mouvement_secondes",
)


def _valeurs_valides(r) -> list[int]:
    """Toutes les valeurs entières que le registre accepte, dans l'ordre."""
    return [v for v in range(int(r.minimum), int(r.maximum) + 1) if not reglages._erreur_de_valeur(r, v)]


class EchelleDuRegistreTests(unittest.TestCase):
    def test_les_six_delais_partagent_la_meme_echelle(self) -> None:
        for cle in LES_SIX:
            with self.subTest(cle=cle):
                r = reglages.reglage(cle)
                self.assertEqual((r.genre, r.unite, r.pas, r.seuil, r.pas_haut), ("nombre", "s", 1, 60, 60))
                self.assertEqual((r.maximum - r.seuil) % r.pas_haut, 0, "le maximum tombe sur un cran de minutes")
                self.assertEqual(r.minimum % r.pas, 0)

    def test_seconde_par_seconde_jusqu_a_une_minute_puis_minute_par_minute(self) -> None:
        r = reglages.reglage("tondeuse_garage_delai_fermeture_secondes")           # 0 … 900 s
        valides = _valeurs_valides(r)
        self.assertEqual(valides[:62], list(range(0, 60)) + [60, 120])
        self.assertEqual(valides[60:], [60 * k for k in range(1, 16)])
        self.assertEqual(len(valides), 60 + 15)

    def test_chaque_delai_commence_la_ou_il_doit(self) -> None:
        planchers = {"tondeuse_garage_delai_reprise_secondes": 5, "tondeuse_garage_delai_max_mouvement_secondes": 5}
        for cle in LES_SIX:
            with self.subTest(cle=cle):
                r = reglages.reglage(cle)
                self.assertEqual(r.minimum, planchers.get(cle, 0))
                self.assertEqual(_valeurs_valides(r)[0], r.minimum)

    def test_le_cran_le_plus_proche_est_toujours_valide_borne_et_stable(self) -> None:
        for cle in LES_SIX:
            r = reglages.reglage(cle)
            for dixieme in range(int(r.minimum) * 10 - 30, int(r.maximum) * 10 + 31, 7):
                v = dixieme / 10
                with self.subTest(cle=cle, v=v):
                    c = reglages.caler(r, v)
                    self.assertGreaterEqual(c, r.minimum)
                    self.assertLessEqual(c, r.maximum)
                    self.assertIsNone(reglages._erreur_de_valeur(r, c), "le cran est une valeur acceptée")
                    self.assertEqual(reglages.caler(r, c), c, "idempotent")
                    if r.minimum <= v <= r.maximum:
                        self.assertLessEqual(abs(c - v), r.pas_haut / 2 + 1e-9, "le plus proche")

    def test_les_egalites_vont_vers_le_haut(self) -> None:
        r = reglages.reglage("tondeuse_garage_delai_fermeture_secondes")
        self.assertEqual((reglages.caler(r, 90), reglages.caler(r, 150), reglages.caler(r, 89.9)), (120, 180, 60))

    def test_un_message_dit_les_deux_pas(self) -> None:
        erreur = reglages.valider({"tondeuse_garage_delai_fermeture_secondes": 90})["tondeuse_garage_delai_fermeture_secondes"]
        self.assertIn("Jusqu'à 60", erreur)
        self.assertIn("de 1 en 1", erreur)
        self.assertIn("de 60 en 60", erreur)

    def test_l_export_donne_a_la_page_l_echelle(self) -> None:
        exportes = {r["cle"]: r for r in reglages.exporter()["reglages"]}
        for cle in LES_SIX:
            self.assertEqual((exportes[cle]["seuil"], exportes[cle]["pas_haut"]), (60, 60))
        self.assertEqual(exportes["tonte_vent_bloque"]["pas_haut"], 0, "les autres réglages gardent leur pas unique")

    def test_les_autres_reglages_ne_sont_pas_touches(self) -> None:
        for r in reglages.REGLAGES:
            if r.cle not in LES_SIX:
                with self.subTest(cle=r.cle):
                    self.assertEqual((r.seuil, r.pas_haut), (0, 0))


SCRIPT = r"""
const fs = require("fs");
const vm = require("vm");
const { chemin, reglages } = JSON.parse(fs.readFileSync(0, "utf8"));
const ctx = {
  HTMLElement: class {},
  customElements: { get: () => undefined, define: (_nom, classe) => { ctx.Classe = classe; } },
  console,
};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(chemin, "utf8"), ctx);
const sortie = {};
for (const r of reglages) {
  const e = ctx.echelleDe(r);
  const positions = Array.from({ length: e.total + 1 }, (_, p) => ctx.valeurDePosition(r, p));
  const entiers = [];
  for (let v = Math.floor(r.minimum) - 20; v <= r.maximum + 20; v++) entiers.push(v);
  const demis = entiers.map((v) => v + 0.5);
  sortie[r.cle] = {
    total: e.total,
    positions,
    sur_le_pas: Object.fromEntries(entiers.map((v) => [v, ctx.surLePas(r, v)])),
    caler: Object.fromEntries([...entiers, ...demis].map((v) => [v, ctx.caler(r, v)])),
    voisines: positions.map((v) => [ctx.voisine(r, v, -1), ctx.voisine(r, v, 1)]),
    positions_de: positions.map((v) => ctx.positionDeValeur(r, v)),
    textes: Object.fromEntries([0, 1, 2, 3, 4, 45, 59, 60, 120, 180, 5400].map((v) => [v, ctx.secondesFr(v)])),
    erreurs: ctx.valider({ reglages: [r], contraintes: [] }, { [r.cle]: 90 }).erreurs[r.cle] || null,
    curseur: ctx.attributsCurseur(r, 90),
  };
}
process.stdout.write(JSON.stringify(sortie));
"""


@unittest.skipUnless(NODE, "Node n'est pas installé")
class EchelleDeLaPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        entree = {"chemin": str(PANNEAU), "reglages": [r for r in reglages.exporter()["reglages"] if r["cle"] in LES_SIX]}
        cls.sortie = json.loads(subprocess.run(
            [NODE, "-e", SCRIPT], input=json.dumps(entree), capture_output=True, text=True, check=True, timeout=120).stdout)

    def test_la_page_donne_les_memes_valeurs_que_le_registre_cran_par_cran(self) -> None:
        for cle in LES_SIX:
            with self.subTest(cle=cle):
                valides = _valeurs_valides(reglages.reglage(cle))
                self.assertEqual(self.sortie[cle]["positions"], valides)
                self.assertEqual(self.sortie[cle]["total"], len(valides) - 1)

    def test_la_validation_de_la_page_est_celle_du_serveur(self) -> None:
        for cle in LES_SIX:
            r = reglages.reglage(cle)
            for v, attendu in self.sortie[cle]["sur_le_pas"].items():
                v = int(v)
                if r.minimum <= v <= r.maximum:
                    with self.subTest(cle=cle, v=v):
                        self.assertEqual(attendu, not reglages._erreur_de_valeur(r, v))

    def test_le_cran_le_plus_proche_est_le_meme_page_et_serveur(self) -> None:
        for cle in LES_SIX:
            r = reglages.reglage(cle)
            for v, attendu in self.sortie[cle]["caler"].items():
                with self.subTest(cle=cle, v=v):
                    self.assertEqual(attendu, reglages.caler(r, float(v)))

    def test_le_bouton_plus_ou_moins_passe_au_cran_voisin(self) -> None:
        for cle in LES_SIX:
            valides = _valeurs_valides(reglages.reglage(cle))
            attendu = [[valides[max(0, i - 1)], valides[min(len(valides) - 1, i + 1)]] for i in range(len(valides))]
            with self.subTest(cle=cle):
                self.assertEqual(self.sortie[cle]["voisines"], attendu)
                self.assertEqual(self.sortie[cle]["positions_de"], list(range(len(valides))), "aller-retour valeur ↔ position")

    def test_les_durees_s_ecrivent_en_secondes_puis_en_minutes(self) -> None:
        nbsp = " "
        attendu = {"0": f"0{nbsp}s", "1": f"1{nbsp}s", "2": f"2{nbsp}s", "3": f"3{nbsp}s", "4": f"4{nbsp}s", "45": f"45{nbsp}s",
                   "59": f"59{nbsp}s", "60": f"1{nbsp}min", "120": f"2{nbsp}min", "180": f"3{nbsp}min",
                   "5400": f"1{nbsp}h{nbsp}30"}
        for cle in LES_SIX:
            with self.subTest(cle=cle):
                self.assertEqual(self.sortie[cle]["textes"], attendu)

    def test_le_message_de_la_page_est_celui_du_serveur(self) -> None:
        for cle in LES_SIX:
            with self.subTest(cle=cle):
                self.assertEqual(self.sortie[cle]["erreurs"], reglages.valider({cle: 90})[cle])

    def test_le_curseur_travaille_en_positions_pas_en_secondes(self) -> None:
        for cle in LES_SIX:
            r = reglages.reglage(cle)
            c = self.sortie[cle]["curseur"]
            with self.subTest(cle=cle):
                self.assertEqual((c["min"], c["step"]), (0, 1))
                self.assertEqual(c["max"], len(_valeurs_valides(r)) - 1)
                self.assertEqual(c["valeur"], _valeurs_valides(r).index(reglages.caler(r, 90)))


SCRIPT_CURSEUR = r"""
const fs = require("fs");
const vm = require("vm");
const { chemin, reglage, cas } = JSON.parse(fs.readFileSync(0, "utf8"));
const ctx = {
  HTMLElement: class {},
  customElements: { get: () => undefined, define: (_nom, classe) => { ctx.Classe = classe; } },
  console,
};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(chemin, "utf8"), ctx);

function fabriquer(valeur) {
  const p = Object.create(ctx.Classe.prototype);
  p._hass = { user: { is_admin: true } };
  p._brouillon = {};
  p._donnees = { registre: { reglages: [reglage], contraintes: [] } };
  p._valeurCourante = valeur;
  p._valeur = () => p._valeurCourante;
  p._reglage = () => reglage;
  p._toutesLesValeurs = () => ({ [reglage.cle]: p._valeurCourante });
  p._fenetre = { contains: () => false };
  p.changements = [];
  p._changer = (cle, v) => { p.changements.push([cle, v]); p._valeurCourante = v; };
  p._rafraichirApresChangement = () => {};
  p._rendre = () => {};
  return p;
}

const sorties = cas.map((c) => {
  const p = fabriquer(c.valeur);
  if (c.type === "html") return { html: p._ligneHtml(reglage) };
  if (c.type === "saisie") {
    const cible = { matches: (sel) => sel === 'input[type="range"]', closest: () => ({ dataset: { cle: reglage.cle } }), value: String(c.position) };
    p._surSaisie({ target: cible });
    return { changements: p.changements };
  }
  if (c.type === "pas") {
    p._pas({ dataset: { cle: reglage.cle } }, c.sens);
    return { changements: p.changements };
  }
  return null;
});
process.stdout.write(JSON.stringify(sorties));
"""


def _page(reglage: dict, cas: list[dict]) -> list[dict]:
    entree = {"chemin": str(PANNEAU), "reglage": reglage, "cas": cas}
    resultat = subprocess.run([NODE, "-e", SCRIPT_CURSEUR], input=json.dumps(entree), capture_output=True, text=True, timeout=120)
    if resultat.returncode:
        raise AssertionError(f"la page a planté : {resultat.stderr[-800:]}")
    return json.loads(resultat.stdout)


@unittest.skipUnless(NODE, "Node n'est pas installé")
class CurseurDeLaPageTests(unittest.TestCase):
    """Le VRAI curseur de la page : rendu, glissement et boutons − / + sur l'échelle à deux pas."""

    CLE = "tondeuse_garage_delai_fermeture_secondes"

    @classmethod
    def setUpClass(cls) -> None:
        cls.reglage = next(r for r in reglages.exporter()["reglages"] if r["cle"] == cls.CLE)
        cls.valides = _valeurs_valides(reglages.reglage(cls.CLE))

    def test_le_rendu_place_le_curseur_sur_la_position_et_ecrit_la_duree(self) -> None:
        nbsp = "\u00a0"
        for valeur, texte in ((0, f"0{nbsp}s"), (1, f"1{nbsp}s"), (15, f"15{nbsp}s"), (60, f"1{nbsp}min"), (120, f"2{nbsp}min"), (900, f"15{nbsp}min")):
            with self.subTest(valeur=valeur):
                (sortie,) = _page(self.reglage, [{"type": "html", "valeur": valeur}])
                position = self.valides.index(valeur)
                self.assertIn(f'min="0" max="{len(self.valides) - 1}" step="1" value="{position}"', sortie["html"])
                self.assertIn(f"<output class=\"bulle bulle-haut\">{texte}</output>", sortie["html"])
                self.assertIn(f'aria-valuetext="{texte}"', sortie["html"])

    def test_le_glissement_donne_une_position_que_la_page_convertit_en_duree(self) -> None:
        for position in range(len(self.valides)):
            (sortie,) = _page(self.reglage, [{"type": "saisie", "valeur": 120, "position": position}])
            with self.subTest(position=position):
                self.assertEqual(sortie["changements"], [[self.CLE, self.valides[position]]])

    def test_les_boutons_moins_et_plus_passent_au_cran_voisin(self) -> None:
        for valeur in (0, 1, 59, 60, 120, 840, 900):
            i = self.valides.index(valeur)
            for sens, voisin in ((-1, self.valides[max(0, i - 1)]), (1, self.valides[min(len(self.valides) - 1, i + 1)])):
                with self.subTest(valeur=valeur, sens=sens):
                    (sortie,) = _page(self.reglage, [{"type": "pas", "valeur": valeur, "sens": sens}])
                    self.assertEqual(sortie["changements"], [[self.CLE, voisin]])

    def test_un_reglage_a_pas_unique_garde_son_curseur_en_valeurs(self) -> None:
        r = next(x for x in reglages.exporter()["reglages"] if x["cle"] == "tonte_vent_bloque")
        (sortie,) = _page(r, [{"type": "html", "valeur": 40}])
        self.assertIn(f'min="{r["minimum"]}" max="{r["maximum"]}" step="{r["pas"]}" value="40"', sortie["html"])


if __name__ == "__main__":
    unittest.main()
