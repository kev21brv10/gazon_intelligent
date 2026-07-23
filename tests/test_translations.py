"""Cohérence des fichiers de traduction.

Trois défauts silencieux avaient cours et échappaient à la CI :
  - la clé `reconfigure` était DUPLIQUÉE dans les 5 fichiers ; un parseur JSON n'en garde
    qu'une, donc le contenu perdu ne se voyait nulle part ;
  - les 7 champs tondeuse du formulaire, présents dans le schéma du config flow et dans
    `strings.json`, n'étaient traduits dans AUCUNE langue (libellés bruts affichés) ;
  - `config.error.entity_not_found`, pourtant levée par config_flow.py, manquait dans
    en / de / es / nl.

Ces tests comparent chaque fichier à `strings.json`, qui fait référence.
"""

from __future__ import annotations

import collections
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT / "custom_components" / "gazon_intelligent"
STRINGS = PACKAGE_DIR / "strings.json"
TRANSLATIONS = PACKAGE_DIR / "translations"
LANGUAGES = ("fr", "en", "de", "es", "nl")


def _flatten(obj, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    if isinstance(obj, dict):
        for key, value in obj.items():
            keys.add(prefix + key)
            keys |= _flatten(value, prefix + key + ".")
    return keys


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _duplicate_keys(path: Path) -> list[str]:
    """Détecte les clés répétées dans un même objet — invisibles après parsing."""
    duplicates: list[str] = []

    def hook(pairs):
        counts = collections.Counter(key for key, _ in pairs)
        duplicates.extend(key for key, count in counts.items() if count > 1)
        return dict(pairs)

    json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=hook)
    return duplicates


class TranslationConsistencyTests(unittest.TestCase):
    def test_aucune_cle_dupliquee(self) -> None:
        for path in (STRINGS, *(TRANSLATIONS / f"{lang}.json" for lang in LANGUAGES)):
            with self.subTest(fichier=path.name):
                self.assertEqual(_duplicate_keys(path), [])

    def test_chaque_langue_couvre_strings_json(self) -> None:
        reference = _flatten(_load(STRINGS))
        for lang in LANGUAGES:
            with self.subTest(langue=lang):
                keys = _flatten(_load(TRANSLATIONS / f"{lang}.json"))
                self.assertEqual(sorted(reference - keys), [], "clés manquantes")

    def test_aucune_cle_orpheline(self) -> None:
        reference = _flatten(_load(STRINGS))
        for lang in LANGUAGES:
            with self.subTest(langue=lang):
                keys = _flatten(_load(TRANSLATIONS / f"{lang}.json"))
                self.assertEqual(sorted(keys - reference), [], "clés sans référence")

    def test_les_champs_tondeuse_sont_traduits(self) -> None:
        champs = (
            "entite_tondeuse",
            "capteur_tondeuse_batterie",
            "capteur_tondeuse_en_charge",
            "capteur_tondeuse_erreur",
            "capteur_tondeuse_hauteur_coupe",
            "capteur_tondeuse_pluie",
            "capteur_tondeuse_prochain_depart",
        )
        for lang in LANGUAGES:
            data = _load(TRANSLATIONS / f"{lang}.json")
            for section in (
                data["config"]["step"]["sensors"]["data"],
                data["options"]["step"]["user"]["data"],
            ):
                for champ in champs:
                    with self.subTest(langue=lang, champ=champ):
                        self.assertTrue(str(section.get(champ) or "").strip())

    def test_les_erreurs_du_config_flow_sont_traduites(self) -> None:
        # config_flow.py lève entity_not_found et invalid_instance_slug.
        for lang in LANGUAGES:
            errors = _load(TRANSLATIONS / f"{lang}.json")["config"]["error"]
            for code in ("entity_not_found", "invalid_instance_slug"):
                with self.subTest(langue=lang, code=code):
                    self.assertTrue(str(errors.get(code) or "").strip())


if __name__ == "__main__":
    unittest.main()
