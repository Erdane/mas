"""Ce qui ne colle pas : un mois dont les lignes ne retombent pas sur le net, ton classeur qui dit autre chose que le
bulletin de l'employeur, une ligne saisie avec le mauvais signe."""
from __future__ import annotations

from collections import Counter

from .format import eur
from .modeles import Bulletin

TOLERANCE = 0.005


def _montant(x: float) -> int:
    return round(x * 100)


def _sans_pareil(a: list, b: list) -> list:
    """Les lignes de a dont le montant n'a pas d'égal dans b (chaque égal ne sert qu'une fois)."""
    reste = Counter(_montant(l.montant) for l in b)
    seules = []
    for l in a:
        cle = _montant(l.montant)
        if reste[cle]:
            reste[cle] -= 1
        else:
            seules.append(l)
    return seules


def _indice_ecart(b: Bulletin, historique: list[Bulletin]) -> str:
    """Une piste pour un mois dont les lignes ne retombent pas sur le net (sans bulletin PDF pour comparer)."""
    e = b.ecart
    if 0 < e < 3:
        return ("sans doute une petite cotisation remboursée : le bulletin l'imprime dans la colonne des gains, au milieu "
                "des cotisations")
    for l in b.lignes:                          # une ligne saisie à l'envers compte deux fois
        if abs(2 * l.montant + e) < 0.015:
            return f"« {l.libelle} » a peut-être le mauvais signe ({eur(l.montant)} saisis, {eur(-l.montant)} attendus)"
    habituels = Counter()
    for h in historique:
        for l in h.lignes:
            habituels[(l.libelle, _montant(l.montant))] += 1
    for (lib, cents), n in habituels.most_common():
        if n >= 3 and abs(cents / 100 - e) < 0.015 and not any(x.libelle == lib for x in b.lignes):
            return f"il manque peut-être « {lib} » ({eur(cents / 100)}), présent d'habitude"
    return f"il manque {eur(e)} de lignes" if e > 0 else f"il y a {eur(-e)} de lignes en trop"


def ecarts_internes(bulletins: list[Bulletin], seuil: float = 0.05) -> list[dict]:
    """Les mois où lignes − cotisations ≠ net avant impôt."""
    res = []
    for i, b in enumerate(bulletins):
        if abs(b.ecart) >= seuil:
            res.append({"mois": b.mois, "source": b.source, "ecart": b.ecart, "petit": abs(b.ecart) < 3,
                        "piste": _indice_ecart(b, bulletins[max(0, i - 12):i + 12])})
    return res


def comparer(excel: list[Bulletin], pdfs: list[Bulletin]) -> list[dict]:
    """Mois par mois, ce que ton classeur dit autrement que le bulletin. `grave` : le net ou l'impôt diffère ; sinon
    seules des lignes sont mal saisies (le total brut de ta Synthèse est faux, pas ce que tu as touché)."""
    par_mois = {b.mois: b for b in pdfs}
    res = []
    for x in excel:
        p = par_mois.get(x.mois)
        if p is None:
            continue
        constats = []
        for nom, a, b in (("net avant impôt", x.net_avant_impot, p.net_avant_impot), ("impôt", x.impot, p.impot),
                          ("net payé", x.net_paye, p.net_paye)):
            if abs(a - b) > 0.01:
                constats.append(f"{nom} : {eur(a)} dans ton classeur, {eur(b)} sur le bulletin")
        grave = bool(constats)
        en_trop, manquent = _sans_pareil(x.lignes, p.lignes), _sans_pareil(p.lignes, x.lignes)
        for l in list(en_trop):                 # même montant, signe inversé
            inverse = next((m for m in manquent if _montant(m.montant) == -_montant(l.montant)), None)
            if inverse:
                constats.append(f"« {l.libelle} » : {eur(l.montant)} dans ton classeur, {eur(inverse.montant)} sur le bulletin "
                                f"(« {inverse.libelle} »)")
                en_trop.remove(l)
                manquent.remove(inverse)
        # Le même argent, saisi en une ligne d'un côté et en deux de l'autre : rien à corriger
        for nature in {l.nature for l in en_trop}:
            a = [l for l in en_trop if l.nature == nature]; b = [m for m in manquent if m.nature == nature]
            if b and abs(sum(l.montant for l in a) - sum(m.montant for m in b)) < 0.01:
                en_trop = [l for l in en_trop if l not in a]; manquent = [m for m in manquent if m not in b]
        if en_trop and manquent and abs(sum(l.montant for l in en_trop) - sum(m.montant for m in manquent)) < 0.01:
            constats.append("même total, rangé autrement : " + " + ".join(f"« {l.libelle} » ({eur(l.montant)})" for l in en_trop)
                            + " dans ton classeur, " + " + ".join(f"« {m.libelle} » ({eur(m.montant)})" for m in manquent)
                            + " sur le bulletin")
            en_trop, manquent = [], []
        appariees = []
        for l in list(en_trop):                 # même ligne, autre montant (même nature)
            autre = next((m for m in manquent if m.nature == l.nature), None)
            if autre:
                appariees.append((l, autre))
                en_trop.remove(l)
                manquent.remove(autre)
        for l, autre in appariees:
            constats.append(f"« {l.libelle} » : {eur(l.montant)} dans ton classeur, {eur(autre.montant)} sur le bulletin "
                            f"(« {autre.libelle} »)")
        constats += [f"« {m.libelle} » ({eur(m.montant)}) est sur le bulletin, pas dans ton classeur" for m in manquent]
        constats += [f"« {l.libelle} » ({eur(l.montant)}) est dans ton classeur, pas sur le bulletin" for l in en_trop]
        d_cot = round(x.cotisations - p.cotisations, 2)
        if abs(d_cot) > 0.01:
            constats.append(f"cotisations : {eur(x.cotisations)} dans ton classeur, {eur(p.cotisations)} sur le bulletin"
                            + (" (le bulletin rembourse une cotisation que ton classeur ne compte pas)" if 0 < d_cot < 5 and not grave else ""))
        if not constats:
            continue
        ampleur = max([abs(x.brut - p.brut), abs(d_cot)] + [abs(m.montant) for m in manquent + en_trop] + [0])
        res.append({"mois": x.mois, "grave": grave, "petit": not grave and ampleur < 3, "constats": constats,
                    "fichier": p.fichier})
    return res
