"""Pistes d'économie sur les dépenses que tu choisis chaque mois (restaurants, shopping, vacances…).

Calcul local, sans IA : chaque poste est comparé à tes propres mois. L'objectif proposé est à mi-chemin
entre ta moyenne et le niveau de tes mois les plus sobres (le premier quartile : un mois sur quatre, tu
dépenses moins que ça), un niveau que tu as donc déjà tenu. La règle 50/30/20 (besoins, envies,
épargne, en part des revenus) sert de repère pour l'ensemble.
"""

from __future__ import annotations

# Postes variables sur lesquels tu as la main, et un conseil concret pour chacun
CONSEILS = {
    "restauration": ("Les repas et cafés pris dehors s'additionnent vite : fixe-toi un montant par semaine et "
                     "emporte ton déjeuner quelques jours."),
    "shopping": ("Tes mois les plus chers font la moyenne : pour un achat de plus de 100 €, attends une semaine "
                 "avant de te décider, et garde un montant fixe pour le reste."),
    "loisirs": ("Vacances et sorties : décide d'un budget pour l'année et mets-le de côté chaque mois, plutôt que "
                "de tout payer le mois du départ."),
    "transport": ("Carburant, billets, péages : réserve tes longs trajets à l'avance et regroupe les petits "
                  "déplacements."),
    "alimentation": ("Une liste de courses et moins de passages en magasin : les achats d'appoint coûtent plus "
                     "cher."),
    "retrait": ("L'argent liquide échappe au suivi : retire une somme fixe par semaine et garde trace de ce "
                "qu'elle paie."),
}
# Règle 50/30/20 : besoins, envies, épargne, en part des revenus
BESOINS = {"logement", "energie", "telecom", "assurance", "transport", "alimentation", "sante", "impots_taxes",
           "credit", "frais_bancaires"}
ENVIES = {"restauration", "abonnement", "shopping", "loisirs"}
REPERES = {"besoins": 0.50, "envies": 0.30, "epargne": 0.20}

MOIS_MIN = 4            # en dessous, pas assez de mois pour parler de « tes mois sobres »
ECONOMIE_MIN = 15.0     # € par mois : une piste plus petite ne vaut pas d'être citée
PISTES_MAX = 6


def quartile_bas(valeurs: list[float]) -> float:
    """Premier quartile (interpolation linéaire, comme numpy) : un mois sur quatre est en dessous."""
    v = sorted(valeurs)
    position = (len(v) - 1) * 0.25
    bas = int(position)
    haut = min(bas + 1, len(v) - 1)
    return v[bas] + (v[haut] - v[bas]) * (position - bas)


def _arrondi(x: float, pas: float = 5.0) -> float:
    return round(x / pas) * pas


def pistes_economie(par_mois: dict, revenus: float, par_categorie: dict[str, float],
                    optionnel: float = 0.0) -> dict | None:
    """`par_mois` : le tableau mois par mois du budget (mois, partiels, lignes) ; `revenus`, `par_categorie`
    et `optionnel` (abonnements optionnels) : moyennes mensuelles. None sans assez de mois complets."""
    partiels = set(par_mois.get("partiels") or [])
    mois = par_mois.get("mois") or []
    garder = [i for i, m in enumerate(mois) if m not in partiels]
    if len(garder) < MOIS_MIN:
        return None
    pistes = []
    for ligne in par_mois.get("lignes") or []:
        categorie = ligne["categorie"]
        moyenne = par_categorie.get(categorie, 0.0)
        if categorie not in CONSEILS or moyenne <= 0:
            continue
        serie = [(mois[i], max(0.0, ligne["montants"][i])) for i in garder]
        sobres = quartile_bas([x for _, x in serie])
        objectif = _arrondi((moyenne + sobres) / 2)
        economie = moyenne - objectif
        if economie < ECONOMIE_MIN:
            continue
        plus_chers = sorted(serie, key=lambda s: -s[1])[:2]
        pistes.append({
            "categorie": categorie,
            "moyenne": round(moyenne, 2),
            "sobres": round(sobres, 2),
            "objectif": objectif,
            "economie": round(economie, 2),
            "part_revenus": round(moyenne / revenus, 4) if revenus > 0 else None,
            "mois_au_dessus": sum(1 for _, x in serie if x > objectif),
            "plus_chers": [{"mois": m, "montant": round(x, 2)} for m, x in plus_chers],
            "serie": [{"mois": m, "montant": round(x, 2)} for m, x in serie],
            "conseil": CONSEILS[categorie],
        })
    pistes = sorted(pistes, key=lambda p: -p["economie"])[:PISTES_MAX]

    repartition = None
    if revenus > 0:
        groupes = {"besoins": 0.0, "envies": 0.0, "autres": 0.0}
        for categorie, montant in par_categorie.items():
            groupe = "besoins" if categorie in BESOINS else "envies" if categorie in ENVIES else "autres"
            groupes[groupe] += montant
        depenses = sum(groupes.values())
        repartition = {k: {"montant": round(v, 2), "part": round(v / revenus, 4)} for k, v in groupes.items()}
        repartition["epargne"] = {"montant": round(revenus - depenses, 2), "part": round((revenus - depenses) / revenus, 4)}

    total = sum(p["economie"] for p in pistes)
    return {
        "pistes": pistes,
        "total": round(total, 2),
        "abonnements_optionnels": round(optionnel, 2),
        "repartition": repartition,
        "reperes": REPERES,
    }


def pistes_markdown(pistes: dict | None, eur) -> list[str]:
    """La même chose pour le rapport texte (et pour l'IA qui rédige la synthèse)."""
    if not pistes or not (pistes["pistes"] or pistes["repartition"]):
        return []
    l = ["", "### Pistes d'économie sur les dépenses variables (calcul local)", "",
         "Chaque poste est comparé aux mois de la personne. Objectif : à mi-chemin entre sa moyenne et ses "
         "mois les plus sobres (premier quartile), un niveau déjà tenu."]
    if pistes["pistes"]:
        l += ["", "| Poste | Moyenne | Mois sobres | Objectif | Économie par mois | Mois les plus chers |",
              "|---|---:|---:|---:|---:|---|"]
        for p in pistes["pistes"]:
            chers = ", ".join(f"{c['mois']} ({eur(c['montant'])})" for c in p["plus_chers"])
            l.append(f"| {p['categorie']} | {eur(p['moyenne'])} | {eur(p['sobres'])} | {eur(p['objectif'])} | "
                     f"{eur(p['economie'])} | {chers} |")
        l += ["", f"Ensemble : {eur(pistes['total'])} par mois ({eur(pistes['total'] * 12)} par an)"
              + (f", plus {eur(pistes['abonnements_optionnels'])} d'abonnements optionnels résiliables."
                 if pistes["abonnements_optionnels"] else ".")]
    r = pistes["repartition"]
    if r:
        pc = lambda x: f"{x * 100:.0f} %"
        l += ["", f"Répartition des revenus (repère 50/30/20) : besoins {pc(r['besoins']['part'])} (repère 50 %), "
                  f"envies {pc(r['envies']['part'])} (repère 30 %), proches, espèces et divers {pc(r['autres']['part'])}, "
                  f"épargne {pc(r['epargne']['part'])} (repère 20 %)."]
    return l
