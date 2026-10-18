# mas

> Anciennement *masque*. Au carnaval antillais, « faire mas », c'est se déguiser pour cacher son
> identité : c'est ce que fait l'outil avec tes données.

Anonymise tes PDF **sur ton PC**, puis fait analyser la version anonyme par des
agents LLM optimisés avec **DSPy + GEPA**. Premier cas d'usage : à partir de
relevés bancaires, retrouver les dépenses récurrentes et obligatoires pour
construire un budget.

```
 PDF / ZIP
    │
    ▼
 ┌──────────────────────── LOCAL (rien ne sort) ─────────────────────────┐
 │ Lecture          tableau relu ligne par ligne (date, libellé, débit,   │
 │                  crédit) ; comptes séparés ; contrôle au centime avec  │
 │                  les totaux de la banque ; sinon l'IA ; OCR optionnel  │
 │ Anonymisation    Presidio + spaCy FR + regex FR (IBAN, RIB, NIR,       │
 │                  tél., adresses, noms dans les virements) + GLiNER     │
 │                  optionnel + tes données déclarées dans config.yaml    │
 │ Pseudonymisation « Jean Dupont » → [PERSONNE_1], partout et d'un mois  │
 │                  sur l'autre ; table chiffrée dans ~/.mas/             │
 │ Vérificateur     regex + clés de contrôle + recherche des valeurs      │
 │                  connues ; boucle jusqu'à 0 fuite, sinon ENVOI BLOQUÉ  │
 └────────────────────────────────────────────────────────────────────────┘
    │ texte pseudonymisé uniquement
    ▼
 ┌──────────────────────── AGENTS (LLM cloud) ───────────────────────────┐
 │ Extracteur ⇄ Contrôleur   le contrôleur (Python) compare les montants │
 │                           extraits à ceux de la page et renvoie ses   │
 │                           remarques à l'extracteur (2 corrections max)│
 │ Catégoriseur              logement, énergie, abonnement…              │
 │ Détecteur de récurrences  Python déterministe (périodicité, montants) │
 │ Classeur                  obligatoire / optionnel / courant variable  │
 │ Synthétiseur              commentaire ; chiffres calculés en Python   │
 └────────────────────────────────────────────────────────────────────────┘
    │
    ▼
 Rapport dé-pseudonymisé EN LOCAL (rapports/rapport.md + .html) + version anonyme
```

## Sommaire

1. [Installation](#installation)
2. [Configuration](#configuration)
3. [Analyser tes relevés, pas à pas](#analyser-tes-relevés-pas-à-pas)
4. [Comment mas lit tes relevés](#comment-mas-lit-tes-relevés) et [ce qui compte comme dépense](#ce-qui-compte-comme-dépense)
5. [Les deux boucles de mas](#les-deux-boucles-de-mas)
6. [Essayer sans tes données](#essayer-sans-tes-données)
7. [Publier le code sans tes données](#publier-le-code-sans-tes-données)
8. [Commandes](#commandes)
9. [Optimisation avec GEPA](#optimisation-avec-gepa)
10. [Tests](#tests-sans-clé-api)
11. [Structure](#structure)
12. [Adapter à ta banque](#adapter-à-ta-banque)
13. [Limites](#limites)
14. [Licence](#licence)

## Installation

Il faut Python 3.10 ou plus récent (Linux, macOS ou WSL sous Windows).

```bash
git clone https://github.com/<ton-compte>/mas.git && cd mas
python3 -m venv .venv && source .venv/bin/activate   # ou : uv venv
pip install -e ".[dev]"                              # ou : uv pip install -e ".[dev]"
mas init
```

`mas init` prépare le dossier sans rien écraser :

- `config.yaml` (copie de `config.example.yaml`) : renseigne ta section `identite` et choisis le
  modèle dans `llm` ;
- `.env` (copie de `.env.example`) : colle ta clé d'API ;
- `releves/` pour tes PDF et `rapports/` pour les résultats, deux dossiers ignorés par git ;
- le modèle français de spaCy, téléchargé s'il manque.

Options : `pip install -e ".[gliner]"` (2e détecteur de noms, plus lent),
`".[ocr]"` + `sudo apt install tesseract-ocr tesseract-ocr-fra` (PDF scannés).

## Configuration

**Lance toujours `mas` depuis son dossier.** `config.yaml` et `.env` sont lus dans le dossier
courant. Sans `config.yaml`, `mas analyser` et `mas anonymiser` s'arrêtent et te proposent
`mas init`, plutôt que de traiter tes relevés sans tes données déclarées. Pour une configuration
rangée ailleurs : `mas analyser … -c chemin/config.yaml`.

### `.env` : la clé d'API

Il est lu automatiquement à chaque commande. Une variable déjà définie dans le terminal reste
prioritaire. Il est ignoré par git, comme `config.yaml`.

### `config.yaml` : les réglages

| Section | Rôle |
|---|---|
| `llm` | modèle d'analyse, au format LiteLLM `fournisseur/modele`. `anthropic/claude-haiku-4-5-20251001` est économique (1 $ / 5 $ par million de tokens en entrée / sortie) ; `anthropic/claude-sonnet-5-5` est plus fin et coûte le double (2 $ / 10 $) ; `anthropic/claude-opus-5-5` est le plus fin des trois et coûte quatre fois Haiku (4 $ / 20 $). Pour Sonnet et Opus 5.5 : **`temperature: null` et `max_tokens: 16000`**, car ils refusent la température et leur réflexion avant de répondre compte dans `max_tokens` |
| `analyse` | ce qui compte comme dépense : virements vers un bénéficiaire à ton nom (`virements_a_ton_nom`), tes comptes dans d'autres banques (`comptes_personnels`), virements à des proches (`virements_a_des_proches`), loyers payés sans le mot « loyer » (`loyers_sans_libelle`, `loyer_montant_min`) ; voir [Ce qui compte comme dépense](#ce-qui-compte-comme-dépense) |
| `identite` | tes données qui ne doivent jamais sortir : noms (toutes les variantes écrites sur tes relevés), adresses, IBAN, numéros de compte, téléphones, e-mails, et `autres` (n° client, n° de contrat, proches à qui tu fais des virements…) |
| `anonymisation` | modèle spaCy, types d'entités masquées, `liste_blanche` des marchands à ne pas masquer |
| `verification` | nombre maximal de boucles anonymisation → vérification (voir [Les deux boucles de mas](#les-deux-boucles-de-mas)), vérificateur LLM local optionnel (Ollama) |
| `coffre` | emplacement de la table chiffrée des pseudonymes |
| `recurrence` | seuils de détection des dépenses récurrentes |
| `optimisation` | GEPA : modèle de réflexion (`temperature_reflexion: null` pour Opus 5.5), taille des jeux, dossiers |

## Analyser tes relevés, pas à pas

**1. Se placer dans le dossier**

```bash
cd mas                        # le dossier du dépôt
source .venv/bin/activate
```

**2. Récupérer les relevés**

Télécharge tes relevés en PDF depuis ton espace bancaire : au moins **3 mois**, idéalement 6 à 12.
C'est la répétition qui révèle une dépense récurrente, et 12 mois font apparaître les dépenses
trimestrielles ou annuelles. Range-les dans `releves/` : ce dossier est ignoré par git.

**3. Déclarer tes données dans `config.yaml`**

```yaml
identite:
  noms: ["Prénom NOM", "NOM PRENOM", "M NOM"]
  adresses: ["12 rue ..."]
  ibans: ["FR76 ..."]
  numeros_compte: ["..."]
  telephones: ["06..."]
  emails: ["...@..."]
  autres: ["n° client", "noms des proches à qui tu fais des virements"]
```

Elles sont masquées en plus de la détection automatique, puis recherchées une dernière fois par le
vérificateur avant tout envoi.

**4. Mettre la clé d'API dans `.env`** (voir [Installation](#installation)).

**5. Anonymiser et relire, sans rien envoyer**

```bash
mas anonymiser releves/ --sortie sortie_anonyme/
```

Ouvre les `.txt` produits et vérifie :

- **Tes données sont masquées :** cherche ton nom, ton IBAN et ta rue avec Ctrl+F. S'il reste
  quelque chose, ajoute-le à `identite.autres` et relance.
- **Les marchands sont lisibles :** EDF, Netflix… Un marchand masqué à tort (par exemple
  `[PERSONNE_2]`) s'ajoute à `anonymisation.liste_blanche`.
- **Les opérations sont lues :** dates, libellés et montants doivent être là. Une page vide
  signifie un PDF scanné, voir [Limites](#limites).

**6. Lancer l'analyse**

```bash
mas analyser releves/
```

mas anonymise à nouveau puis vérifie (voir [Les deux boucles de mas](#les-deux-boucles-de-mas)) :

- **S'il reste une donnée personnelle**, l'envoi est **bloqué** et mas dit laquelle.
- **Sinon**, il affiche un extrait de ce qui partira et demande confirmation. `--oui` saute cette
  question.

Pendant l'analyse, chaque étape s'affiche :

```
[1/5] Lecture directe des tableaux (sans IA) : 363 opération(s) sur le compte principal,
      50 mouvement(s) entre tes comptes mis à part
  Totaux imprimés par la banque : 6/6 relevé(s) concordant(s)
[2/5] Catégorisation : 214 libellé(s) distinct(s) en 6 lot(s)
[3/5] Dépenses récurrentes (calcul local, sans IA) : 9 trouvée(s)
[4/5] Classement obligatoire / optionnel de 9 dépense(s)…
[5/5] Rédaction de la synthèse…
```

Si le tableau d'un relevé n'est pas reconnu, l'étape 1 passe par l'IA, page par page
(« [1/5] Extraction des opérations par l'IA »), voir [Comment mas lit tes relevés](#comment-mas-lit-tes-relevés).

À la fin, un **résumé du traitement** donne la durée de l'anonymisation et de l'analyse, le nombre
d'appels à l'IA, les tokens consommés et le **coût estimé**. Seuls les appels réellement facturés
sont comptés : si tu relances la même analyse, les réponses déjà calculées sont reprises du cache
de DSPy, gratuitement. Si l'IA est injoignable (clé invalide, crédit épuisé, modèle inconnu),
l'analyse s'arrête tout de suite avec l'erreur au lieu de produire un rapport vide.

**7. Lire le résultat**

| Fichier | Contenu |
|---|---|
| `rapports/rapport.html` | **la page du rapport**, avec tes vrais noms remis en local |
| `rapports/rapport_anonyme.html` | la même page, telle que l'IA l'a vue (pseudonymes) |
| `rapports/rapport.md` / `rapport_anonyme.md` | les mêmes informations en texte |
| `rapports/rapport.json` | les données de la page, avec les pseudonymes (pour `mas exporter`) |

La page du rapport montre :

- **ton mois type :** une barre représente tes revenus ; les parties colorées sont tes dépenses
  (obligatoires, abonnements optionnels, courantes), la partie vide est ce qu'il te reste, avec ce
  montant en grand ;
- **ce que dit l'analyse :** le constat et les pistes d'économies rédigés par l'IA ;
- **où va ton argent :** tes dépenses mensuelles par catégorie, avec le tableau des montants exacts ;
- **mois par mois :** chaque catégorie de dépenses, mois après mois, avec la moyenne et le total de
  chaque mois ; plus la case est colorée, plus la dépense est élevée. Un mois que tes relevés ne
  couvrent qu'en partie est marqué « incomplet » : ses montants sont forcément plus bas ;
- **tes dépenses récurrentes :** à payer quoi qu'il arrive, abonnements que tu peux arrêter,
  dépenses courantes qui reviennent, avec le coût par mois et par an.

Survole une barre (ou atteins-la au clavier) pour voir son montant, sa part et son coût annuel.
Dans la version anonyme, les pseudonymes apparaissent comme de petits masques ; dans la version
personnelle, les vraies valeurs remises en local sont soulignées en pointillé.

La page est autonome : styles et script intégrés, aucune ressource externe (l'ouvrir n'envoie
rien), thème clair ou sombre selon Windows, imprimable. Pour l'ouvrir depuis WSL dans le
navigateur Windows :

```bash
explorer.exe "$(wslpath -w rapports/rapport.html)"
```

`mas coffre` affiche la table des pseudonymes et de leurs vraies valeurs, en local.

## Comment mas lit tes relevés

**Tableau reconnu : lecture directe, sans IA.** Quand le tableau des opérations a un en-tête
« Date … Débit … Crédit » (la plupart des banques françaises), mas repère la position des colonnes
et relit chaque opération ligne par ligne : date, libellé (même sur deux lignes), débit, crédit,
date de valeur. Cette lecture :

- **ne dépend pas du dessin du tableau :** certains relevés (la BRED, par exemple) sont lus par
  l'extraction de tableaux classique comme une seule ligne fourre-tout, où plus aucun montant n'est
  rattaché à son libellé ;
- **sépare les comptes d'un même relevé :** seul le compte courant est analysé ; les livrets
  imprimés à la suite (LDD, Livret A…) servent à reconnaître ton épargne ;
- **est contrôlée au centime :** la somme des opérations lues est comparée au « Total des
  mouvements » imprimé par la banque (ou, à défaut, solde précédent + crédits − débits = nouveau
  solde). En cas d'écart, le rapport le signale en tête ;
- **donne la bonne période :** le nombre de mois vient des dates des relevés (solde précédent →
  nouveau solde), arrondi au demi-mois.

**Tableau non reconnu : extraction par l'IA**, page par page, avec la boucle de correction
décrite plus bas.

### Ce qui compte comme dépense

L'argent qui change seulement de compte n'est **pas** une dépense. Il est montré à part, sous la
barre des revenus (« Pas compté dans tes dépenses ») et dans le rapport texte :

| Mouvement | Comment il est repéré | Réglage |
|---|---|---|
| vers / depuis tes livrets | un virement du compte courant et un mouvement d'un livret du même relevé, de même montant, en sens inverse, à 4 jours près | automatique |
| vers tes autres comptes | le libellé mentionne un compte que tu as déclaré (IBAN, code BIC, banque) | `analyse.comptes_personnels` |
| vers un compte à ton nom | le bénéficiaire porte le nom déclaré dans `identite.noms` | `analyse.virements_a_ton_nom` |
| avec des proches | catégorie « virements à des proches » | `analyse.virements_a_des_proches` |

Le repérage « à ton nom » est une **déduction**, pas une certitude : un homonyme, un proche qui
porte ton nom ou un compte joint donnent le même résultat. Ces virements sont mis à part par
défaut ; mets `virements_a_ton_nom: depense` pour les compter comme des dépenses, ou déclare tes
vrais comptes dans `comptes_personnels` pour ne plus dépendre du nom. Les virements à des proches
comptent comme des dépenses, sauf avec `virements_a_des_proches: a_part`.

Le reste du calcul :

- **remboursements :** un remboursement par carte vient en déduction des dépenses de sa catégorie ;
- **revenus :** salaire et revenus, plus l'argent reçu de particuliers, une fois les remboursements
  déduits (un remboursement annule le virement qu'il rembourse, voir
  [docs/categories.md](docs/categories.md#virements-à-des-proches)) ;
- **loyer sans libellé :** des virements mensuels d'un montant stable vers une même personne
  (300 € ou plus) sont comptés dans le logement et signalés comme « loyer probable »
  (`analyse.loyers_sans_libelle`, `analyse.loyer_montant_min`) ;
- **moyennes :** chaque montant est divisé par le nombre de mois couverts par les relevés ;
- **catégories :** ce que l'IA range dans chaque catégorie (logement, crédits, virements à des
  proches, autres…) est expliqué dans [docs/categories.md](docs/categories.md) ;
- **mois par mois :** les mêmes règles, appliquées à chaque mois. Un mois couvert à moins de 75 %
  par tes relevés (par exemple du 1er au 5) est marqué incomplet ; la somme des mois, divisée par le
  nombre de mois couverts, redonne les moyennes (au centime près).

## Les deux boucles de mas

mas répète deux étapes jusqu'à obtenir un résultat satisfaisant. Elles n'ont ni le même rôle ni
le même coût :

| Boucle | Rôle | Où | Coût | Réglage |
|---|---|---|---|---|
| Anonymisation ⇄ vérification | ne rien envoyer de personnel | sur ton PC | gratuit | `verification.iterations_max` dans `config.yaml` (3) |
| Extracteur ⇄ contrôleur | extraire des opérations justes, quand le tableau n'est pas reconnu | avec l'IA | un appel à l'IA par correction | `tentatives_max` dans `agents/programme.py` (2) |

### 1. Anonymisation ⇄ vérification : le filet de sécurité

```
anonymiser toutes les pages
        ↓
vérifier toutes les pages ──── aucune fuite ──→ envoi possible
        │ fuite(s) trouvée(s)
        ↓
ajouter les valeurs trouvées à la liste à masquer,
ré-anonymiser les pages concernées depuis le texte d'origine
        ↓
recommencer (3 corrections au maximum) ──── encore des fuites ──→ ENVOI BLOQUÉ
```

- **Deux contrôleurs indépendants :** le vérificateur ne fonctionne pas comme l'anonymiseur. Il
  utilise des motifs, les clés de contrôle des IBAN, cartes et numéros de sécurité sociale, et
  cherche mot pour mot les valeurs déjà pseudonymisées ailleurs. Les deux ne ratent donc pas les
  mêmes choses.
- **Pourquoi recommencer :** ton nom peut être reconnu en page 1 mais raté par spaCy dans un
  libellé de virement en page 4. Le vérificateur le retrouve, mas ré-anonymise cette page, puis
  revérifie **tous** les documents : une valeur découverte dans le troisième fichier doit aussi
  être masquée si elle apparaît dans le premier.
- **En pratique :** la boucle s'arrête dès qu'une vérification ne trouve plus rien, en général
  juste après le premier passage. Sur le relevé de démonstration, il n'y a eu aucune itération
  supplémentaire.

Le message « Itération 1 : N fuite(s) corrigée(s) » signifie que le filet a servi. Pour que le
premier passage attrape ces valeurs directement, ajoute-les à `identite` dans `config.yaml`
(`mas anonymiser` permet de les repérer). Augmenter `iterations_max` ne sert à rien : si l'envoi
est bloqué, la solution est de déclarer la donnée.

### 2. Extracteur ⇄ contrôleur : la qualité de l'extraction

Cette boucle ne sert que pour les relevés dont le tableau n'est pas reconnu (sinon, les opérations
sont lues directement, sans IA). Pendant l'analyse, page par page :

1. l'IA extrait les opérations de la page ;
2. un contrôle en Python compare les montants extraits avec ceux imprimés sur la page ;
3. en cas d'écart (opération oubliée, signe inversé…) ou de réponse mal formée, il renvoie ses
   remarques à l'IA, qui recommence : **2 corrections au maximum par page**, et mas garde la
   meilleure tentative ;
4. les pages encore incohérentes sont signalées : « N page(s) avec des incohérences d'extraction
   non résolues : vérifie le rapport ».

Contrairement à la première boucle, **chaque correction est un appel à l'IA de plus, donc
payant**.

## Essayer sans tes données

Le générateur produit un relevé fictif de 3 à 6 mois, avec sa vérité terrain en JSON (opérations,
dépenses récurrentes, données personnelles) :

```bash
mas generer --n 1 --sortie donnees/demo
mas anonymiser donnees/demo/releve_0000.pdf --sortie donnees/demo/anonyme
mas analyser donnees/demo/releve_0000.pdf --sortie donnees/demo/rapport.md
```

Premier essai (octobre 2026, Claude Haiku 4.5, relevé de 4 mois) : aucune donnée personnelle en
clair, 7 dépenses récurrentes sur 7 retrouvées, 6 catégories sur 7 justes.

## Publier le code sans tes données

Le dépôt ne contient que le code, la documentation et les tests. Tout le reste est ignoré par git
(voir `.gitignore`) :

| Ignoré | Pourquoi |
|---|---|
| `config.yaml`, `.env` | ton identité déclarée, tes clés d'API |
| `releves/`, `rapports/`, `sortie_anonyme/` | tes relevés et tout ce que mas en tire |
| `donnees/`, `artefacts/` | relevés de démonstration, journaux d'optimisation |
| `*.pdf`, `*.csv`, `*.ofx`, `*.xlsx`, `*.png`… | relevés, exports bancaires et captures, où qu'ils soient |

Un `.gitignore` ne voit pas le **contenu** des fichiers : ton nom recopié dans un test, par
exemple. `mas check-repo` passe en revue les fichiers que git publierait et y cherche tes
données déclarées dans `config.yaml`, les valeurs de ton coffre (celles de plusieurs mots et les
numéros) et tes clés d'API. Il affiche le fichier, la ligne et le type de donnée, jamais la valeur.

Pour qu'il tourne avant chaque commit, active le crochet fourni, une fois par clone :

```bash
git config core.hooksPath .githooks
```

Un commit qui contient une de tes données est alors refusé. En cas de fausse alerte (un nom
inventé pour un test qui se trouve aussi dans ton coffre), change le nom dans le test ;
`git commit --no-verify` passe outre, à réserver aux cas que tu as vérifiés.

## Commandes

| Commande | Rôle | Options utiles |
|---|---|---|
| `mas init` | prépare le dossier : `config.yaml`, `.env`, `releves/`, `rapports/`, modèle spaCy (n'écrase rien) | `-c` |
| `mas anonymiser ENTRÉE` | anonymise seulement, rien n'est envoyé | `--sortie DOSSIER` |
| `mas analyser ENTRÉE` | anonymise, vérifie, analyse, écrit les rapports dans `rapports/` | `--sortie rapports/rapport.md`, `--oui` |
| `mas exporter RAPPORT.md` | régénère les pages HTML d'un rapport existant, sans rappeler l'IA (à partir de `rapport.json` ; sans lui, simple mise en page du Markdown) | `-c` |
| `mas coffre` | table pseudonymes → vraies valeurs (local) | |
| `mas generer` | relevés synthétiques (PDF + vérité JSON) | `--n`, `--sortie`, `--graine` |
| `mas optimiser` | optimise les agents avec GEPA | `--regenerer` |
| `mas evaluer` | score du programme courant | |
| `mas check-repo` | cherche tes données et tes fichiers personnels dans ce que git publierait | `--staged` |

`ENTRÉE` est un PDF, un ZIP de PDF ou un dossier. Toutes les commandes qui lisent la
configuration acceptent `-c chemin/config.yaml`.

## Optimisation avec GEPA

```bash
mas generer --n 5 --sortie donnees/apercu   # voir à quoi ressemblent les relevés de test
mas optimiser                               # génère 36 relevés, optimise, sauvegarde
mas evaluer                                 # score du programme courant
```

L'optimisation n'utilise **que des relevés synthétiques** (Faker) dont on connaît
la vérité : transactions, catégories, récurrences et données personnelles. Ils
passent par le vrai pipeline d'anonymisation, donc les agents apprennent sur des
textes identiques à ceux de production, sans tes données.

La métrique (`src/mas/optimisation/metrique.py`) note quatre axes et renvoie
à GEPA un retour ciblé sur le prédicteur qu'il est en train d'améliorer :

| Prédicteur   | Score             | Exemple de retour |
|--------------|-------------------|-------------------|
| extracteur   | F1 des opérations | « 3 opérations manquées : 2026-03-08 PRLV SEPA EDF… −90,79 » ; erreurs de signe ; récurrences ratées |
| categoriseur | précision         | « « CB UBER EATS 12/03 » classé alimentation, attendu restauration » |
| classeur     | précision         | « « PRLV SEPA BASIC FIT » classé obligatoire, attendu abonnement_optionnel » |
| (global)     | 0 si fuite        | toute donnée personnelle en clair dans la sortie annule le score |

Le programme optimisé est sauvegardé dans `artefacts/programme_optimise.json`
et chargé automatiquement par `mas analyser`. Les instructions réécrites
sont lisibles dans `artefacts/instructions_optimisees.json`.

Coût : avec `auto: light`, compte quelques centaines d'appels au modèle
d'analyse et quelques dizaines au modèle de réflexion. Commence avec
`n_train: 12`, `n_val: 6` pour un premier essai. Avec Claude Opus 5.5 comme modèle
de réflexion, mets `temperature_reflexion: null`.

## Tests (sans clé API)

```bash
pytest
```

Les tests utilisent un faux LLM déterministe (`tests/faux_llm.py`) pour exécuter
tout le pipeline, la boucle extracteur ⇄ contrôleur et une compilation GEPA. Ils
couvrent aussi la lecture directe des tableaux (relevé factice au format BRED : comptes,
totaux, libellés sur deux lignes, livrets, virements entre comptes), le calcul du budget et sa
répartition mois par mois,
l'anonymisation (dates et noms de livrets non masqués), la vérification du dépôt avant publication,
`mas init`, la page HTML (versions anonyme et personnelle, déficit,
injection de HTML), la lecture du `.env`, l'affichage unique des messages répétés, l'avancement de
l'analyse et le calcul des tokens et du coût.

## Structure

```
src/mas/
  config.py             lecture de config.yaml en objets typés
  modeles.py            structures de données, définitions des catégories envoyées à l'IA
  ingestion.py          PDF/ZIP -> texte page par page, tableaux | col | col |
  releve.py             lecture du tableau ligne par ligne, comptes, soldes et totaux
  anonymisation/
    reconnaisseurs.py   regex FR + GLiNER
    validateurs.py      Luhn, IBAN mod 97, clé RIB, clé NIR
    moteur.py           Presidio + résolution des chevauchements + pseudonymisation
    coffre.py           table de correspondance chiffrée (Fernet)
  verification.py       vérificateur de fuites indépendant (+ LLM local optionnel)
  depot.py              mas check-repo : aucune donnée personnelle dans le dépôt git
  agents/
    signatures.py       instructions de départ des agents (réécrites par GEPA)
    programme.py        programme DSPy + contrôleur
    synthese.py         calcul du budget + rapport
  recurrence.py         détection déterministe des récurrences
  synthetique.py        générateur de relevés + vérité terrain
  optimisation/         jeux de données, métrique avec feedback, boucle GEPA
  orchestrateur.py      enchaîne tout, bloque l'envoi en cas de fuite
  page.py               page HTML du rapport (barre des revenus, catégories, mois par mois, récurrences)
  export.py             mise en page simple d'un rapport Markdown (anciens rapports)
  suivi.py              durées, tokens et coût estimé d'une analyse
  cli.py                commandes mas ..., chargement du .env
tests/                  faux LLM, relevé BRED factice, lecture, budget, catégories,
                        anonymisation, pipeline, page, export, journal, suivi
docs/categories.md      ce que l'IA range dans chaque catégorie
.githooks/pre-commit    lance mas check-repo avant chaque commit
config.example.yaml     modèle de config.yaml ; .env.example : modèle de .env (copiés par mas init)
```

## Adapter à ta banque

Les relevés réels varient d'une banque à l'autre. Lance `mas anonymiser` sur un vrai relevé et
relis le résultat :

- **le tableau est-il relu ligne par ligne ?** Chaque opération doit apparaître sur sa propre
  ligne `| date | libellé | débit | crédit |`. C'est le cas dès que le tableau a un en-tête
  « Date … Débit … Crédit » ; sinon, l'extraction passe par l'IA ;
- **les données personnelles sont-elles masquées, et seulement elles ?** Ajoute au besoin des mots
  à `liste_blanche` (marchands masqués à tort) ou à `identite.autres` (données oubliées).

Pour aller plus loin, ajoute le format de ta banque au générateur synthétique et relance
`mas optimiser`.

## Limites

- **Anonymisation imparfaite :** l'anonymisation automatique n'est jamais parfaite. Relis la
  sortie de `mas anonymiser` sur tes premiers relevés.
- **Ville des achats visible :** dans « CB CARREFOUR VILLEJUIF », la ville reste lisible. C'est un
  choix pour garder les marchands lisibles. Ajoute ta ville dans `identite.autres` si tu veux la
  masquer.
- **PDF scannés :** sans l'option OCR, une page scannée sort **vide, sans message d'erreur**. Si
  `mas anonymiser` produit des pages vides, installe `".[ocr]"` et tesseract (voir
  [Installation](#installation)).
- **Catégories à vérifier :** les catégories sont choisies par l'IA et peuvent se tromper. Les
  montants et les totaux, eux, sont calculés en Python.
- **Tableaux non reconnus :** un relevé sans en-tête « Date … Débit … Crédit » (une seule colonne
  « Montant » signée, par exemple) passe par l'extraction par l'IA, moins fiable et sans contrôle
  au centime.
- **« À ton nom » est une déduction :** un virement vers quelqu'un qui porte ton nom est mis à part
  comme un mouvement entre tes comptes. Vérifie-le dans le rapport, et déclare tes vrais comptes
  dans `analyse.comptes_personnels`.
- **Épargne dans une autre banque :** un virement vers un livret qui ne figure pas sur le même
  relevé n'est reconnu que s'il est à ton nom ou si ce compte est déclaré.
- **Clé du coffre :** garde `~/.mas/cle.key`, ou la variable `MAS_CLE_COFFRE`. Sans elle, la table
  des pseudonymes ne peut plus être déchiffrée.
- **Matériel :** pas de GPU nécessaire. spaCy et Presidio tournent sur CPU ; GLiNER et le
  vérificateur LLM local (Ollama) sont optionnels.

## Licence

[MIT](LICENSE) : tu peux utiliser, copier, modifier et redistribuer ce code, y compris dans un
projet commercial, à condition de garder la mention de copyright et la licence. Le logiciel est
fourni sans garantie.
