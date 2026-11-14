"""Les mois à venir, d'après les habitudes de tes bulletins : salaire de base et primes en pourcentage, 13e mois,
primes annuelles du même mois l'an dernier, hausses de janvier et d'avril, cotisations et taux d'impôt actuels.

C'est une estimation : les primes annuelles dépendent des résultats, et une hausse n'est connue qu'une fois annoncée.
"""
from __future__ import annotations

import statistics

from .analyses import augmentations, impots, mois_plus, regles_pourcentage, treizieme

VARIABLES = ("variable", "interessement", "exceptionnelle")


def _moindres_carres(points: list[tuple[float, float, float]]) -> tuple[float, float]:
    """cotisations ≈ a × salaire + b × primes annuelles (deux taux : les primes annuelles cotisent moins)."""
    sxx = sum(s * s for s, v, c in points); svv = sum(v * v for s, v, c in points); sxv = sum(s * v for s, v, c in points)
    sxc = sum(s * c for s, v, c in points); svc = sum(v * c for s, v, c in points)
    det = sxx * svv - sxv * sxv
    if abs(det) < 1e-9:
        a = sxc / sxx if sxx else 0.0
        return a, a
    return (sxc * svv - svc * sxv) / det, (svc * sxx - sxc * sxv) / det


def _hausses(bulletins) -> tuple[float, float]:
    """(hausse de janvier, hausse d'avril) habituelles, en % : les médianes de l'historique."""
    janvier, avril = [], []
    for a in augmentations(bulletins):
        if a["pct"] < 0.1:
            continue
        if a["mois_rappeles"]:
            avril.append(a["pct"])
        elif a["mois"].endswith("-01"):
            janvier.append(a["pct"])
    # les trois dernières années : les hausses d'il y a longtemps disent peu de la prochaine
    return (round(statistics.median(janvier[-3:]), 2) if janvier else 0.0,
            round(statistics.median(avril[-3:]), 2) if avril else 0.0)


def prevoir(bulletins, hausse_janvier: float | None = None, hausse_avril: float | None = None) -> dict | None:
    if len(bulletins) < 12:
        return None
    dernier = bulletins[-1]
    hj, ha = _hausses(bulletins)
    hj = hj if hausse_janvier is None else hausse_janvier
    ha = ha if hausse_avril is None else hausse_avril
    recents = bulletins[-6:]
    taux = [r for r in regles_pourcentage(bulletins) if not any(m >= recents[0].mois for m in r["absents"])]
    t_mens = sum(r["taux"] for r in taux if r["nature"] == "mensuelle") / 100
    t_cet = sum(r["taux"] for r in taux if r["nature"] == "cet") / 100
    fixes = statistics.median(b.somme("mensuelle") - t_mens * b.base for b in recents)
    calendrier_13 = treizieme(bulletins)["calendrier"]
    frais = statistics.mean(b.somme("frais") for b in bulletins[-12:])
    # les primes annuelles des douze derniers mois, au même mois : une prime exceptionnelle d'il y a trois ans
    # ne reviendra pas d'elle-même
    annuelles: dict[int, dict[str, float]] = {}
    for b in bulletins[-12:]:
        for n in VARIABLES:
            if b.somme(n) >= 50:
                annuelles.setdefault(int(b.mois[5:7]), {})[n] = b.somme(n)
    # les cotisations : deux taux appris sur les 24 derniers mois
    points = []
    for b in bulletins[-24:]:
        v = b.somme(*VARIABLES)
        points.append((b.brut - b.somme("frais") - v, v, b.cotisations))
    a_cot, b_cot = _moindres_carres(points)
    imp = impots(bulletins)
    taux_pas = next((m["taux"] for m in reversed(imp["mois"]) if m["taux"] is not None), 0.0)
    k = imp["ratio_imposable"]

    def simuler(hausse_avril: float) -> list[dict]:
        base, mois, res = dernier.base, dernier.mois, []
        fin = f"{dernier.annee + 1}-12"
        while mois < fin:
            mois = mois_plus(mois, 1)
            mo = int(mois[5:7])
            rappel = 0.0
            if mo == 1:
                base = round(base * (1 + hj / 100), 2)
            if mo == 4 and hausse_avril:
                nouvelle = round(base * (1 + hausse_avril / 100), 2)
                rappel = round(3 * (nouvelle - base), 2)        # janvier à mars, versés en avril
                base = nouvelle
            primes = round(base * t_mens + fixes + rappel * t_mens, 2)
            cet = round(base * t_cet + rappel * t_cet, 2)
            treize = round(calendrier_13.get(mo, 0.0) * base, 2)
            variables = annuelles.get(mo, {})
            v = round(sum(variables.values()), 2)
            salaire = base + primes + cet + treize + rappel
            cotisations = round(a_cot * salaire + b_cot * v, 2)
            net_avant = round(salaire + v + frais - cotisations, 2)
            impot = round(taux_pas / 100 * k * (net_avant - frais), 2)
            extras = [(n, x) for n, x in (("treizieme", treize), ("rappel", rappel), *variables.items()) if x >= 50]
            res.append({"mois": mois, "base": base, "net_avant_impot": net_avant, "impot": impot,
                        "net_paye": round(net_avant - impot, 2), "remuneration": round(salaire - cet + v, 2),
                        "extras": extras})
        return res

    mois = simuler(ha)
    plus_un = simuler(ha + 1)
    for m, p in zip(mois, plus_un):
        m["par_point"] = round(p["net_paye"] - m["net_paye"], 2)     # net en plus pour 1 point de hausse en avril
    return {"depuis": dernier.mois, "mois": mois, "hausse_janvier": hj, "hausse_avril": ha, "taux_impot": taux_pas,
            "taux_mensuels": round(100 * t_mens, 2), "taux_cet": round(100 * t_cet, 2), "fixes": round(fixes, 2),
            "frais_moyens": round(frais, 2), "cotisations": {"salaire": round(100 * a_cot, 2), "primes": round(100 * b_cot, 2)},
            "primes_annuelles": {m: v for m, v in sorted(annuelles.items())}, "treizieme": calendrier_13}
