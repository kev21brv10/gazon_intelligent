# Référence d'architecture

La référence d'architecture de Gazon Intelligent est un **artefact vivant**, republié à chaque
changement de code :

<https://claude.ai/code/artifact/d2f5f3cc-d931-4d09-a8de-69502116f1de>

Elle décrit l'intégration en neuf onglets — vue d'ensemble, arrosage, tonte, phases & produits,
stress & budget, capteurs, services & entités, arbitrages, santé du code — et reste vérifiée sur le
code réel. L'onglet « Santé du code » sert de point d'entrée aux dettes connues et aux pièges à ne
pas réintroduire. Les règles de mise à jour vivent dans [CLAUDE.md](../CLAUDE.md), section
« Référence d'architecture ».

⚠️ **L'artefact est privé** : le lien ne s'ouvre qu'avec le compte de son propriétaire.

## Ce qui fait foi dans le dépôt

| Question | Où regarder |
| --- | --- |
| Ce qu'une version a changé, et pourquoi | [CHANGELOG.md](../CHANGELOG.md) |
| Version actuelle, installation, configuration | [README.md](../README.md) |
| Attributs publics des entités | [docs/public-attribute-contract.md](public-attribute-contract.md) |
| Comportement réel | le code et les tests (`custom_components/gazon_intelligent/`, `tests/`) |

## Pourquoi il n'y a plus de copie HTML ici

`docs/reference-architecture.html` était une copie figée, committée le 04/09/2026 avec un en-tête
en 0.74.0. Elle n'était plus régénérée et contredisait le code : elle annonçait encore une fenêtre
de tonte idéale de 10 h à 12 h et une fin de soirée 90 min avant le coucher, alors que la 0.90.0
retient 10 h – 14 h et une fenêtre du soir allant de coucher − 5 h à coucher + 30 min. Rien dans le
dépôt ne la référençait.

Elle a été retirée le 16/09/2026, sur décision de Kévin. **Ne pas recommitter de copie figée** :
une référence fausse est pire que pas de référence.
