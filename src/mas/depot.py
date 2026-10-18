"""Avant de publier : ni fichier personnel ni aucune de tes données dans le dépôt git.

`mas check-repo` (et le crochet .githooks/pre-commit) passe en revue les fichiers que git
publierait. Il signale les fichiers qui n'ont rien à y faire (config.yaml, .env, relevés,
rapports…) et cherche dans tous les autres tes données déclarées dans config.yaml, les valeurs
réelles de ton coffre et tes clés d'API. Les valeurs trouvées ne sont jamais affichées : seulement
le fichier, la ligne et le type de donnée.
"""

from __future__ import annotations

import re
import subprocess
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

from .anonymisation.coffre import Coffre
from .anonymisation.reconnaisseurs import MOTS_NON_NOMS, valeur_plausible
from .config import Config

# Même s'ils échappent au .gitignore (git add -f, autre nom de dossier…)
FICHIERS_INTERDITS = [
    (re.compile(r"(^|/)config\.yaml$"), "ta configuration (identité déclarée)"),
    (re.compile(r"(^|/)\.env$"), "tes clés d'API"),
    (re.compile(r"(^|/)(releves|rapports|donnees|sortie_anonyme|artefacts)/"), "dossier de données personnelles"),
    (re.compile(r"(^|/)rapport[^/]*\.(md|html|json)$|_anonyme\.\w+$"), "rapport d'analyse"),
    (re.compile(r"\.(pdf|zip|csv|ofx|qif|qfx|xls|xlsx|ods|key|bin|log)$", re.IGNORECASE),
     "relevé, export bancaire, clé ou journal"),
]
CLE_API = re.compile(r"sk-ant-[\w-]{20,}|sk-[A-Za-z0-9]{32,}")
VARIABLE_SECRETE = re.compile(r"KEY|TOKEN|SECRET|PASS|CLE", re.IGNORECASE)


@dataclass
class Probleme:
    fichier: str
    ligne: int | None       # None : c'est le fichier lui-même qui n'a rien à faire dans le dépôt
    motif: str


@dataclass
class Recherche:
    motif: str              # ce qui est affiché, jamais la valeur : "identite.noms", "coffre PERSONNE"…
    regex: re.Pattern
    compacte: bool          # numéros : comparés sans espaces, points ni tirets


def _simple(texte: str) -> str:
    sans_accents = "".join(c for c in unicodedata.normalize("NFKD", texte) if not unicodedata.combining(c))
    return sans_accents.casefold()


def _compact(texte: str) -> str:
    return re.sub(r"[\s.\-/]", "", texte)


def _recherche(valeur: str, motif: str) -> Recherche | None:
    valeur = _simple(valeur.strip())
    if sum(c.isdigit() for c in valeur) >= 5:                   # IBAN, compte, téléphone, référence
        compact = _compact(valeur)
        return Recherche(motif, re.compile(re.escape(compact)), True) if len(compact) >= 6 else None
    mots = re.findall(r"\w+", valeur)
    if not mots or len("".join(mots)) < 4:
        return None
    return Recherche(motif, re.compile(r"(?<!\w)" + r"\W+".join(map(re.escape, mots)) + r"(?!\w)"), False)


def recherches(config: Config, dossier: Path) -> tuple[list[Recherche], list[str]]:
    """Ce qu'on cherche dans les fichiers, et les avertissements (coffre illisible…)."""
    valeurs: list[tuple[str, str]] = []
    for champ, liste in config.identite.model_dump().items():
        for v in liste:
            if v and v.strip():
                valeurs.append((v, f"identite.{champ}"))
                if champ == "noms":                              # le nom de famille seul suffit à t'identifier
                    valeurs += [(m, "identite.noms (un mot)") for m in v.split() if len(m) >= 4]
    env = dossier / ".env"
    if env.exists():
        valeurs += [(v, f".env {k}") for k, v in dotenv_values(env).items()
                    if v and len(v) >= 8 and VARIABLE_SECRETE.search(k)]

    avertissements = []
    chemin = Path(config.coffre.chemin).expanduser()
    if chemin.exists():
        communs = {m.upper() for m in [*config.anonymisation.liste_blanche, *MOTS_NON_NOMS]}
        try:
            coffre = Coffre(chemin)
        except Exception as e:
            avertissements.append(f"Coffre illisible ({e}) : ses valeurs n'ont pas été recherchées.")
        else:
            # Un mot seul est trop ambigu (anciens faux positifs : « Page », un marchand…) :
            # seulement les valeurs de plusieurs mots (« Jean Dupont ») et les numéros.
            valeurs += [(v, f"coffre {jeton}") for jeton, v in coffre.valeurs.items()
                        if v.upper() not in communs and valeur_plausible(v, communs)
                        and (len(re.findall(r"[^\W\d_]{2,}", v)) >= 2 or sum(c.isdigit() for c in v) >= 5)]
    trouvees = [r for v, motif in valeurs if (r := _recherche(v, motif))]
    return trouvees, avertissements


def fichiers_publies(dossier: Path, indexes: bool = False) -> list[str]:
    """Fichiers suivis par git ou qui le seraient au prochain `git add .` (.gitignore respecté).
    `indexes` : seulement les fichiers prêts à être commités (crochet pre-commit)."""
    commande = (["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"] if indexes
                else ["git", "ls-files", "--cached", "--others", "--exclude-standard"])
    sortie = subprocess.run(commande, cwd=dossier, capture_output=True, text=True, check=True).stdout
    return [f for f in sortie.splitlines() if f.strip()]


def _contenu(dossier: Path, fichier: str, indexes: bool) -> str | None:
    if indexes:                                                  # la version qui sera commitée
        brut = subprocess.run(["git", "show", f":{fichier}"], cwd=dossier, capture_output=True).stdout
    else:
        chemin = dossier / fichier
        if not chemin.is_file():
            return None
        brut = chemin.read_bytes()
    if b"\0" in brut[:4096]:                                     # fichier binaire
        return None
    return brut.decode("utf-8", errors="replace")


def racine_du_depot(dossier: Path) -> Path:
    sortie = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=dossier, capture_output=True,
                            text=True, check=True).stdout
    return Path(sortie.strip())


def verifier(dossier: Path, config: Config, indexes: bool = False) -> tuple[list[Probleme], list[str]]:
    dossier = racine_du_depot(dossier)
    a_chercher, avertissements = recherches(config, dossier)
    problemes = []
    for fichier in fichiers_publies(dossier, indexes):
        interdit = next((motif for regex, motif in FICHIERS_INTERDITS if regex.search(fichier)), None)
        if interdit:
            problemes.append(Probleme(fichier, None, interdit))
            continue
        texte = _contenu(dossier, fichier, indexes)
        if texte is None:
            continue
        for numero, ligne in enumerate(texte.splitlines(), 1):
            if CLE_API.search(ligne):
                problemes.append(Probleme(fichier, numero, "clé d'API"))
            simple = _simple(ligne)
            compacte = _compact(simple)
            for r in a_chercher:
                if r.regex.search(compacte if r.compacte else simple):
                    problemes.append(Probleme(fichier, numero, r.motif))
    return problemes, avertissements
