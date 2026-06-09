# CLAUDE.md — Conventions du dépôt Gazon Intelligent

Guide de travail pour Claude (et tout contributeur) sur ce dépôt.
Objectif : un GitHub propre et traçable, jamais de `main` cassé.

## Workflow Git (obligatoire)

**Jamais de commit ni de push direct sur `main`.** Toujours passer par une branche + PR :

1. Brancher depuis `main` à jour, avec un préfixe explicite :
   - `feat/<sujet>` — nouvelle fonctionnalité
   - `fix/<sujet>` — correction de bug
   - `refactor/<sujet>` — refactor sans changement de comportement
   - `chore/<sujet>` — maintenance, outillage, hygiène
   - `docs/<sujet>` — documentation
   - `release/<x.y.z>` — préparation d'une release
2. Commits **Conventional Commits** (`feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`),
   sujet à l'impératif, le *pourquoi* dans le corps.
3. Ouvrir une **PR** vers `main` avec une description claire du diff.
4. **Attendre la CI verte** (`unit-tests`, `hassfest`, `lint`, `type-check`) avant tout merge.
5. **Squash merge** — l'historique linéaire est imposé sur `main`.
6. **Supprimer la branche** après merge.

`main` est protégé : PR obligatoire, 0 approbation requise (dépôt solo),
4 status checks requis, historique linéaire, résolution des conversations requise.
Ne pas bypasser la protection.

## Releases (SemVer)

Sur une branche `release/<x.y.z>` :

1. Bump `custom_components/gazon_intelligent/manifest.json`.
2. Ajouter l'entrée en tête de `CHANGELOG.md` — format des entrées existantes :
   `## x.y.z`, ligne d'intro avec le nombre de tests verts, puis bullets `**Catégorie** : …`.
3. Mettre à jour la section « version actuelle » du `README.md` (le badge suit le tag).
4. PR → CI verte → squash merge.
5. Tag `vx.y.z` sur `main` + release GitHub (notes reprises du CHANGELOG).

Ne jamais inventer de numéro de version dans les textes : la source de vérité est `manifest.json`.

## Qualité

- Lancer `python -m pytest tests/ -q` avant d'ouvrir une PR (doit être vert).
- La logique métier est testable hors Home Assistant : `decision_*.py`, `guidance.py`,
  `water.py`, `phases.py`, `watering_policy.py`.
- Ne pas réactiver `USE_DEPLETION_LOGIC` (désactivée volontairement,
  voir le commentaire en tête de `decision_watering.py`).
- Ne pas toucher au fill cap réserve de `_profile_for_normal` (`guidance.py`)
  sans raison agronomique explicite.

## Outillage

- Tests : `unittest` exécuté via `pytest`, dans `tests/`.
- CI : workflow **Validate** (Hassfest, Ruff, mypy, tests unitaires), sur chaque push et PR.
