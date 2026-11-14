"""Lecture du classeur : une feuille « Brut AAAA » (une colonne par ligne de paie, puis « Cotisations ») et une
feuille « Net AAAA » (net avant impôt, net après impôt) par année, un mois par ligne.

Le classeur n'est jamais modifié. mas y relève aussi ce qui cloche dans ses propres calculs (`verifier_classeur`).
Les libellés (en-têtes de colonnes) passent par l'anonymisation avant d'être lus (`renommer`).
"""
from __future__ import annotations

import re
from pathlib import Path

import openpyxl

from .format import eur
from .modeles import Bulletin, Ligne
from .natures import nature_de, normaliser

FEUILLE = re.compile(r"^\s*(Brut|Net)\s+(\d{4})\s*$", re.I)


def _nombre(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _ligne_entete(feuille) -> int | None:
    for r in range(1, min(feuille.max_row, 10) + 1):
        if normaliser(str(feuille.cell(r, 1).value or "")) == "MOIS":
            return r
    return None


def _mois(feuille, entete: int):
    """(numéro de ligne, mois 1-12) des lignes de mois qui suivent l'en-tête."""
    for r in range(entete + 1, entete + 13):
        m = feuille.cell(r, 1).value
        if isinstance(m, (int, float)) and 1 <= int(m) <= 12:
            yield r, int(m)


def _colonne(entetes: dict[str, int], *mots: str) -> int | None:
    for nom, c in entetes.items():
        if all(m in nom for m in mots):
            return c
    return None


def lire_classeur(chemin: Path | str, corrections: dict[str, str] | None = None, renommer=None) -> list[Bulletin]:
    """Un Bulletin par mois rempli dans les deux feuilles (Brut et Net) de son année. `renommer` : le libellé
    anonymisé de chaque colonne."""
    classeur = openpyxl.load_workbook(chemin, data_only=True, read_only=False)
    feuilles: dict[tuple[str, int], object] = {}
    for nom in classeur.sheetnames:
        if m := FEUILLE.match(nom):
            feuilles[(m.group(1).capitalize(), int(m.group(2)))] = classeur[nom]
    bulletins = []
    for annee in sorted({a for _, a in feuilles}):
        brut, net = feuilles.get(("Brut", annee)), feuilles.get(("Net", annee))
        if brut is None or net is None:
            continue
        eb, en = _ligne_entete(brut), _ligne_entete(net)
        if not eb or not en:
            continue
        colonnes = []          # (colonne, libellé) des lignes de paie, jusqu'à « Cotisations »
        col_cotis = None
        for c in range(2, brut.max_column + 1):
            titre = brut.cell(eb, c).value
            if titre is None:
                continue
            if normaliser(str(titre)).startswith("COTISATION"):
                col_cotis = c
                break
            libelle = re.sub(r"\s+", " ", str(titre)).strip()
            colonnes.append((c, renommer(libelle) if renommer else libelle))
        entetes_net = {normaliser(str(net.cell(en, c).value or "")): c for c in range(1, net.max_column + 1)}
        c_avant = _colonne(entetes_net, "NET", "AVANT")
        c_apres = _colonne(entetes_net, "NET", "APRES")
        c_impot = _colonne(entetes_net, "IMPOT")
        nets = {}
        for r, m in _mois(net, en):
            avant = _nombre(net.cell(r, c_avant).value) if c_avant else None
            apres = _nombre(net.cell(r, c_apres).value) if c_apres else None
            impot = _nombre(net.cell(r, c_impot).value) if c_impot else None
            if avant is not None and (apres is not None or impot is not None):
                nets[m] = (avant, round(avant - apres, 2) if apres is not None else impot)
        for r, m in _mois(brut, eb):
            lignes = [Ligne(lib, round(v, 2), nature_de(lib, corrections))
                      for c, lib in colonnes if (v := _nombre(brut.cell(r, c).value))]
            if not lignes or m not in nets:
                continue
            cotis = _nombre(brut.cell(r, col_cotis).value) if col_cotis else None
            avant, impot = nets[m]
            bulletins.append(Bulletin(mois=f"{annee}-{m:02d}", lignes=lignes, cotisations=round(abs(cotis or 0.0), 2),
                                      net_avant_impot=round(avant, 2), impot=round(impot or 0.0, 2), source="excel",
                                      fichier=Path(chemin).name))
    return bulletins


def verifier_classeur(chemin: Path | str, bulletins: list[Bulletin]) -> list[dict]:
    """Ce que les formules du classeur calculent de travers : une moyenne qui compte les mois vides, une
    étiquette d'année qui n'est pas celle de la feuille. (Les #DIV/0! des mois pas encore remplis sont normaux.)"""
    classeur = openpyxl.load_workbook(chemin, data_only=True)
    remarques = []
    par_annee: dict[int, list[Bulletin]] = {}
    for b in bulletins:
        par_annee.setdefault(b.annee, []).append(b)
    for nom in classeur.sheetnames:
        m = FEUILLE.match(nom)
        if not m:
            continue
        sorte, annee, f = m.group(1).capitalize(), int(m.group(2)), classeur[nom]
        for ligne in f.iter_rows():
            for cellule in ligne:
                v = cellule.value
                if not isinstance(v, str):
                    continue
                # « Annuel » suivi d'une année : celle de la feuille ?
                if normaliser(v) == "ANNUEL":
                    for dr, dc in ((1, 0), (1, 1), (0, 1)):
                        voisin = f.cell(cellule.row + dr, cellule.column + dc).value
                        if isinstance(voisin, int) and 2000 <= voisin <= 2100 and voisin != annee:
                            remarques.append({"feuille": nom, "cellule": f.cell(cellule.row + dr, cellule.column + dc).coordinate,
                                              "texte": f"le total annuel est étiqueté {voisin}, sur la feuille {annee}"})
                # Moyennes : sur les mois remplis seulement
                if sorte == "Net" and normaliser(v).startswith("MOYENNE") and par_annee.get(annee):
                    valeur = _nombre(f.cell(cellule.row + 1, cellule.column).value)
                    mois = par_annee[annee]
                    cle = normaliser(v)
                    attendu = None
                    if "IMPOT" in cle and "APRES" not in cle and "AVANT" not in cle:
                        attendu = sum(b.impot for b in mois) / len(mois)
                    elif "AVANT" in cle:
                        attendu = sum(b.net_avant_impot for b in mois) / len(mois)
                    elif "APRES" in cle:
                        attendu = sum(b.net_paye for b in mois) / len(mois)
                    if valeur is not None and attendu is not None and abs(valeur - attendu) > 0.5:
                        remarques.append({"feuille": nom, "cellule": f.cell(cellule.row + 1, cellule.column).coordinate,
                                          "texte": f"« {v.strip()} » vaut {eur(valeur)} ; sur les {len(mois)} mois "
                                                   f"remplis, c'est {eur(attendu)} (les mois vides comptent pour zéro)"})
    return remarques
