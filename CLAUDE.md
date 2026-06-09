# CLAUDE.md — Spécifique Gazon Intelligent

> La discipline Git/PR/releases **générique** (branches, Conventional Commits,
> squash merge, SemVer, hygiène) vit dans le `CLAUDE.md` global (`~/.claude/CLAUDE.md`).
> Ce fichier ne couvre que le **spécifique à ce projet**.

## Protection de `main` (ce repo)

- PR obligatoire · 0 approbation requise (dépôt solo) · historique linéaire · résolution des conversations requise.
- **4 status checks CI bloquants** : `unit-tests`, `hassfest`, `lint`, `type-check` (workflow **Validate**).

## Releases

- Source de vérité de la version : `custom_components/gazon_intelligent/manifest.json`
  (ne jamais inventer un numéro dans les textes).
- Entrée `CHANGELOG.md` en tête, format des entrées existantes :
  `## x.y.z`, ligne d'intro avec le nombre de tests verts, puis bullets `**Catégorie** : …`.
- Mettre à jour la section « version actuelle » du `README.md` (le badge suit le tag).

## Qualité

- `python -m pytest tests/ -q` doit être vert avant toute PR.
- Logique métier testable hors Home Assistant : `decision_*.py`, `guidance.py`,
  `water.py`, `phases.py`, `watering_policy.py`.
- Ne pas réactiver `USE_DEPLETION_LOGIC` (désactivée volontairement,
  voir le commentaire en tête de `decision_watering.py`).
- Ne pas toucher au fill cap réserve de `_profile_for_normal` (`guidance.py`)
  sans raison agronomique explicite.
- Le flow Node-RED (`docs/node_red/`) est une config perso, hors dépôt (gitignored).

## Outillage

- Tests : `unittest` exécuté via `pytest`, dans `tests/`.
- CI : workflow **Validate** (Hassfest, Ruff, mypy, tests unitaires), sur chaque push et PR.
