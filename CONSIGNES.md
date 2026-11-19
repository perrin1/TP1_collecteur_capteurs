# TP 1 — Collecteur de données de capteurs agricoles

**Phase :** 1 — Python professionnel · **Tâche :** génie logiciel, aucun modèle
**Outil :** PyCharm · **Durée estimée :** 10 à 14 h
**Livrable :** package Python testé + CLI + CI GitHub Actions

---

## 1. Contexte

Un réseau de stations météo et de capteurs de sol est déployé sur des parcelles agricoles.
Chaque station remonte ses relevés, mais le dispositif est hétérogène et le terrain est
mauvais :

- la **station A**, ancienne, dépose un fichier `CSV` sur un partage réseau ;
- la **station B**, récente, écrit un fichier `JSON` imbriqué ;
- la **station C**, connectée, expose une **API REST** — qui tombe régulièrement.

On te demande une bibliothèque Python qui collecte ces trois sources, les normalise dans
un format unique, détecte les relevés aberrants et les stocke, le tout pilotable en ligne
de commande et exécutable sans surveillance.

> Aucun apprentissage automatique dans ce TP. On évalue uniquement la qualité du code :
> structure, typage, gestion d'erreurs, tests, robustesse.

---

## 2. Objectifs pédagogiques

À la fin du TP, tu dois savoir :

1. structurer un projet Python en `src/` avec un package installable ;
2. modéliser un domaine avec des `dataclass` et un typage complet vérifié par `mypy` ;
3. écrire une hiérarchie d'exceptions personnalisées utile au diagnostic ;
4. consommer une API instable : **retry, backoff exponentiel, délai maximal, abandon propre** ;
5. garantir l'**idempotence** d'une ingestion répétée ;
6. tester sans dépendre du réseau, par simulacre (`mock`) et par serveur local ;
7. journaliser de façon exploitable (`logging`, niveaux, contexte) ;
8. livrer une CLI et une intégration continue qui tourne.

---

## 3. Le défi central : le réseau tombe

L'API de la station C est volontairement défaillante. Elle produit quatre comportements,
que tu dois découvrir en l'interrogeant :

| Comportement | Fréquence approximative |
|---|---|
| Réponse `503 Service Unavailable` | ~20 % des appels |
| Réponse lente (2 à 5 secondes) | ~10 % des appels |
| **Payload tronqué** — JSON invalide, coupé au milieu | ~8 % des appels |
| **Relevés dupliqués** — le même `releve_id` renvoyé deux fois | ~15 % des pages |

Un collecteur naïf fait trois erreurs :

1. il s'arrête à la première `503` et perd tout le reste ;
2. il plante sur le JSON tronqué au lieu de rejouer la page ;
3. il insère deux fois les mêmes relevés, et ton stock est faux sans que rien ne le signale.

**Ce que tu dois construire :**

- une politique de **retry avec backoff exponentiel** et plafond (ex. 5 tentatives,
  1 s → 2 s → 4 s → 8 s → 16 s), avec abandon propre et journalisé ;
- une **file d'attente hors-ligne** : si la source est injoignable après épuisement des
  tentatives, la requête est persistée et rejouée au prochain lancement ;
- un **stockage idempotent** : relancer la collecte deux fois de suite ne doit pas
  modifier le nombre de lignes stockées.

**Preuve demandée dans le `README.md` :** lance la collecte complète deux fois d'affilée
et montre que le compte de lignes est identique. Puis coupe l'API en cours de route
(`Ctrl+C` sur le serveur), relance, et montre que rien n'est perdu.

> ⚠️ Un rendu dont la seconde exécution duplique les données est plafonné à 12 sur 20,
> quelle que soit la qualité du reste.

---

## 4. Les données

Lance le générateur une seule fois :

```bash
python generer_donnees.py
```

Il produit :

```
data/
├── station_A_releves.csv      ← 4 200 lignes, séparateur ';', décimale ','
└── station_B_releves.json     ← 3 800 relevés, structure imbriquée
faux_api.py                     ← serveur local de la station C
```

Pour démarrer la station C, dans un terminal séparé :

```bash
python faux_api.py
# écoute sur http://127.0.0.1:8777
```

Points d'entrée disponibles :

| Route | Description |
|---|---|
| `GET /health` | État du service |
| `GET /releves?page=N&taille=100` | Une page de relevés, avec les pannes décrites plus haut |
| `GET /stations` | Métadonnées des stations |

Les trois sources ne décrivent **pas** les mêmes champs avec les mêmes noms ni les mêmes
unités. C'est le travail de normalisation. Voir `DICTIONNAIRE.md`.

---

## 5. Consignes

### Partie A — Modélisation du domaine (4 points)

- **A1.** Définis une `dataclass` `Releve` typée, immuable (`frozen=True`), représentant un
  relevé normalisé : identifiant, station, horodatage conscient du fuseau, grandeur,
  valeur, unité, qualité.
- **A2.** Définis une énumération `Grandeur` (température, humidité du sol, humidité de
  l'air, pluviométrie, conductivité) et une énumération `Qualite` (valide, suspecte,
  rejetée).
- **A3.** Écris une hiérarchie d'exceptions : `CollecteError` en racine, puis
  `SourceIndisponible`, `PayloadInvalide`, `ReleveIncoherent`, `ConfigurationInvalide`.
  Chacune doit porter un contexte exploitable, pas seulement un message.
- **A4.** Le projet doit passer `mypy --strict` sur `src/`. Aucun `Any` non justifié.

### Partie B — Lecteurs de sources (4 points)

- **B1.** Définis un protocole `SourceReleves` (via `typing.Protocol`) exposant une méthode
  `lire() -> Iterator[Releve]`. Les trois lecteurs l'implémentent.
- **B2.** `LecteurCSV` : séparateur `;`, décimale `,`, trois formats de date mélangés,
  colonnes en casse incohérente.
- **B3.** `LecteurJSON` : structure imbriquée, certains relevés sous `mesures`, d'autres
  sous `mesures_differees`. Ne pas tout charger en mémoire d'un bloc.
- **B4.** `LecteurAPI` : pagination, retry, backoff, détection du payload tronqué,
  déduplication par `releve_id`.
- **B5.** Les trois lecteurs **renvoient un itérateur**, jamais une liste complète. Justifie
  ce choix dans le `README.md`.

### Partie C — Normalisation et validation (3 points)

- **C1.** Unifie les unités : les températures arrivent en °C et en °F selon la source ; les
  humidités en pourcentage et en fraction ; la pluviométrie en mm et en 1/10 mm.
- **C2.** Unifie les horodatages : trois formats de date, deux fuseaux (`UTC` et
  `Africa/Porto-Novo`). Tout doit finir en UTC conscient du fuseau.
- **C3.** Valide les plages physiques et marque `Qualite.SUSPECTE` plutôt que de supprimer :
  température hors [-10, 60] °C, humidité hors [0, 100] %, pluviométrie négative.
- **C4.** Détecte les **capteurs bloqués** : plus de 12 relevés consécutifs strictement
  identiques sur la même grandeur. Marque-les `SUSPECTE` et compte-les.

### Partie D — Robustesse et stockage (5 points)

- **D1.** Implémente le retry avec backoff exponentiel, en paramètres configurables.
- **D2.** Implémente la file hors-ligne persistée sur disque (JSONL ou SQLite).
- **D3.** Stockage idempotent en SQLite, avec contrainte d'unicité sur `releve_id`.
- **D4.** Journalisation structurée : un enregistrement par source avec le nombre lu,
  rejeté, dupliqué, retenté.
- **D5.** Tests `pytest` avec au minimum : un test par lecteur, un test de la politique de
  retry par simulacre, un test d'idempotence, un test de normalisation d'unités.
  **Couverture minimale attendue : 70 % sur `src/`.**

### Partie E — CLI, CI et documentation (2 points)

- **E1.** CLI avec au moins trois commandes : `collecter`, `statut`, `rejouer-file`.
  Options `--source`, `--depuis`, `--verbeux`.
- **E2.** `pyproject.toml` installable en mode édition (`pip install -e .`).
- **E3.** GitHub Actions : lint (`ruff`), typage (`mypy`), tests (`pytest`).
- **E4.** `README.md` avec les chiffres réels obtenus : nombre de relevés par source,
  taux de rejet, nombre de retries déclenchés, preuve d'idempotence.

### Partie F — Le défi central (3 points)

Documenté dans le `README.md` :

- **F1.** Les quatre comportements de panne, mesurés sur 200 appels. Donne les taux observés.
- **F2.** La preuve d'idempotence : deux exécutions consécutives, même compte de lignes.
- **F3.** La preuve de reprise : API coupée en cours de collecte, relance, aucune perte.
- **F4.** Une courbe ou un tableau montrant le délai total de collecte avec et sans backoff.

---

## 6. Ce qui est évalué

| Partie | Points |
|---|---|
| A — Modélisation du domaine | 4 |
| B — Lecteurs de sources | 4 |
| C — Normalisation et validation | 3 |
| D — Robustesse et stockage | 5 |
| E — CLI, CI, documentation | 2 |
| **F — Défi central** | **3** |
| **Total** | **21 → ramené à 20** |

---

## 7. Pièges secondaires à repérer

Ils ne sont pas annoncés dans les consignes des parties. À toi de les trouver.

1. Deux relevés de la station A portent un horodatage **dans le futur**.
2. La station B envoie des valeurs de température en Fahrenheit **sans le signaler** dans
   le champ `unite` pour environ 5 % des relevés — il faut le déduire de la plage.
3. Un identifiant de station présent dans les relevés n'existe pas dans `/stations`.
4. Le fichier CSV contient un caractère `BOM` en tête qui casse le nom de la première colonne.

---

## 8. Pour aller plus loin

- Ajoute une exécution concurrente des trois sources avec `asyncio` ou
  `concurrent.futures`, et mesure le gain réel.
- Expose un `GET /metrics` au format Prometheus sur ton collecteur.
- Ajoute un mode `--simuler-panne` qui rejoue des scénarios de défaillance pour tes tests.

> **Lien avec ton projet de recherche :** ce TP est une maquette réduite du problème que tu
> veux instruire en thèse — maintenir la cohérence d'un système de collecte quand le réseau
> est intermittent. Garde-le, il te servira d'exemple concret en entretien.
