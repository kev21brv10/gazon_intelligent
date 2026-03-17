# 🌱 Gazon Intelligent

Intégration Home Assistant pour gérer les modes gazon :

- Normal
- Sursemis
- Traitement
- Fertilisation
- Biostimulant
- Agent Mouillant
- Scarification
- Hivernage

## Fonctionnalités 🚀

- Configuration UI simple (formulaire d’entités).
- Sélection des zones, capteurs et débits pour calculer l’arrosage.
- Calcul automatique de l'objectif d'arrosage selon le mode et la météo.
- Indicateurs clairs : autorisation tonte, arrosage auto, arrosage conseillé.
- Gestion complète des phases (durées, dates d’action, dates de fin).

## Installation simple 🧰

1. Copier `custom_components/gazon_intelligent` dans le dossier `custom_components` de Home Assistant (ou installer via HACS si tu publies le repo).
2. Redémarrer Home Assistant.
3. Dans *Paramètres → Appareils et services → Ajouter une intégration*, choisir **Gazon Intelligent**.

## Configuration (ce qui est demandé) 🛠️

- Zone 1 (obligatoire) + Zones 2 à 5 (optionnelles) : ce sont tes `switch` d’électrovannes.
- Tondeuse (optionnel, domaine `lawn_mower`).
- Capteur pluie 24h (obligatoire), pluie demain J+1 (prévision, pas la pluie du jour) / température / ETP / humidité extérieure (optionnels).
- Débit par zone (mm/h) : combien de millimètres d’eau la zone apporte en 1 heure. Si tu ne sais pas, laisse 60 mm/h (≈ 1 mm/min) et ajuste après mesure.

## Entités créées 📡

- Sélecteur de mode gazon (Normal, Sursemis, Traitement, Fertilisation, Biostimulant, Agent Mouillant, Scarification, Hivernage).
- Capteur `Objectif d'arrosage` (mm).
- Capteur `Jours restants de la phase`.
- Capteur `ETP estimée` (mm/j) : capteur ETP si présent, sinon estimation simple (température + pluie).
- Capteur `Humidité extérieure` (%) si fourni.
- Capteur `Arrosage conseillé` : `auto` / `personnalise` / `interdit` selon le mode.
- Binaire `Tonte autorisée`.
- Binaire `Arrosage automatique autorisé` (à combiner dans tes automations).
- Bouton `Repasser en mode normal`.
- Bouton `Date action = aujourd'hui` : fixe rapidement la date d'action si tu mets la phase en retard.

Reconfigurer plus tard 🔄  
- Menu Options de l'intégration : change zones, capteurs, débits quand tu veux sans recréer l’entrée.

Toutes les entités sont rattachées à un appareil « Gazon Intelligent » pour un renommage persistant.

## Versions / Releases 🏷️
- Voir `CHANGELOG.md` (dernière : 0.3.7).
- Le manifest est aligné ; crée une release taguée (ex. v0.3.7) pour HACS.
- Mode et date d'action sont persistés entre redémarrages.

## Services ⚙️

- `gazon_intelligent.set_mode` (`mode` parmi la liste ci-dessus).
- `gazon_intelligent.set_date_action` (date optionnelle `AAAA-MM-JJ`; si vide = aujourd'hui).
- `gazon_intelligent.reset_mode` (revient en Normal).
- `gazon_intelligent.start_manual_irrigation` (`objectif_mm` float, 0‑30).
- `gazon_intelligent.start_auto_irrigation` (objectif optionnel, utilise l'objectif calculé si omis). Lance chaque zone en séquence en convertissant l'objectif mm en durée selon le débit renseigné (mm/h).

Objectif en mode Normal 💧  
- Pensé pour 3 arrosages/sem : 8.3 mm par passage (~25 mm/sem).  
- Si tu arroses 2×/sem : mets `objectif_mm: 12.5` dans ton automation `start_auto_irrigation`.

## Événement

`gazon_intelligent_manual_irrigation_requested` émis lors de `start_manual_irrigation` avec `objectif_mm`, `mode`, `date_action`.

### Exemple d'automatisation pour déclencher une scène d'arrosage

```yaml
alias: Arrosage manuel gazon
mode: single
trigger:
  - platform: event
    event_type: gazon_intelligent_manual_irrigation_requested
action:
  - service: gazon_intelligent.start_auto_irrigation
    data: {}

# Variante : imposer 2 mm d'eau
#  - service: gazon_intelligent.start_auto_irrigation
#    data:
#      objectif_mm: 2
```

### Exemple : créer un cumul pluie 24h simple

Si tu n'as qu'un capteur de pluie horaire ou instantanée (ex. `sensor.pluie_horaire`), crée un cumul 24h glissant avec `statistics` :

```yaml
template:
  - sensor:
      - name: "Pluie 24h"
        unit_of_measurement: "mm"
        state: "{{ states('sensor.pluie_24h_stats') }}"
        availability: "{{ states('sensor.pluie_24h_stats') not in ['unknown','unavailable','none'] }}"

sensor:
  - platform: statistics
    name: "Pluie 24h stats"
    entity_id: sensor.pluie_horaire
    sampling_size: 200
    max_age:
      hours: 24
    state_characteristic: sum
```

Puis utilise `sensor.pluie_24h` comme `capteur_pluie_24h` dans l'intégration.
