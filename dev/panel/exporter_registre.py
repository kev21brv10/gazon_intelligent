"""Prépare l'aperçu local de la page « Gazon » à partir du code de l'intégration.

    python3 dev/panel/exporter_registre.py

Écrit trois fichiers, ignorés par git :
    · `registre.json` : le registre des réglages (`reglages.py`) ;
    · `services.json` : les champs acceptés par chaque service de l'intégration (`services.yaml`),
      pour que la maison simulée refuse un champ inconnu comme le fait Home Assistant ;
    · `sources.json` : les entrées météo et jardin (`sources.py`), pour l'onglet Météo.

`reglages.py` est chargé par son chemin : importer le paquet de l'intégration exigerait Home
Assistant, et ce module n'a aucune dépendance. `sources.py` lit `const.py` : le paquet est
simulé le temps de l'import, sans exécuter son `__init__`.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import sys
import types
from pathlib import Path

import yaml

ICI = Path(__file__).resolve().parent
INTEGRATION = ICI.parents[1] / "custom_components" / "gazon_intelligent"


def _registre() -> dict:
    spec = importlib.util.spec_from_file_location("gazon_reglages", INTEGRATION / "reglages.py")
    if spec is None or spec.loader is None:
        raise SystemExit("Impossible de charger reglages.py")
    module = importlib.util.module_from_spec(spec)
    # Les dataclasses relisent leur module dans `sys.modules` pendant leur construction.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.exporter()


def _sources() -> list[dict]:
    racine = str(INTEGRATION.parents[1])
    if racine not in sys.path:
        sys.path.insert(0, racine)
    # `const.py` lit `phases.py`, qui lit l'horloge de Home Assistant : une horloge simple suffit.
    try:
        importlib.import_module("homeassistant.util.dt")
    except ImportError:
        from datetime import datetime, timezone

        for nom in ("homeassistant", "homeassistant.util", "homeassistant.util.dt"):
            module = sys.modules.setdefault(nom, types.ModuleType(nom))
            if nom != "homeassistant.util.dt":
                module.__path__ = []  # type: ignore[attr-defined]
        horloge = sys.modules["homeassistant.util.dt"]
        horloge.now = lambda: datetime.now(timezone.utc)  # type: ignore[attr-defined]
        horloge.utcnow = lambda: datetime.now(timezone.utc)  # type: ignore[attr-defined]
        sys.modules["homeassistant.util"].dt = horloge  # type: ignore[attr-defined]
    for nom, chemin in (("custom_components", INTEGRATION.parent), ("custom_components.gazon_intelligent", INTEGRATION)):
        if nom not in sys.modules:
            paquet = types.ModuleType(nom)
            paquet.__path__ = [str(chemin)]  # type: ignore[attr-defined]
            sys.modules[nom] = paquet
    return importlib.import_module("custom_components.gazon_intelligent.sources").exporter()


def _services() -> dict[str, list[str]]:
    """Champs acceptés par service. `entity_id` l'est partout : c'est la cible de l'instance."""
    definitions = yaml.safe_load((INTEGRATION / "services.yaml").read_text(encoding="utf-8")) or {}
    return {
        nom: sorted({"entity_id", *((definition or {}).get("fields") or {})})
        for nom, definition in definitions.items()
    }


def _ecrire(nom: str, contenu: dict) -> None:
    cible = ICI / nom
    cible.write_text(json.dumps(contenu, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def main() -> None:
    registre = _registre()
    services = _services()
    sources = _sources()
    _ecrire("registre.json", registre)
    _ecrire("services.json", services)
    _ecrire("sources.json", sources)
    print(f"{len(registre['reglages'])} réglages, {len(services)} services, {len(sources)} entrées → dev/panel/")


if __name__ == "__main__":
    main()
