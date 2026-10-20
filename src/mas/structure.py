"""Squelette d'un relevé, sans aucune donnée : de quoi apprendre une nouvelle mise en page à mas.

Pour chaque PDF, désigné par un numéro (pas par son nom) : le nombre de pages, si la lecture directe
reconnaît le tableau, puis, page par page, les lignes qui ressemblent à un en-tête de tableau et les
premières lignes qui les suivent.

Rien de personnel ne peut en sortir :
- un mot n'est affiché que s'il fait partie d'une liste fixe de termes de colonnes (MOTS_AFFICHES) ;
  un mot qui commence par l'un de ces termes (« Dateopération », mots collés dans le PDF) devient
  « date… » ; tout autre mot devient « … » ;
- des lignes d'opérations, seul le type de chaque élément est montré (date courte, date longue, montant,
  nombre, texte) avec sa position horizontale, jamais sa valeur.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pdfplumber

from .lecteur_deduit import LecteurDeduit
from .releve import LecteurReleve, _lignes

MOTS_AFFICHES = {
    "date", "dates", "dateop", "operation", "operations", "ope", "op", "libelle", "libelles", "intitule",
    "valeur", "val", "debit", "debits", "credit", "credits", "montant", "montants", "somme", "euros", "eur",
    "solde", "soldes", "total", "totaux", "nouveau", "ancien", "precedent", "report", "nature", "detail",
    "details", "description", "reference", "ref", "type", "mouvements", "periode", "sens", "devise",
    "de", "des", "du", "la", "le", "en", "au", "aux", "l", "d", "a", "et",
}
COLONNES = {"debit", "credit", "montant", "libelle", "operation", "valeur", "nature", "detail", "description", "solde"}
PREFIXES = sorted(COLONNES | {"date", "total", "nouveau", "ancien", "report", "devise", "reference"}, key=len, reverse=True)
MOTS_CLES = ("solde", "total", "totaux", "report", "nouveau", "ancien")
LIGNES_APRES_ENTETE = 4
LIGNES_AVANT_OPERATIONS = 3

DATE_LONGUE = re.compile(r"\d{2}[./-]\d{2}[./-](\d{4}|\d{2})")
DATE_COURTE = re.compile(r"\d{2}[./]\d{2}")
MONTANT = re.compile(r"[-+]?\d{1,3}(?:[ .  ]\d{3})*,\d{2}(?:€|eur)?|[-+]?\d+[.,]\d{2}(?:€|eur)?", re.IGNORECASE)
NOMBRE = re.compile(r"[-+]?\d+")


def _simple(texte: str) -> str:
    texte = unicodedata.normalize("NFKD", texte.lower())
    return re.sub(r"[^a-z]", "", "".join(c for c in texte if not unicodedata.combining(c)))


def type_de(mot: str) -> str:
    if DATE_LONGUE.fullmatch(mot):
        return "DATE_LONGUE"
    if DATE_COURTE.fullmatch(mot):
        return "DATE_COURTE"
    if MONTANT.fullmatch(mot):
        return ("-" if mot.startswith("-") else "+" if mot.startswith("+") else "") + "MONTANT"
    if NOMBRE.fullmatch(mot):
        return "NOMBRE"
    if mot in {"€", "EUR", "eur"}:
        return "€"
    return "TEXTE"


def mot_affichable(mot: str) -> str:
    s = _simple(mot)
    if any(c.isdigit() for c in mot) or not s:
        return "…"
    if s in MOTS_AFFICHES:
        return mot.lower()
    prefixe = next((p for p in PREFIXES if s.startswith(p)), None)
    return f"{prefixe}…" if prefixe else "…"


def est_entete(ligne: list[dict]) -> bool:
    mots = {_simple(w["text"]) for w in ligne}
    return any(m.startswith("date") for m in mots) and len({c for c in COLONNES if any(m.startswith(c) for m in mots)}) >= 1


def squelette_entete(ligne: list[dict]) -> str:
    morceaux, precedent = [], None
    for w in ligne:
        texte = mot_affichable(w["text"])
        if texte == "…" and precedent == "…":
            continue
        morceaux.append(f"{texte}@{round(w['x0'])}")
        precedent = texte
    return " ".join(morceaux)


def squelette_ligne(ligne: list[dict]) -> str:
    """Types et positions : « DATE_LONGUE@36 TEXTE×4@80 -MONTANT@455 ». Les mots d'un même texte sont regroupés,
    un nombre suivi d'un montant (« 1 234,56 » coupé en deux) ne fait qu'un montant."""
    morceaux: list[list] = []          # [type, x, nombre de mots, x1]
    for w in ligne:
        t = type_de(w["text"])
        dernier = morceaux[-1] if morceaux else None
        if dernier and t == "TEXTE" and dernier[0] == "TEXTE":
            dernier[2] += 1
            dernier[3] = w["x1"]
        elif dernier and t.endswith("MONTANT") and dernier[0] == "NOMBRE" and w["x0"] - dernier[3] < 6:
            dernier[0], dernier[3] = t, w["x1"]
        else:
            morceaux.append([t, round(w["x0"]), 1, w["x1"]])
    return " ".join(f"{t}{'×' + str(n) if t == 'TEXTE' and n > 1 else ''}@{x}" for t, x, n, _ in morceaux)


def squelette_mixte(ligne: list[dict]) -> str:
    """Pour les lignes au-dessus des opérations (l'en-tête) : mots affichables, types pour le reste."""
    morceaux = []
    for w in ligne:
        t = type_de(w["text"])
        texte = mot_affichable(w["text"]) if t == "TEXTE" else t
        if not (texte == "…" and morceaux and morceaux[-1].startswith("…@")):
            morceaux.append(f"{texte}@{round(w['x0'])}")
    return " ".join(morceaux)


def mots_cles(ligne: list[dict]) -> set[str]:
    """Mots-clés présents, même collés à d'autres (« NOUVEAUSOLDE ») : seule leur présence est notée."""
    simples = [_simple(w["text"]) for w in ligne]
    return {m for m in MOTS_CLES if any(m in s for s in simples)}


def ressemble_a_une_operation(ligne: list[dict]) -> bool:
    return bool(ligne) and type_de(ligne[0]["text"]).startswith("DATE") and any(type_de(w["text"]).endswith("MONTANT") for w in ligne)


def decrire_pdf(chemin: Path) -> dict:
    lecteur = LecteurReleve()
    deduit = LecteurDeduit()
    pages = []
    with pdfplumber.open(chemin) as pdf:
        for i, page in enumerate(pdf.pages):
            lecteur.lire_page(page, i)
            deduit.ajouter_page(page, i)
            lignes = _lignes(page)
            entetes = []
            for k, ligne in enumerate(lignes):
                if est_entete(ligne):
                    suite = [squelette_ligne(l) for l in lignes[k + 1:k + 1 + LIGNES_APRES_ENTETE]]
                    entetes.append({"y": round(ligne[0]["top"]), "entete": squelette_entete(ligne), "suite": suite})
            debuts = [type_de(l[0]["text"]) for l in lignes if l]
            premiere = next((k for k, l in enumerate(lignes) if ressemble_a_une_operation(l)), None)
            operations = None
            if premiere is not None:
                operations = {
                    "avant": [squelette_mixte(l) for l in lignes[max(0, premiere - LIGNES_AVANT_OPERATIONS):premiere]],
                    "lignes": [squelette_ligne(l) for l in lignes[premiere:premiere + LIGNES_APRES_ENTETE]],
                }
            pages.append({
                "lignes": len(lignes),
                "commencent_par_date_longue": debuts.count("DATE_LONGUE"),
                "commencent_par_date_courte": debuts.count("DATE_COURTE"),
                "avec_montant": sum(1 for l in lignes if any(type_de(w["text"]).endswith("MONTANT") for w in l)),
                "mots_cles": sorted(set().union(*(mots_cles(l) for l in lignes))) if lignes else [],
                "entetes": entetes[:3],
                "operations": operations,
            })
            page.flush_cache()
    structure = lecteur.resultat() or deduit.resultat()
    if structure is not None:
        return {"pages": pages, "reconnu": True, "lecture": f"reconnue, {structure.lecture}"}
    return {"pages": pages, "reconnu": False, "lecture": f"non reconnue ({deduit.raison})"}


def decrire(entree: Path, tous: bool = False) -> list[str]:
    fichiers = sorted(entree.glob("*.pdf")) if entree.is_dir() else [entree]
    sortie = []
    for numero, chemin in enumerate(fichiers, 1):
        d = decrire_pdf(chemin)
        if d["reconnu"] and not tous:
            continue
        sortie.append(f"Document {numero}/{len(fichiers)} : {len(d['pages'])} page(s), lecture directe : "
                      f"{d['lecture']}")
        for p, page in enumerate(d["pages"], 1):
            sortie.append(f"  page {p} : {page['lignes']} lignes, {page['commencent_par_date_longue']} commencent par une "
                          f"date longue, {page['commencent_par_date_courte']} par une date courte, "
                          f"{page['avec_montant']} avec un montant ; mots repérés : {', '.join(page['mots_cles']) or 'aucun'}")
            for e in page["entetes"]:
                sortie.append(f"    en-tête (y={e['y']}) : {e['entete']}")
                sortie += [f"      {ligne}" for ligne in e["suite"]]
            if page["operations"]:
                sortie.append("    au-dessus de la première ligne qui ressemble à une opération (date + montant) :")
                sortie += [f"      {ligne}" for ligne in page["operations"]["avant"]]
                sortie.append("    premières lignes d'opérations :")
                sortie += [f"      {ligne}" for ligne in page["operations"]["lignes"]]
    return sortie or ["Tous les documents sont lus directement : rien à décrire."]
