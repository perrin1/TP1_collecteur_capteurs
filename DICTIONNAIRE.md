# Dictionnaire des données — TP1

Trois sources décrivent la même réalité avec des conventions différentes.
**C'est tout l'enjeu de la normalisation.**

---

## Station A — `data/station_A_releves.csv`

Séparateur `;` · décimale `,` · encodage UTF-8 **avec BOM** · 4 245 lignes

| Colonne | Type | Notes |
|---|---|---|
| `releve_id` | texte | `A-000000` à `A-004199`. **Non unique** : 45 doublons exacts injectés |
| `Station` | texte | `STA-01`, `STA-02`, `STA-03`, `STA-07`. Casse parfois en minuscules |
| `DATE_HEURE` | texte | **Trois formats mélangés** : `AAAA-MM-JJ HH:MM:SS`, `JJ/MM/AAAA HH:MM`, ISO 8601 |
| `grandeur` | texte | Parfois en MAJUSCULES (~3 %) |
| `Valeur` | texte | **Décimale virgule**, à convertir |
| `unite` | texte | `degC`, `degF`, `pct`, `mm`, `dmm`, `dS_m` |
| `capteur_serie` | texte | Numéro de série, non exploité |

**Unités rencontrées :** `degC` et `degF` pour la température (~7 % en Fahrenheit,
**correctement annoncé**) · `mm` et `dmm` pour la pluviométrie (`dmm` = 1/10 mm, ~12 %).

**Fuseau :** tous les horodatages sont en UTC, mais le format ISO est seul à le déclarer.

---

## Station B — `data/station_B_releves.json`

Structure imbriquée · 2 576 mesures immédiates + 1 224 différées

```json
{
  "schema": "station-b/v2",
  "genere_le": "...",
  "mesures":           [ { ... } ],
  "mesures_differees": [ { ... } ]
}
```

Un relevé :

| Chemin | Type | Notes |
|---|---|---|
| `id` | texte | `B-000000`… |
| `station.code` | texte | `STB-11`, `STB-12`, `STB-13` — et `STB-99` (~1,2 %) |
| `station.firmware` | texte | Non exploité |
| `ts` | texte | ISO 8601 |
| `fuseau` | texte | `UTC` ou `Africa/Porto-Novo` — **à appliquer** |
| `mesure.type` | texte | Même vocabulaire que la station A |
| `mesure.valeur` | nombre | Décimale point |
| `mesure.unite` | texte | `degC`, `pct`, `ratio`, `mm`, `dS_m` |
| `batterie_pct` | entier | 12 à 100 |

**Attention :** les humidités arrivent en `ratio` (0 à 1) pour environ 20 % des relevés.

> ⚠️ **Les deux listes doivent être traitées.** Un collecteur qui ne lit que `mesures`
> perd un tiers des données sans aucun message d'erreur.

---

## Station C — API locale `http://127.0.0.1:8777`

5 200 relevés paginés.

### `GET /health`
```json
{"statut": "ok", "mode": "instable"}
```

### `GET /stations`
```json
{"stations": [{"code": "STC-21", "commune": "Parakou", "lat": 9.3372, "lon": 2.6303}]}
```

### `GET /releves?page=N&taille=100`
```json
{
  "page": 0, "taille": 100, "total": 5200, "pages_total": 52,
  "releves": [
    {"releve_id": "C-000000", "station_code": "STC-21",
     "horodatage_utc": "2026-03-01T00:00:00Z", "grandeur": "temperature",
     "valeur": 27.4, "unite": "C", "qualite_capteur": "ok"}
  ]
}
```

`taille` est plafonnée à 500. Les unités sont écrites `C`, `%`, `mm`, `dS/m` — **notation
différente des deux autres sources**.

---

## Référentiel — `data/stations_reference.csv`

Séparateur `;` · 7 stations

| Colonne | Notes |
|---|---|
| `code_station` | Stations A et B uniquement |
| `commune`, `latitude`, `longitude`, `altitude_m`, `date_installation` | |

> Les stations C ne sont connues que par `GET /stations`. Et `STB-99`, présente dans les
> relevés, **n'existe nulle part**.

---

## Format normalisé attendu

| Champ | Type | Règle |
|---|---|---|
| `releve_id` | `str` | Clé d'unicité du stockage |
| `station` | `str` | Code en majuscules |
| `horodatage` | `datetime` | **UTC, conscient du fuseau** |
| `grandeur` | `Grandeur` | Énumération, minuscules |
| `valeur` | `float` | Unité canonique |
| `unite` | `str` | `degC`, `pct`, `mm`, `dS_m` — **seules valeurs admises** |
| `qualite` | `Qualite` | `VALIDE`, `SUSPECTE`, `REJETE` |
| `source` | `str` | `A`, `B` ou `C` |

### Conversions

| Depuis | Vers | Formule |
|---|---|---|
| `degF`, `F` | `degC` | `(v − 32) × 5/9` |
| `ratio` | `pct` | `v × 100` |
| `dmm` | `mm` | `v / 10` |
| `C`, `%`, `dS/m` | `degC`, `pct`, `dS_m` | Renommage seul |

### Plages de validité

| Grandeur | Min | Max |
|---|---|---|
| `temperature` | −10 | 60 °C |
| `humidite_sol` / `humidite_air` | 0 | 100 % |
| `pluviometrie` | 0 | 500 mm |
| `conductivite` | 0 | 20 dS/m |

Hors plage → `SUSPECTE`, **jamais supprimé**.
