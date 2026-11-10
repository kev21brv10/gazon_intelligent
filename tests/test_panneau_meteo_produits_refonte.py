"""Onglets Météo et Produits (refonte 1.0) : plage de température, barre de pluie, courbe des heures, pertinence.

Figé ici : la barre de température de chaque jour est placée sur l'étendue de la SEMAINE (pas sur une
échelle fixe), la barre de pluie a un plafond d'au moins 5 mm (un jour à 0,4 mm n'a pas l'air d'une
averse), la courbe des heures n'existe qu'à partir de trois températures et ses barres de pluie suivent
la pluie annoncée, et la pertinence d'un produit n'est dessinée que si elle est positive, bornée à 100 %.
Le vrai JS est exécuté dans Node.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
PANNEAU = ROOT / "custom_components" / "gazon_intelligent" / "frontend" / "gazon-intelligent-panel.js"
NODE = shutil.which("node")

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
const sorties = cas.map((c) => {
  const p = Object.create(ctx.Classe.prototype);
  p._fuseau = () => "Europe/Paris";
  p._previsions = c.previsions;
  p._mosaique = (items) => items.map((i) => i[0]).join("\n<!--sep-->\n");
  p._historiqueProduitsHtml = () => "";
  p._catalogueHtml = () => "";
  const intervention = c.intervention || {};
  p._a = (cle, nom) => (cle === "prochaine_intervention" ? intervention[nom] : undefined);
  p._s = (cle) => (cle === "prochaine_intervention" ? c.etat : undefined);
  if (c.quoi === "jours") return p._meteoJoursHtml({ maintenant: { annee: 2026, mois: 9, jour: 17 } });
  if (c.quoi === "courbe") return p._courbeHeuresHtml(c.heures);
  return p._ongletProduitsHtml({});
});
process.stdout.write(JSON.stringify(sorties));
"""


def _rendre(cas: list[dict]) -> list[str]:
    assert NODE
    sortie = subprocess.run(
        [NODE, "-e", SCRIPT], input=json.dumps({"chemin": str(PANNEAU), "cas": cas}),
        capture_output=True, text=True, check=True, timeout=60,
    )
    return [texte.replace(" ", " ") for texte in json.loads(sortie.stdout)]


def _jour(jour: int, bas: float | None, haut: float | None, pluie: float | None = 0) -> dict:
    j: dict = {"datetime": f"2026-09-{jour:02d}T12:00:00+02:00", "condition": "sunny"}
    if bas is not None:
        j["templow"] = bas
    if haut is not None:
        j["temperature"] = haut
    if pluie is not None:
        j["precipitation"] = pluie
    return j


def _jours(*jours: dict) -> dict:
    return {"quoi": "jours", "previsions": {"jours": list(jours), "heures": []}}


def _plages(html: str) -> list[tuple[float, float]]:
    return [(float(a), float(b)) for a, b in re.findall(r'class="plage-t" role="img"[^>]*><i style="left:([\d.]+)%;width:([\d.]+)%"', html)]


def _pluies(html: str) -> list[float]:
    return [float(x) for x in re.findall(r'class="barre-pluie"[^>]*><i style="width:([\d.]+)%"', html)]


@unittest.skipUnless(NODE, "Node n'est pas installé")
class JoursMeteoTests(unittest.TestCase):
    def test_la_plage_de_chaque_jour_est_placee_sur_l_etendue_de_la_semaine(self) -> None:
        (html,) = _rendre([_jours(_jour(17, 10, 20), _jour(18, 10, 30), _jour(19, 20, 30))])
        # Semaine : de 10 à 30 °C.
        self.assertEqual(_plages(html), [(0.0, 50.0), (0.0, 100.0), (50.0, 50.0)])

    def test_la_barre_de_pluie_a_un_plafond_d_au_moins_cinq_millimetres(self) -> None:
        (html,) = _rendre([_jours(_jour(17, 10, 20, 0.4), _jour(18, 10, 20, 5), _jour(19, 10, 20, 0))])
        self.assertEqual(_pluies(html), [8.0, 100.0])  # 0,4 / 5 ; 5 / 5 ; pas de barre à 0 mm

    def test_une_semaine_peu_arrosee_ne_remplit_jamais_la_barre(self) -> None:
        (html,) = _rendre([_jours(_jour(17, 10, 20, 0.4), _jour(18, 10, 20, 1))])
        self.assertEqual(_pluies(html), [8.0, 20.0])

    def test_le_plus_gros_jour_remplit_la_barre_quand_il_depasse_cinq_millimetres(self) -> None:
        (html,) = _rendre([_jours(_jour(17, 10, 20, 12), _jour(18, 10, 20, 6))])
        self.assertEqual(_pluies(html), [100.0, 50.0])

    def test_un_jour_sans_temperature_garde_sa_place_sans_barre(self) -> None:
        (html,) = _rendre([_jours(_jour(17, 10, 20), _jour(18, None, 25), _jour(19, 12, 22))])
        self.assertEqual(len(_plages(html)), 2)
        self.assertEqual(html.count('class="plage-t vide-plage"'), 1)
        self.assertEqual(html.count("<li>"), 3)

    def test_une_semaine_sans_ecart_de_temperature_ne_divise_pas_par_zero(self) -> None:
        (html,) = _rendre([_jours(_jour(17, 15, 15), _jour(18, 15, 15))])
        self.assertEqual(_plages(html), [])
        self.assertEqual(html.count('class="plage-t vide-plage"'), 2)
        self.assertNotIn("NaN", html)
        self.assertNotIn("Infinity", html)

    def test_la_plage_a_un_texte_alternatif_avec_les_deux_temperatures(self) -> None:
        (html,) = _rendre([_jours(_jour(17, 11.4, 22.2), _jour(18, 12, 25))])
        self.assertIn('aria-label="de 11 à 22 degrés"', html)


def _heure(i: int, temperature: float | None, pluie: float = 0) -> dict:
    h: dict = {"datetime": f"2026-09-17T{i:02d}:00:00+02:00"}
    if temperature is not None:
        h["temperature"] = temperature
    if pluie:
        h["precipitation"] = pluie
    return h


@unittest.skipUnless(NODE, "Node n'est pas installé")
class CourbeHeuresTests(unittest.TestCase):
    def _courbe(self, heures: list[dict]) -> str:
        (html,) = _rendre([{"quoi": "courbe", "heures": heures}])
        return html

    def test_pas_de_courbe_avec_moins_de_trois_temperatures(self) -> None:
        self.assertEqual(self._courbe([]), "")
        self.assertEqual(self._courbe([_heure(1, 10), _heure(2, 11)]), "")
        self.assertEqual(self._courbe([_heure(1, 10), _heure(2, None), _heure(3, 12), _heure(4, None)]), "")

    def test_la_courbe_a_un_point_par_heure_connue_et_ses_bornes(self) -> None:
        html = self._courbe([_heure(1, 10), _heure(2, 14), _heure(3, None), _heure(4, 12)])
        (points,) = re.findall(r'<polyline class="t-ligne" points="([^"]+)"', html)
        self.assertEqual(len(points.split()), 3)
        self.assertIn("<span>10°</span><span>14°</span>", html)
        self.assertIn("de 10 à 12 degrés", html)

    def test_les_barres_de_pluie_suivent_la_pluie_annoncee_et_la_plus_forte_est_la_plus_haute(self) -> None:
        html = self._courbe([_heure(1, 10), _heure(2, 11, 0.2), _heure(3, 12, 0.8), _heure(4, 12)])
        hauteurs = [float(x) for x in re.findall(r'class="pluie-b"[^>]* height="([\d.]+)"', html)]
        self.assertEqual(len(hauteurs), 2)
        # Échelle plancher à 1 mm : 0,8 mm = 80 % de 40, 0,2 mm = 20 %.
        self.assertAlmostEqual(hauteurs[1], 32.0, places=1)
        self.assertAlmostEqual(hauteurs[0], 8.0, places=1)

    def test_au_dela_d_un_millimetre_la_plus_forte_pluie_remplit_la_zone_des_barres(self) -> None:
        html = self._courbe([_heure(1, 10), _heure(2, 11, 2), _heure(3, 12, 4), _heure(4, 12)])
        hauteurs = [float(x) for x in re.findall(r'class="pluie-b"[^>]* height="([\d.]+)"', html)]
        self.assertEqual(hauteurs, [20.0, 40.0])

    def test_aucune_barre_sans_pluie_et_aucune_valeur_invalide(self) -> None:
        html = self._courbe([_heure(1, 10), _heure(2, 11), _heure(3, 12)])
        self.assertNotIn('class="pluie-b"', html)
        self.assertNotIn("NaN", html)
        self.assertNotIn("Infinity", html)

    def test_une_temperature_constante_dessine_quand_meme_une_courbe(self) -> None:
        html = self._courbe([_heure(1, 15), _heure(2, 15), _heure(3, 15)])
        self.assertIn('class="t-ligne"', html)
        self.assertNotIn("NaN", html)


@unittest.skipUnless(NODE, "Node n'est pas installé")
class ProduitConseilleTests(unittest.TestCase):
    def _produit(self, etat: str, score: object) -> str:
        (html,) = _rendre([{"quoi": "produits", "etat": etat, "intervention": {"product_name": "Humuslight", "score": score}}])
        return html

    def test_la_pertinence_est_dessinee_en_barre_avec_son_texte(self) -> None:
        html = self._produit("recommande", 71)
        self.assertIn('class="pertinence" role="img" aria-label="Pertinence 71 %"', html)
        self.assertIn('<i style="width:71%">', html)
        self.assertIn("pertinence 71 %", html)

    def test_pas_de_barre_sans_pertinence_positive(self) -> None:
        for score in (0, None, -5):
            with self.subTest(score=score):
                self.assertNotIn('class="pertinence"', self._produit("recommande", score))

    def test_la_barre_ne_depasse_jamais_cent_pour_cent(self) -> None:
        self.assertIn('<i style="width:100%">', self._produit("recommande", 140))

    def test_un_produit_a_preparer_garde_sa_variante(self) -> None:
        self.assertIn("produit-bandeau a-preparer", self._produit("a_preparer", 40))
        self.assertNotIn("a-preparer", self._produit("recommande", 40))

    def test_sans_intervention_il_n_y_a_ni_bandeau_ni_barre(self) -> None:
        html = self._produit("non_requis", 80)
        self.assertNotIn("produit-bandeau", html)
        self.assertNotIn('class="pertinence"', html)
        self.assertIn("Aucun produit conseillé pour l'instant.", html)


if __name__ == "__main__":
    unittest.main()
