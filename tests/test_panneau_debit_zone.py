"""Le débit d'une zone se règle depuis la liste des zones, avec ce que la valeur change.

Même valeur que Réglages → Installation → Arroseurs : une seule entité derrière (`number.set_value`).
Ce qui est figé ici : la durée annoncée pour la dose du jour, l'avertissement au-delà de 30 % d'écart,
la zone mise à 0 (plus arrosée), le calcul d'un test plus court qu'une heure, le bouton qui ne part pas
sans changement ni hors des bornes de l'entité, et le lien réservé aux administrateurs.
Le vrai JS est exécuté dans Node, comme les autres tests du panneau.
"""

from __future__ import annotations

import json
from pathlib import Path
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
  const etats = { debit_zone_1: c.actuel ?? 14, objectif: c.objectif ?? 0 };
  p._s = (cle) => (cle in etats ? String(etats[cle]) : undefined);
  p._entite = (cle) => (cle === "debit_zone_1" ? { attributes: c.max === undefined ? {} : { max: c.max } } : undefined);
  p._estAdmin = () => c.admin !== false;
  p._donnees = { entites: c.sansEntite ? {} : { debit_zone_1: "number.debit_1" } };
  const d = { nom: "debit", numero: "1", valeur: c.valeur, duree: c.duree, haut: c.haut };
  if (c.quoi === "lien") return p._debitLienHtml({ numero: 1 }, c.debit === undefined ? 14 : c.debit);
  if (c.quoi === "calcul") return p._debitCalculHtml(d);
  if (c.quoi === "bouton") return JSON.stringify(p._debitBouton(d));
  if (c.quoi === "corps") return p._debitDialogueCorps(d);
  return p._debitEffetHtml(d);
});
process.stdout.write(JSON.stringify(sorties));
"""


def _rendre(cas: list[dict]) -> list[str]:
    assert NODE
    sortie = subprocess.run(
        [NODE, "-e", SCRIPT], input=json.dumps({"chemin": str(PANNEAU), "cas": cas}),
        capture_output=True, text=True, check=True, timeout=60,
    )
    return [html.replace(" ", " ") for html in json.loads(sortie.stdout)]


@unittest.skipUnless(NODE, "Node n'est pas installé")
class DebitZoneTests(unittest.TestCase):
    def test_l_effet_dit_la_duree_pour_la_dose_du_jour_avec_l_ancienne_valeur(self) -> None:
        (html,) = _rendre([{"valeur": "17"}])
        self.assertIn("Pour 3 mm d'eau, cette zone arrosera <b>11 min</b> (avant : 13 min)", html)
        self.assertNotIn("note alerte", html)

    def test_l_effet_utilise_l_objectif_du_jour_quand_il_existe(self) -> None:
        (html,) = _rendre([{"valeur": "14", "objectif": 5}])
        self.assertIn("Pour 5 mm d'eau", html)
        self.assertIn("<b>21 min</b>", html)

    def test_un_ecart_de_plus_de_30_pour_cent_avertit_et_pas_avant(self) -> None:
        sous, au_dessus = _rendre([{"valeur": "18"}, {"valeur": "19"}])
        self.assertNotIn("plus de 30 %", sous)  # 28,6 %
        self.assertIn("Le débit change de plus de 30 %", au_dessus)  # 35,7 %

    def test_zero_veut_dire_zone_pas_utilisee(self) -> None:
        (html,) = _rendre([{"valeur": "0"}])
        self.assertIn("Zone pas utilisée : elle ne sera plus arrosée", html)
        self.assertNotIn("arrosera", html)

    def test_une_saisie_invalide_ne_promet_aucune_duree(self) -> None:
        texte, negatif = _rendre([{"valeur": "abc"}, {"valeur": "-3"}])
        for html in (texte, negatif):
            self.assertIn("Saisir un nombre positif", html)
            self.assertNotIn("arrosera", html)

    def test_la_virgule_francaise_est_comprise(self) -> None:
        (html,) = _rendre([{"valeur": "17,5"}])
        self.assertIn("<b>10 min</b>", html)

    def test_le_calcul_ramene_un_test_court_a_l_heure(self) -> None:
        trente, dix, une_heure, vide = _rendre([
            {"quoi": "calcul", "duree": "30", "haut": "11"},
            {"quoi": "calcul", "duree": "10", "haut": "2"},
            {"quoi": "calcul", "duree": "60", "haut": "14"},
            {"quoi": "calcul", "duree": "30", "haut": ""},
        ])
        self.assertIn("<b>22 mm par heure</b>", trente)
        self.assertIn('data-debit-utiliser="22"', trente)
        self.assertIn("<b>12 mm par heure</b>", dix)
        self.assertIn("<b>14 mm par heure</b>", une_heure)
        self.assertIn("Renseigner la hauteur d'eau mesurée", vide)
        self.assertNotIn("data-debit-utiliser", vide)

    def test_le_bouton_ne_part_pas_sans_changement_ni_hors_des_bornes(self) -> None:
        inchange, change, zero, trop, invalide, borne = _rendre([
            {"quoi": "bouton", "valeur": "14"},
            {"quoi": "bouton", "valeur": "17"},
            {"quoi": "bouton", "valeur": "0"},
            {"quoi": "bouton", "valeur": "80"},
            {"quoi": "bouton", "valeur": "abc"},
            {"quoi": "bouton", "valeur": "31", "max": 30},
        ])
        self.assertTrue(json.loads(inchange)["off"])
        self.assertEqual(json.loads(change), {"texte": "Enregistrer 17 mm/h", "off": False})
        self.assertEqual(json.loads(zero), {"texte": "Enregistrer : zone pas utilisée", "off": False})
        self.assertTrue(json.loads(trop)["off"])  # borne par défaut : 60 mm/h
        self.assertTrue(json.loads(invalide)["off"])
        self.assertTrue(json.loads(borne)["off"])  # borne de l'entité : 30

    def test_le_lien_n_existe_que_pour_un_administrateur_avec_une_entite(self) -> None:
        admin, lecteur, sans_entite, sans_debit = _rendre([
            {"quoi": "lien"},
            {"quoi": "lien", "admin": False},
            {"quoi": "lien", "sansEntite": True},
            {"quoi": "lien", "debit": None},
        ])
        self.assertIn('data-dialogue="debit" data-zone="1"', admin)
        self.assertIn("14 mm/h", admin)
        self.assertNotIn("<button", lecteur)
        self.assertEqual(lecteur, "14 mm/h · ")
        self.assertNotIn("<button", sans_entite)
        self.assertIn("Débit à régler", sans_debit)

    def test_la_fenetre_est_branchee_a_la_saisie_a_la_validation_et_au_lien(self) -> None:
        source = PANNEAU.read_text(encoding="utf-8")
        self.assertIn('if (this._dialogue?.nom === "debit" && this._fenetre.contains(cible))', source)
        self.assertIn('appel = ["number", "set_value", { entity_id: entityId, value: v }];', source)
        self.assertIn("numero: dialogue.dataset.zone", source)
        self.assertIn('bouton.dataset.debitUtiliser !== undefined && this._dialogue?.nom === "debit"', source)
        # Une zone inconnue ne s'ouvre pas : on n'écrit jamais une entité qui n'existe pas.
        self.assertIn("if (!numero || !this._donnees?.entites?.[`debit_zone_${numero}`]) return;", source)

    def test_le_corps_de_la_fenetre_contient_les_trois_etapes_du_test_et_les_champs(self) -> None:
        (html,) = _rendre([{"quoi": "corps", "duree": "60"}])
        for attendu in ("Poser un verre à fond plat", "0 = zone pas utilisée", 'id="dlg-debit"', 'id="dlg-debit-haut"', "data-debit-effet"):
            self.assertIn(attendu, html)
        self.assertIn('<option value="60" selected>', html)


if __name__ == "__main__":
    unittest.main()
