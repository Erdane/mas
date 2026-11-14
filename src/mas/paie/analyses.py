"""Ce que mas tire de tes bulletins : augmentations, règles de paie, calendrier, impôts, pouvoir d'achat.

Tout se calcule sur la liste des bulletins, un par mois, du plus ancien au plus récent. Rien ne dépend d'un
employeur : les pourcentages des primes, le calendrier du 13e mois ou des primes annuelles sont déduits de
l'historique lui-même.
"""
from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict

from .inflation import indice_au
from .modeles import Bulletin
from .natures import NATURES, normaliser

EXTRAS = ("treizieme", "variable", "interessement", "exceptionnelle", "rappel")
SEUIL_EXTRA = 50.0


def mois_plus(aaaa_mm: str, n: int) -> str:
    t = int(aaaa_mm[:4]) * 12 + int(aaaa_mm[5:7]) - 1 + n
    return f"{t // 12}-{t % 12 + 1:02d}"


def mois_entre(a: str, b: str) -> int:
    return (int(b[:4]) - int(a[:4])) * 12 + int(b[5:7]) - int(a[5:7])


def remuneration(b: Bulletin) -> float:
    """Ce que l'employeur te verse pour ton travail : tout sauf les frais remboursés, CET compris (c'est ton
    épargne, mise de côté avant le net)."""
    return round(sum(l.montant for l in b.lignes if l.nature not in ("frais", "cet")), 2)


def emploi_actuel(bulletins: list[Bulletin]) -> tuple[list[Bulletin], list[Bulletin]]:
    """(les mois de l'emploi actuel, ceux d'avant) : avant, un stage ou des mois sans salaire de base."""
    debut = 0
    for i, b in enumerate(bulletins):
        if b.somme("stage") or b.base <= 0:
            debut = i + 1
    return bulletins[debut:], bulletins[:debut]


def mois_manquants(bulletins: list[Bulletin]) -> list[str]:
    if not bulletins:
        return []
    presents = {b.mois for b in bulletins}
    m, fin, manque = bulletins[0].mois, bulletins[-1].mois, []
    while m < fin:
        if m not in presents:
            manque.append(m)
        m = mois_plus(m, 1)
    return manque


# --- augmentations ------------------------------------------------------------------------------------------

def _rappel_de_base(b: Bulletin) -> float:
    return round(sum(l.montant for l in b.lignes if l.nature == "rappel"
                     and re.search(r"REMUNERATION|SALAIRE|TRAITEMENT", normaliser(l.libelle))), 2)


def augmentations(bulletins: list[Bulletin]) -> list[dict]:
    """Chaque changement du salaire de base. Un rappel (« … MOIS ANTER ») égal à k fois la hausse dit qu'elle
    s'applique depuis k mois plus tôt : l'augmentation versée en avril vaut depuis janvier."""
    res, pris = [], set()
    for i in range(1, len(bulletins)):
        avant, b = bulletins[i - 1], bulletins[i]
        if avant.base <= 0 or abs(b.base - avant.base) < 0.5:
            continue
        delta = round(b.base - avant.base, 2)
        k, rappel, mois_rappel = 0, None, None
        for c in bulletins[i:i + 4]:
            r = _rappel_de_base(c)
            if r and c.mois not in pris and delta > 0:
                n = round(r / delta)
                if n >= 1 and abs(r - n * delta) <= 0.03 * n + 0.02:
                    k, rappel, mois_rappel = n + mois_entre(b.mois, c.mois) - mois_entre(b.mois, c.mois), r, c.mois
                    pris.add(c.mois)
                    break
        effet = mois_plus(b.mois, -k) if k else b.mois
        res.append({"mois": b.mois, "avant": avant.base, "apres": b.base, "delta": delta,
                    "pct": round(100 * delta / avant.base, 2), "effet": effet, "rappel": rappel,
                    "mois_rappel": mois_rappel, "mois_rappeles": k})
    return res


def hausses_par_annee(augs: list[dict]) -> dict[int, float]:
    """La hausse du salaire de base de l'année (en %), selon le mois où chaque augmentation prend effet."""
    par = defaultdict(lambda: 1.0)
    for a in augs:
        par[int(a["effet"][:4])] *= 1 + a["pct"] / 100
    return {an: round(100 * (f - 1), 2) for an, f in sorted(par.items())}


# --- règles : primes en % du salaire de base, 13e mois ----------------------------------------------------------

def regles_pourcentage(bulletins: list[Bulletin]) -> list[dict]:
    """Les lignes qui valent chaque mois le même pourcentage du salaire de base (une prime de 3,5 %, un CET de
    3 %…), depuis quand, et les mois où elles manquent ou s'écartent."""
    ratios: Counter = Counter()
    libelles: dict[tuple, str] = {}
    premier: dict[tuple, str] = {}
    for b in bulletins:
        if b.base <= 0:
            continue
        for l in b.lignes:
            if l.nature in ("mensuelle", "cet"):
                cle = (l.nature, round(100 * l.montant / b.base, 1))
                ratios[cle] += 1
                libelles[cle] = l.libelle
                premier.setdefault(cle, b.mois)
    seuil = max(3, len(bulletins) // 4)
    regles = []
    for (nature, taux), n in ratios.most_common():
        if n < seuil or abs(taux) < 0.5:
            continue
        absents = []
        for b in bulletins:
            if b.mois < premier[(nature, taux)] or b.base <= 0:
                continue
            if not any(l.nature == nature and abs(100 * l.montant / b.base - taux) <= 0.06 for l in b.lignes):
                absents.append(b.mois)
        regles.append({"nature": nature, "taux": taux, "libelle": libelles[(nature, taux)], "depuis": premier[(nature, taux)],
                       "mois": n, "absents": absents})
    return sorted(regles, key=lambda r: (r["nature"], -abs(r["taux"])))


def treizieme(bulletins: list[Bulletin]) -> dict:
    """Le 13e mois de chaque année, sa répartition par mois, et s'il vaut bien un mois de salaire de base."""
    annees = defaultdict(dict)
    bases = {b.mois: b.base for b in bulletins}
    for b in bulletins:
        v = b.somme("treizieme")
        if v:
            annees[b.annee][int(b.mois[5:7])] = v
    lignes = []
    parts = defaultdict(list)
    for an, mois in sorted(annees.items()):
        total = round(sum(mois.values()), 2)
        dec = bases.get(f"{an}-12")
        complet = dec is not None and max(mois) == 12
        if complet:
            for m, v in mois.items():
                parts[m].append(v / dec)
        lignes.append({"annee": an, "par_mois": mois, "total": total, "base_decembre": dec, "complet": complet,
                       "conforme": None if not complet else abs(total - dec) < 1.0})
    calendrier = {m: round(statistics.median(v), 3) for m, v in sorted(parts.items())}
    return {"annees": lignes, "calendrier": calendrier}


# --- l'année et le calendrier -----------------------------------------------------------------------------------

def par_annee(bulletins: list[Bulletin]) -> list[dict]:
    res = []
    for an in sorted({b.annee for b in bulletins}):
        mois = [b for b in bulletins if b.annee == an]
        natures = {n: round(sum(b.somme(n) for b in mois), 2) for n in NATURES}
        res.append({
            "annee": an, "nb_mois": len(mois), "premier": mois[0].mois, "dernier": mois[-1].mois,
            "base_moyenne": round(statistics.mean(b.base for b in mois), 2),
            "natures": natures,
            "remuneration": round(sum(remuneration(b) for b in mois), 2),
            "frais": natures["frais"],
            "cet": round(-natures["cet"], 2),
            "cotisations": round(sum(b.cotisations for b in mois), 2),
            "impot": round(sum(b.impot for b in mois), 2),
            "net_avant_impot": round(sum(b.net_avant_impot for b in mois), 2),
            "net_paye": round(sum(b.net_paye for b in mois), 2),
        })
    return res


def calendrier(bulletins: list[Bulletin]) -> dict:
    """Le net payé de chaque mois, ce qui l'a gonflé, et les rendez-vous qui reviennent chaque année."""
    grille = defaultdict(dict)
    vus = defaultdict(lambda: defaultdict(list))         # nature → mois (1-12) → montants
    for b in bulletins:
        extras = [(n, b.somme(n)) for n in EXTRAS if b.somme(n) >= SEUIL_EXTRA]
        grille[b.annee][int(b.mois[5:7])] = {"mois": b.mois, "net_paye": b.net_paye, "extras": extras}
        for n, v in extras:
            vus[n][int(b.mois[5:7])].append(v)
    nb_annees = len(grille)
    habitudes = []
    for n, par_mois in vus.items():
        for m, montants in par_mois.items():
            if len(montants) >= 2 or nb_annees == 1:
                habitudes.append({"mois": m, "nature": n, "fois": len(montants), "min": min(montants),
                                  "max": max(montants), "dernier": montants[-1]})
    habitudes.sort(key=lambda h: (h["mois"], -h["dernier"]))
    mois_habitudes = {h["mois"] for h in habitudes}
    recents = bulletins[-12:]
    ordinaires = [b.net_paye for b in recents if not any(b.somme(n) >= SEUIL_EXTRA for n in EXTRAS)]
    return {"grille": {an: dict(sorted(v.items())) for an, v in sorted(grille.items())}, "habitudes": habitudes,
            "mois_creux": [m for m in range(1, 13) if m not in mois_habitudes],
            "net_ordinaire": round(statistics.median(ordinaires), 2) if ordinaires else None}


# --- impôts et cotisations ----------------------------------------------------------------------------------------

def _ratio_imposable(bulletins: list[Bulletin]) -> float:
    """Net imposable / (net avant impôt − frais), lu sur les derniers bulletins PDF : de quoi estimer le taux
    d'impôt des mois saisis dans l'Excel, qui n'ont pas le net imposable."""
    ratios = [b.net_imposable / (b.net_avant_impot - b.somme("frais")) for b in bulletins
              if b.net_imposable and b.net_avant_impot - b.somme("frais") > 0 and not b.somme(*EXTRAS[1:4])]
    return statistics.median(ratios[-12:]) if ratios else 1.0


def impots(bulletins: list[Bulletin]) -> dict:
    k = _ratio_imposable(bulletins)
    mois = []
    for b in bulletins:
        if b.taux_pas is not None:
            taux, lu = b.taux_pas, True
        else:
            assiette = k * (b.net_avant_impot - b.somme("frais"))
            taux, lu = (round(100 * b.impot / assiette, 1) if assiette > 0 else None), False
        mois.append({"mois": b.mois, "taux": taux, "lu": lu, "impot": b.impot, "neutre": b.taux_neutre,
                     "assiette": b.net_imposable or round(k * (b.net_avant_impot - b.somme("frais")), 2)})
    # Le taux non personnalisé suit le montant de chaque mois : des pics qui retombent le mois suivant
    dernier_pic = None
    for i in range(1, len(mois) - 1):
        t0, t, t1 = mois[i - 1]["taux"], mois[i]["taux"], mois[i + 1]["taux"]
        if None not in (t0, t, t1) and abs(t - t0) >= 1 and abs(t - t1) >= 1:
            dernier_pic = mois[i]["mois"]
    neutres = [m["mois"] for m in mois if m["neutre"]]
    fin_grille = max([x for x in (dernier_pic, neutres[-1] if neutres else None) if x], default=None)
    for m in mois:
        m["grille"] = bool(fin_grille and m["mois"] <= fin_grille)
    # Les changements de taux qui durent, après la période de la grille
    changements = []
    stables = [m for m in mois if not m["grille"] and m["taux"] is not None]
    for i in range(1, len(stables) - 1):
        avant, m, apres = stables[i - 1], stables[i], stables[i + 1]
        seuil = 0.25 if m["lu"] and avant["lu"] else 1.0
        if abs(m["taux"] - avant["taux"]) >= seuil and abs(apres["taux"] - m["taux"]) < seuil:
            changements.append({"mois": m["mois"], "avant": avant["taux"], "apres": m["taux"],
                                "par_mois": round((m["taux"] - avant["taux"]) / 100 * m["assiette"], 2)})
    if len(stables) >= 2 and not changements or (changements and changements[-1]["mois"] != stables[-1]["mois"]):
        avant, m = stables[-2], stables[-1]
        seuil = 0.25 if m["lu"] and avant["lu"] else 1.0
        if abs(m["taux"] - avant["taux"]) >= seuil:
            changements.append({"mois": m["mois"], "avant": avant["taux"], "apres": m["taux"],
                                "par_mois": round((m["taux"] - avant["taux"]) / 100 * m["assiette"], 2)})
    return {"mois": mois, "fin_grille": fin_grille, "changements": changements, "ratio_imposable": round(k, 4)}


def partage(annee: dict) -> dict:
    """Sur 100 € de rémunération : cotisations, impôt, ce qui te reste (net payé hors frais), CET."""
    r = annee["remuneration"]
    if r <= 0:
        return {}
    net = annee["net_paye"] - annee["frais"]
    return {"cotisations": round(100 * annee["cotisations"] / r, 1), "impot": round(100 * annee["impot"] / r, 1),
            "cet": round(100 * annee["cet"] / r, 1), "net": round(100 * net / r, 1)}


# --- pouvoir d'achat ----------------------------------------------------------------------------------------------

def pouvoir_achat(bulletins: list[Bulletin], ipc: dict[str, float], augs: list[dict]) -> dict | None:
    if not ipc or not bulletins:
        return None
    premier, dernier = bulletins[0], bulletins[-1]
    i0, i1 = indice_au(ipc, premier.mois), indice_au(ipc, dernier.mois)
    if not i0 or not i1:
        return None
    serie = [{"mois": b.mois, "base": b.base, "suivie": round(premier.base * (indice_au(ipc, b.mois) or i0) / i0, 2)}
             for b in bulletins]
    hausses = hausses_par_annee(augs)
    annees = []
    for an in sorted({b.annee for b in bulletins}):
        dec_avant, dec = f"{an - 1}-12", f"{an}-12"
        p0, p1 = indice_au(ipc, dec_avant), indice_au(ipc, min(dec, max(ipc)))
        prix = round(100 * (p1 / p0 - 1), 2) if p0 and p1 else None
        h = hausses.get(an, 0.0)
        annees.append({"annee": an, "hausse_salaire": h, "hausse_prix": prix,
                       "prix_jusqua": min(dec, max(ipc)),
                       "reel": round(100 * ((1 + h / 100) / (1 + prix / 100) - 1), 2) if prix is not None else None})
    nominal = 100 * (dernier.base / premier.base - 1)
    prix = 100 * (i1 / i0 - 1)
    return {"depuis": premier.mois, "jusqua": dernier.mois, "base_depart": premier.base, "base_actuelle": dernier.base,
            "nominal": round(nominal, 2), "prix": round(prix, 2),
            "reel": round(100 * ((1 + nominal / 100) / (1 + prix / 100) - 1), 2),
            "base_qui_suit": round(premier.base * i1 / i0, 2), "serie": serie, "annees": annees,
            "prix_connus_jusqua": max(ipc)}


# --- CET --------------------------------------------------------------------------------------------------------

def cet(bulletins: list[Bulletin]) -> dict:
    versements = [(b.mois, round(-b.somme("cet"), 2)) for b in bulletins if b.somme("cet")]
    par_an = defaultdict(float)
    for m, v in versements:
        par_an[int(m[:4])] += v
    return {"total": round(sum(v for _, v in versements), 2), "depuis": versements[0][0] if versements else None,
            "par_annee": {an: round(v, 2) for an, v in sorted(par_an.items())},
            "dernier_mensuel": versements[-1][1] if versements else 0.0}
