# Collecteur de données de capteurs agricoles — TP1

Collecte, normalise et stocke les relevés de trois stations hétérogènes :
un CSV (station A), un JSON imbriqué (station B) et une API REST instable
(station C).

Projet du TP 1 — génie logiciel, sans apprentissage automatique. Le détail des
décisions de conception et les mesures se trouvent plus bas ; les consignes
d'origine sont dans `CONSIGNES.md` et le format des sources dans
`DICTIONNAIRE.md`.

## Prérequis

Python **3.12 ou plus**. Aucune autre dépendance système : la station C
n'utilise que la bibliothèque standard.

## Installation

```powershell
git clone <url-du-depot> tp1-collecteur-capteurs
cd tp1-collecteur-capteurs

python -m venv .venv
.\.venv\Scripts\Activate.ps1          # Linux/macOS : source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Générer les données

**À faire avant la première collecte.** Les fichiers sources pèsent 1,4 Mo et
ne sont pas versionnés : c'est le script qui l'est.

```powershell
python generer_donnees.py
```

Il produit `data/station_A_releves.csv` (4 245 lignes), 
`data/station_B_releves.json` (3 800 relevés) et
`data/stations_reference.csv` (7 stations).

## Utilisation

La station C est un serveur local. Démarrez-la dans un **terminal séparé** et
laissez-la tourner :

```powershell
python faux_api.py                     # http://127.0.0.1:8777
python faux_api.py --sain              # sans aucune panne, pour comparer
```

Puis, dans un second terminal :

```powershell
collecteur collecter                   # les trois sources
collecteur statut                      # état de la base et de la file
collecteur rejouer-file                # reprise des pages mises de côté
```

Quelques variantes utiles :

```powershell
collecteur collecter --source A,B                    # sans l'API
collecteur collecter --depuis 2026-04-01             # à partir d'une date
collecteur collecter --verbeux                       # -vv pour le diagnostic
collecteur collecter --journal logs/c.jsonl --format-journal json
```

| Option | Commandes | Rôle |
|---|---|---|
| `--base` | toutes | fichier SQLite (défaut `collecte.db`) |
| `--verbeux` / `-v` | toutes | `-v` détail, `-vv` diagnostic complet |
| `--journal` | toutes | fichier de journal JSON |
| `--format-journal` | toutes | `texte` (défaut) ou `json` à l'écran |
| `--source` | `collecter` | sources à lire, séparées par des virgules |
| `--depuis` | `collecter` | ne garder que les relevés à partir de cette date |
| `--donnees` | `collecter` | dossier des fichiers sources |
| `--url` | `collecter`, `rejouer-file` | adresse de la station C |
| `--tentatives` | `collecter` | tentatives maximales par page |
| `--delai-initial` | `collecter` | premier délai de reprise, en secondes |

Une collecte complète prend une à deux minutes : la station C répond lentement
dans 10 % des cas et chaque page perdue est rejouée.

## Vérifications

```powershell
python -m ruff check src tests
python -m mypy            # --strict, sur src/ et tests/
python -m pytest          # couverture >= 70 % (D5)
```

Les trois tournent aussi en intégration continue — voir
`.github/workflows/ci.yml`. **Aucun test n'a besoin de la station C ni des
fichiers de `data/`** : ils sont tous isolés.

## Mesures du défi central

```powershell
python mesures/defi_central.py         # F1, F3 et F4, environ trois minutes
python mesures/defi_central.py f4      # une seule mesure
```

Le script démarre et arrête lui-même la station C sur ses propres ports.

## Organisation

```
src/collecteur/
├── domaine.py          modèle figé : Releve, Grandeur, Qualite
├── erreurs.py          hiérarchie d'exceptions à contexte
├── normalisation.py    unités et fuseaux horaires
├── validation.py       plages physiques, capteurs bloqués, pièges
├── referentiel.py      stations légitimes
├── reseau.py           politique de reprise avec backoff
├── stockage.py         SQLite idempotent
├── file_attente.py     file hors-ligne JSONL
├── journalisation.py   journal structuré JSON
├── collecte.py         orchestration
├── cli.py              interface en ligne de commande
└── sources/            un lecteur par station (CSV, JSON, API)
```

## Avancement

| Partie | Points | État |
|---|---|---|
| A — Modélisation du domaine | 4 | ✔ faite |
| B — Lecteurs de sources | 4 | ✔ faite |
| C — Normalisation et validation | 3 | ✔ faite |
| D — Robustesse et stockage | 5 | ✔ faite |
| E — CLI, CI, documentation | 2 | ✔ faite |
| F — Défi central | 3 | ✔ faite |

## Décisions de conception

### Pourquoi `Releve` est figé

Un relevé traverse lecteur → normalisation → validation → stockage. S'il était
modifiable, une erreur de normalisation modifierait silencieusement un objet
déjà compté ailleurs. Figé (`frozen=True`), toute transformation doit produire
un nouvel objet — et cela se voit dans le code. `slots=True` supprime le
`__dict__` de chaque instance, ce qui compte sur plus de 13 000 relevés.

### Incohérence structurelle contre mesure douteuse

C'est la frontière qui structure tout le projet.

| Lève `ReleveIncoherent` | Devient `Qualite.SUSPECTE` |
|---|---|
| horodatage sans fuseau | température à 95 °C |
| unité hors du canon | humidité à 140 % |
| identifiant vide | pluviométrie négative |
| valeur NaN ou infinie | capteur bloqué |

À gauche, le relevé ne peut pas exister : c'est un défaut de lecture. À droite,
la mesure existe mais est douteuse — et l'énoncé interdit de la supprimer.

### Pourquoi `lire()` renvoie un itérateur et non une liste (B5)

Trois raisons, dans l'ordre d'importance.

**L'empreinte mémoire cesse de dépendre du volume.** La station B est lue par
décodage incrémental : le tampon fait 64 Ko et un seul objet est matérialisé à
la fois. Le fichier pourrait peser un gigaoctet, le lecteur ne bougerait pas.
Un `json.load()` aurait tout chargé pour n'en garder qu'un relevé à la fois.

**Le traitement commence avant la fin de la lecture.** La station C met 2 à 5
secondes à répondre dans 10 % des cas. Avec une liste, rien n'est traité tant
que la 52ᵉ page n'est pas arrivée ; avec un itérateur, les relevés de la page 1
sont déjà en base pendant que la page 2 est attendue.

**Une lecture interrompue garde ce qu'elle a lu.** C'est la condition de la
reprise (D2) : si l'API tombe à la page 30, les 2 900 relevés déjà émis sont
déjà stockés, et seule la page 30 part en file d'attente.

Le prix à payer est qu'un itérateur ne se parcourt qu'une fois, et que les
compteurs de `statistiques` ne sont complets qu'après épuisement. C'est
documenté dans le protocole plutôt que contourné.

### Mesures réelles de lecture

Relevés sur les fichiers fournis et sur l'API en mode instable.

| Source | Lus | Émis | Rejetés | Doublons | Reprises | Unités converties |
|---|---|---|---|---|---|---|
| A — CSV | 4 245 | 4 245 | 0 | 45 | — | 172 |
| B — JSON | 3 800 | 3 800 | 0 | 0 | — | 278 |
| C — API | 5 114 | 5 100 | 1 page | 14 | 28 | 4 082 |

Lectures à retenir :

* **4 245 et non 4 200** : les 45 doublons exacts du CSV sont comptés et laissés
  passer, c'est le stockage idempotent (D3) qui garantira l'unicité.
* **3 800 et non 2 576** : les deux tableaux `mesures` et `mesures_differees`
  sont lus. Un lecteur qui n'ouvre que le premier perd un tiers du jeu sans
  aucun message d'erreur.
* **43 températures en Fahrenheit déduites** sur la station B, là où rien ne
  l'annonçait (piège n°2).
* **1 page perdue sur 52** après cinq tentatives, soit 100 relevés. Elle est
  enregistrée dans `pages_abandonnees` et sera rejouée par la partie D2 — la
  collecte ne s'est pas arrêtée pour autant.

### Validation : ce qui est marqué, et combien (C3, C4)

Sur les 8 045 relevés des stations A et B réunies. **Aucun relevé n'est
supprimé** : 8 045 entrent, 8 045 sortent, dont 187 marqués `SUSPECTE`.

| Anomalie | Relevés | Origine |
|---|---|---|
| Capteur bloqué | 106 | C4 — 7 séries, la plus longue de 16 |
| Station inconnue | 55 | piège n°3 — `STB-99`, absente du référentiel et de l'API |
| Hors plage physique | 32 | C3 — conductivité > 20 dS/m, température > 60 °C |
| Horodatage dans le futur | 2 | piège n°1 — `A-001337` et `A-003901` |

### Capteur bloqué : la consigne ne peut pas être suivie à la lettre

L'énoncé demande de détecter « plus de 12 relevés consécutifs strictement
identiques **sur la même grandeur** ». Mesuré sur le jeu de données fourni :

| Clé de regroupement | Plus longue série | Séries de plus de 12 |
|---|---|---|
| `(station, grandeur)` | 3 | **0** |
| `(grandeur,)` | 7 | **0** |
| `(station,)` | 8 | **0** |
| `(source,)` | **16** | **7** |

La lecture littérale ne détecte rien. La raison est dans le générateur de
données : il fige une valeur pendant quinze relevés consécutifs sans se soucier
de la station ni de la grandeur tirées entre-temps. Une série bloquée traverse
donc les grandeurs, et toute clé qui les sépare la découpe en fragments trop
courts pour être vus.

Le défaut retenu est la clé `(source,)` ordonnée par horodatage, la seule qui
retrouve les sept séries injectées. L'interprétation littérale reste accessible
par `cle=lambda r: (r.station, r.grandeur)`. Sur le fond, le regroupement large
se défend : une chaîne d'acquisition qui renvoie la même valeur quelle que soit
la grandeur mesurée est un symptôme plus grave, pas moins.

### La seule règle qui casse le flux

Les règles C3, piège n°1 et piège n°3 sont sans état : elles n'examinent qu'un
relevé à la fois et préservent le caractère paresseux de la lecture.

C4 ne le peut pas. Une série est consécutive **dans le temps**, or le CSV de la
station A est mélangé — deux lignes voisines dans le fichier peuvent être
distantes de trois semaines. Détecter une série impose de trier, et trier
impose de tout avoir en mémoire. C'est le seul endroit du collecteur où
l'empreinte croît avec le volume, et c'est assumé plutôt que caché : à plus
grande échelle, la même détection s'écrirait en SQL avec une fonction de
fenêtrage, directement dans la base de la partie D.

### Preuve d'idempotence (D3, et preuve F2)

Deux exécutions consécutives de la collecte complète, sans rien effacer entre
les deux :

```
--- EXECUTION 1 : lignes en base = 8000 ---
    A: lus=4245 inseres=4200 deja_vus=45
    B: lus=3800 inseres=3800 deja_vus=0

--- EXECUTION 2 : lignes en base = 8000 ---
    A: lus=4245 inseres=0 deja_vus=4245
    B: lus=3800 inseres=0 deja_vus=3800
```

**8 000 lignes les deux fois, zéro insertion à la seconde exécution.** Les 45
doublons du CSV sont absorbés dès le premier passage : 4 245 relevés lus, 4 200
lignes créées.

L'idempotence n'est pas garantie par la discipline du code appelant mais par la
**clé primaire** sur `releve_id`, et par un `INSERT … ON CONFLICT DO UPDATE` qui
ne fait qu'un aller-retour. Un script tiers écrivant dans la même base ne
pourrait pas la casser.

Un détail visible dans le journal : à la seconde exécution, `mis_a_jour=97`
pour la station A. Les lecteurs ré-émettent ces relevés avec la qualité
`valide`, et la détection de séries bloquées les re-marque juste après. L'état
final est identique à chaque fois — 8 000 lignes, 186 suspects — mais la
qualité est bien **recalculée** à chaque passage plutôt que figée au premier.

### Détection des capteurs bloqués en SQL

La partie C annonçait qu'une fonction de fenêtrage ferait le travail sans
ramener les relevés en mémoire. C'est fait, et les deux implémentations
trouvent les mêmes 7 séries de 15.

Un piège a coûté douze relevés marqués à tort dans la première version :
marquer par `WHERE source = ? AND valeur = ?` à partir des séries trouvées
attrape **tous** les relevés portant cette valeur, pas seulement ceux de la
série. La requête rattache maintenant chaque relevé à son île (technique dite
« gaps and islands ») avant de marquer — 97 relevés, et pas un de plus.

### File hors-ligne : pourquoi JSONL et non SQLite (D2)

La base stocke des relevés valides ; la file mémorise des intentions. Elles
n'ont ni le même cycle de vie — l'une s'accumule, l'autre se vide — ni la même
exigence : une file doit survivre à un arrêt brutal **au milieu d'une
écriture**.

Un fichier JSON Lines le garantit presque gratuitement : une ligne par entrée,
`flush` puis `fsync` après chaque écriture. Si le programme meurt en pleine
ligne, seule la dernière est illisible et toutes les précédentes restent
valides — c'est testé. La même panne au milieu d'une transaction SQLite
imposerait une reprise de journal. Et la file reste lisible avec un `cat`
quand il faut comprendre pourquoi une page manque.

La réécriture complète passe par un fichier temporaire puis un renommage
atomique : à aucun instant la file n'existe à moitié.

### Journal structuré (D4)

Un enregistrement de synthèse par source, en JSON, avec tout le contexte :

```json
{"horodatage": "...", "niveau": "INFO", "message": "collecte terminée",
 "evenement": "fin", "source": "A", "statut": "ok", "duree_s": 0.118,
 "lus": 4245, "emis": 4245, "rejetes": 0, "dupliques": 45, "retentes": 0,
 "inseres": 4200, "deja_vus": 45, "pages_differees": 0}
```

Un journal n'est pas fait pour être lu, il est fait pour être interrogé.
`jq 'select(.source=="C") | .retentes'` répond en une ligne à une question qui
demanderait sinon une expression régulière. La console garde un format texte
lisible, le fichier reste exploitable.

### Tests (D5)

66 tests, **78 % de couverture** sur `src/` — le seuil exigé est 70 %, et
`--cov-fail-under=70` le fait respecter par la CI.

| Exigence D5 | Tests |
|---|---|
| un test par lecteur | CSV avec BOM et trois formats de date, JSON avec les deux tableaux et le fuseau déclaré, API par simulacre |
| politique de retry par simulacre | progression géométrique, plafond, gigue, abandon propre, erreur non récupérable |
| idempotence | deux écritures identiques, valeur corrigée, reprise après interruption |
| normalisation d'unités | sept conversions, unité inconnue rejetée |

**Aucun test n'ouvre le réseau et aucun n'attend réellement.** `time.sleep` et
le générateur aléatoire sont injectés dans la politique de reprise : un test
qui dormirait 31 secondes ne serait jamais relancé deux fois, donc ne
servirait à rien.

### CLI et intégration continue (E1 à E3)

**La CLI ne contient aucune logique métier.** Elle lit des arguments, instancie
des objets, affiche un résultat. Une formule qui apparaîtrait dans `cli.py`
serait un défaut de conception : la même opération deviendrait impossible
depuis un test, un notebook ou un ordonnanceur.

`argparse` plutôt qu'une bibliothèque tierce — la bibliothèque standard suffit
pour trois commandes, et une dépendance de moins est une dépendance qui ne
cassera pas la CI dans six mois.

`main()` renvoie un code de sortie au lieu d'appeler `sys.exit` : une fonction
qui termine le processus n'est pas testable. Les onze tests de `test_cli.py`
l'appellent comme une fonction ordinaire.

La CI enchaîne deux travaux :

| Travail | Contenu |
|---|---|
| `qualite` | ruff, `mypy --strict`, pytest avec couverture — sur Python 3.12 **et** 3.13 |
| `bout_en_bout` | génère les données, démarre la station C, lance deux collectes et **échoue si le nombre de lignes change entre les deux** |

Le second est le plus utile : il transforme la preuve d'idempotence de la
partie F2 en test de non-régression permanent. Tester 3.12 en plus de 3.13
vérifie que la borne `requires-python = ">=3.12"` est vraie plutôt
qu'espérée.

### Sortie réelle des commandes (E4)

```
$ collecteur collecter --source A,B

Base : collecte.db  (8000 relevés)
source  lus   émis  rejetés  doublons  reprises  insérés  déjà vus
------  ----  ----  -------  --------  --------  -------  --------
A       4245  4245  0        45        0         4200     45
B       3800  3800  0        0         0         3800     0
```

```
$ collecteur statut

Base : collecte.db  (8000 relevés)

source  relevés  dernier relevé
------  -------  ----------------------
A       4200     2027-01-11T09:49+00:00
B       3800     2026-03-27T15:15+00:00

qualité   relevés
--------  -------
suspecte  186
valide    7814

7 série(s) de capteur bloqué, la plus longue de 15 relevés.
```

Le « dernier relevé » de la station A tombe en **janvier 2027** : c'est le
piège n°1, les deux horodatages dans le futur. Ils sont marqués suspects mais
conservés, donc toujours visibles ici — ce qui est exactement le comportement
voulu. Un collecteur qui les aurait supprimés afficherait une date plausible
et aurait perdu l'information.

### Tests, au total

**77 tests, 85 % de couverture** sur `src/`.

| Module | Couverture |
|---|---|
| `domaine`, `normalisation`, `reseau`, `erreurs` | 91 à 98 % |
| `stockage`, `file_attente`, `validation` | 88 à 94 % |
| `sources` | 73 à 89 % |
| `cli` | 75 % |

---

## Partie F — Le défi central

Toutes les mesures sont reproductibles :

```powershell
python mesures/defi_central.py          # F1, F3 et F4
python mesures/defi_central.py f4       # au choix
```

Chaque mesure **redémarre la station C sur son propre port**. Le serveur tire
ses pannes dans un générateur pseudo-aléatoire initialisé au lancement : sans
redémarrage, la seconde variante hériterait de la séquence de la première et la
comparaison serait faussée.

### F1 — Les quatre comportements, mesurés sur 200 appels

Appels bruts, sans aucune reprise : on mesure le service, pas la capacité du
collecteur à l'absorber.

| Comportement | Observé | Taux | Annoncé |
|---|---|---|---|
| `503 Service Unavailable` | 50 / 200 | **25,0 %** | ~20 % |
| Réponse lente (≥ 2 s) | 20 / 200 | **10,0 %** | ~10 % |
| Payload tronqué | 21 / 200 | **10,5 %** | ~8 % |
| Page contenant des doublons | 21 / 129 | **16,3 %** | ~15 % |

Durée médiane d'un appel réussi : **3 ms**. Les 10 % de réponses lentes ne
déplacent donc pas la médiane — mais elles dominent le temps total, ce qui est
exactement pourquoi un timeout serré serait une mauvaise idée.

**Le dénominateur des doublons n'est pas 200.** Une page tronquée ou un `503`
ne permettent pas d'observer si elle contenait des doublons : le tirage a bien
lieu côté serveur, mais le résultat est illisible. Rapporté aux 200 appels, le
taux tombe à 10,5 % et semble contredire l'annonce ; rapporté aux **129 pages
lisibles**, il vaut 16,3 % et la confirme. Mesurer un taux impose de savoir sur
quoi il porte.

Les 21 pages concernées contenaient **63 relevés dupliqués** au total, soit 3
par page en moyenne — cohérent avec le `randint(1, 4)` du serveur.

### F2 — Idempotence

Démontrée plus haut : 8 000 lignes à la première exécution, 8 000 à la seconde,
zéro insertion. Vérifiée en permanence par le travail `bout_en_bout` de la CI,
qui échoue si le compte change entre deux collectes.

### F3 — Reprise après coupure

La station C est tuée **pendant** la collecte, au bout de trois secondes.

```
  coupure : 500 relevés écrits, 47 page(s) mise(s) de côté
  relance : 4800 relevés, 4 page(s) encore perdue(s)
  rejeu 1 : 5200 relevés, 0 page(s) restante(s)
  final   : 5200 / 5200 relevés, 0 doublon(s)
```

Trois choses à lire dans ces quatre lignes.

**Les 500 relevés de la coupure sont conservés.** La collecte s'arrête sans
exception : chaque page injoignable est mise de côté, le flux se termine
normalement, la transaction est validée. Une implémentation qui laisserait
remonter l'erreur annulerait la transaction et perdrait ces 500 relevés.

**La relance seule ne suffit pas.** Elle ramène 4 800 relevés et en perd 400 :
quatre pages tombées pendant la relance elle-même, à cause de l'instabilité
ordinaire de l'API. Une API instable finit toujours par laisser un trou.

**C'est le rejeu qui ferme le trou.** Les quatre pages sont redemandées seules —
ce que fait `collecteur rejouer-file` — et le compte atteint 5 200. Zéro
doublon malgré trois passages sur les mêmes données : la clé primaire fait son
travail.

### F4 — Délai total avec et sans backoff

Collecte complète de la station C, pages de 200, serveur neuf à chaque variante.

| Politique | Durée | Relevés | Pages perdues | Reprises |
|---|---|---|---|---|
| Sans reprise | **7,4 s** | 3 000 | **11 / 26** | 11 |
| Reprise immédiate | 19,4 s | 5 000 | 1 | 17 |
| Backoff constant (1 s) | 35,4 s | 5 000 | 1 | 17 |
| Backoff exponentiel | 59,7 s | 5 000 | 1 | 17 |

**Le résultat ne va pas dans le sens attendu, et il faut le dire.** Le backoff
exponentiel est huit fois plus lent que l'absence de reprise et trois fois plus
lent que la reprise immédiate — pour **exactement le même résultat** : 5 000
relevés, une page perdue, dix-sept reprises.

L'explication tient à la nature du simulateur. Ses pannes sont des tirages
indépendants : la probabilité qu'une page échoue ne dépend ni de la charge, ni
du nombre de requêtes déjà reçues, ni du temps écoulé. Attendre n'améliore donc
rien, puisque le tirage suivant est aussi favorable immédiatement que huit
secondes plus tard.

Deux conclusions, de portée inégale :

**Ce que la mesure établit.** La reprise est indispensable, le backoff ne l'est
pas. Passer de « sans reprise » à « reprise immédiate » fait gagner 2 000
relevés — 40 % du jeu de données — pour 12 secondes. C'est là que se joue
l'essentiel, et c'est mesurable.

**Ce que la mesure ne peut pas établir.** Le backoff ne protège pas contre des
pannes aléatoires mais contre des pannes **corrélées à la charge** : un service
réellement saturé que l'on martèle reste saturé. Aucun banc d'essai local ne
peut le démontrer, parce qu'il faudrait un serveur dont la probabilité d'échec
dépende du rythme des requêtes.

Le backoff exponentiel est donc conservé par défaut — un collecteur destiné à
un vrai service doit être poli, et 60 secondes pour 5 200 relevés reste
négligeable devant un intervalle de collecte horaire. Mais le choix repose ici
sur un argument de conception, pas sur cette mesure, et la politique reste
réglable par `--delai-initial` pour qui mesurerait le contraire en production.
