"""La police condensée du panneau est embarquée, licenciée, et ne charge rien d'un site tiers."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
DOSSIER = ROOT / "custom_components" / "gazon_intelligent" / "frontend"
PANNEAU = DOSSIER / "gazon-intelligent-panel.js"
LICENCE = DOSSIER / "OFL-barlow-condensed.txt"
NODE = shutil.which("node")

SCRIPT = r"""
const fs = require("fs");
const vm = require("vm");
const { chemin } = JSON.parse(fs.readFileSync(0, "utf8"));
const ajouts = [];
const ctx = {
  HTMLElement: class {},
  customElements: { get: () => undefined, define: (nom, classe) => { ctx.Classe = classe; } },
  console, structuredClone,
  document: {
    head: { appendChild: (n) => { ajouts.push(n); ctx.document._ids[n.id] = n; } },
    _ids: {},
    getElementById(id) { return this._ids[id] || null; },
    createElement: () => ({}),
  },
};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(chemin, "utf8"), ctx);
vm.runInContext("installerPolice(); installerPolice();", ctx);
process.stdout.write(JSON.stringify({ n: ajouts.length, id: ajouts[0]?.id, css: ajouts[0]?.textContent }));
"""


class PoliceEmbarqueeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = PANNEAU.read_text(encoding="utf-8")

    def test_la_licence_accompagne_la_police(self) -> None:
        texte = LICENCE.read_text(encoding="utf-8")
        self.assertIn("SIL OPEN FONT LICENSE Version 1.1", texte)
        self.assertIn("Barlow Project Authors", texte)
        # Le fichier du panneau renvoie à cette licence, comme l'exige la SIL OFL.
        self.assertIn("OFL-barlow-condensed.txt", self.source)

    def test_le_fichier_embarque_est_bien_la_police_annoncee(self) -> None:
        brut = re.search(r'const POLICE_CONDENSEE_BASE64 = "([A-Za-z0-9+/=]+)";', self.source)
        self.assertIsNotNone(brut)
        octets = base64.b64decode(brut.group(1), validate=True)
        self.assertEqual(octets[:4], b"wOF2")
        annonce = re.search(r"SHA-256 ([0-9a-f]{64})", self.source)
        self.assertIsNotNone(annonce)
        self.assertEqual(hashlib.sha256(octets).hexdigest(), annonce.group(1))
        # Une police de page, pas un fichier de plusieurs centaines de Ko.
        self.assertLess(len(octets), 40_000)

    def test_aucune_police_n_est_chargee_depuis_un_site_tiers(self) -> None:
        for interdit in ("fonts.googleapis.com", "fonts.gstatic.com", "use.typekit", "cdn.jsdelivr", "@import url("):
            self.assertNotIn(interdit, self.source)
        for url in re.findall(r"src:\s*url\(([^)]{0,40})", self.source):
            self.assertTrue(url.startswith("data:font/woff2"), url)

    def test_la_police_s_installe_au_branchement_de_la_page(self) -> None:
        corps = self.source.split("  connectedCallback() {", 1)[1][:200]
        self.assertIn("installerPolice();", corps)

    @unittest.skipUnless(NODE, "Node n'est pas installé")
    def test_l_injection_se_fait_une_seule_fois_et_declare_la_bonne_famille(self) -> None:
        sortie = subprocess.run(
            [NODE, "-e", SCRIPT], input=json.dumps({"chemin": str(PANNEAU)}),
            capture_output=True, text=True, check=True, timeout=60,
        )
        resultat = json.loads(sortie.stdout)
        self.assertEqual(resultat["n"], 1)
        self.assertEqual(resultat["id"], "gazon-intelligent-police")
        self.assertIn('font-family: "Barlow Condensed"', resultat["css"])
        self.assertIn("font-weight: 600", resultat["css"])

    def test_la_pile_de_polices_garde_un_repli(self) -> None:
        pile = re.search(r"--gz-police-aff: ([^;]+);", self.source)
        self.assertIsNotNone(pile)
        self.assertTrue(pile.group(1).startswith('"Barlow Condensed"'))
        self.assertIn("sans-serif", pile.group(1))


if __name__ == "__main__":
    unittest.main()
