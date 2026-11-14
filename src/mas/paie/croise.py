"""La page qui croise tes bulletins et ton budget : ce que ton salaire laisse après tes dépenses, mois ordinaires
contre mois de prime, le salaire annoncé contre le salaire reçu, l'évolution d'une année sur l'autre, et les douze
mois qui viennent.

Entrées : les données du rapport de budget (rapport.json) et celles des bulletins (« mas-paie/1 », paie/export.py).
Calcul local, sans IA.
"""
from __future__ import annotations

import html
import statistics
from datetime import date

from ..navigation import CSS as CSS_MENU
from .format import eur, mois_lisible, nombre, pct, signe_eur, signe_pct
from .page import CSS, _insecables, _section, _tableau
from .rapprochement import phrase_extras, rapprocher

SEUIL_PRIME = 50.0
e = lambda t: html.escape(str(t), quote=False)


def _mois_suivant(aaaa_mm: str, n: int = 1) -> str:
    t = int(aaaa_mm[:4]) * 12 + int(aaaa_mm[5:7]) - 1 + n
    return f"{t // 12}-{t % 12 + 1:02d}"


def croiser(budget: dict, paie: dict) -> dict | None:
    """Les chiffres de la page. None si budget et bulletins n'ont aucun mois en commun."""
    pm = budget.get("par_mois") or {}
    partiels = set(pm.get("partiels") or [])
    depenses = {m: t for m, t in zip(pm.get("mois") or [], pm.get("totaux") or []) if m not in partiels}
    bulletins = {b["mois"]: b for b in paie["bulletins"]}
    communs = sorted(set(depenses) & set(bulletins))
    if not communs:
        return None
    mois = []
    for m in communs:
        b = bulletins[m]
        primes = {n: v for n, v in (b.get("natures") or {}).items() if v >= SEUIL_PRIME}
        mois.append({"mois": m, "salaire": b["net_paye"], "depenses": round(depenses[m], 2),
                     "reste": round(b["net_paye"] - depenses[m], 2), "primes": primes, "cet": b.get("cet", 0.0)})
    ordinaires = [x for x in mois if not x["primes"]]
    avec_primes = [x for x in mois if x["primes"]]
    moy = lambda xs, k: statistics.mean(x[k] for x in xs) if xs else None
    salaire, depense = sum(x["salaire"] for x in mois), sum(x["depenses"] for x in mois)
    # D'une année sur l'autre : les années couvertes au moins six mois des deux côtés
    annees = []
    for an in sorted({x["mois"][:4] for x in mois}):
        xs = [x for x in mois if x["mois"][:4] == an]
        if len(xs) >= 6:
            annees.append({"annee": int(an), "nb_mois": len(xs), "salaire": moy(xs, "salaire"), "depenses": moy(xs, "depenses")})
    # L'évolution se mesure sur les mêmes mois des deux années : les primes ne tombent pas toutes les mêmes mois
    par_mois = {x["mois"]: x for x in mois}
    for prec, a in zip(annees, annees[1:]):
        memes = [m for m in range(1, 13) if f"{prec['annee']}-{m:02d}" in par_mois and f"{a['annee']}-{m:02d}" in par_mois]
        if len(memes) < 3:
            continue
        somme = lambda an, k: sum(par_mois[f"{an}-{m:02d}"][k] for m in memes)
        a["hausse_salaire"] = round(100 * (somme(a["annee"], "salaire") / somme(prec["annee"], "salaire") - 1), 1)
        a["hausse_depenses"] = round(100 * (somme(a["annee"], "depenses") / somme(prec["annee"], "depenses") - 1), 1)
        a["memes_mois"] = (memes[0], memes[-1], len(memes))
    prix = {a["annee"]: a["hausse_prix"] for a in ((paie.get("pouvoir_achat") or {}).get("annees") or [])}
    for a in annees:
        a["hausse_prix"] = prix.get(a["annee"])
    # Les douze mois qui viennent : le salaire prévu, contre le budget d'aujourd'hui (ou la moyenne des douze
    # derniers mois de dépenses)
    fin = communs[-1] if not depenses else max(depenses)
    aujourdhui = budget.get("aujourdhui") or {}
    if aujourdhui.get("depenses"):
        budget_mensuel, source_budget = aujourdhui["depenses"], "ton budget d'aujourd'hui"
    else:
        recents = [depenses[m] for m in sorted(depenses)[-12:]]
        budget_mensuel, source_budget = statistics.mean(recents), f"la moyenne de tes {len(recents)} derniers mois de dépenses"
    venir, cumul = [], 0.0
    for p in paie.get("prevision") or []:
        if p["mois"] <= fin or len(venir) >= 12:
            continue
        reste = p["net_paye"] - budget_mensuel
        cumul += reste
        venir.append({"mois": p["mois"], "salaire": p["net_paye"], "reste": round(reste, 2), "cumul": round(cumul, 2),
                      "extras": {n: v for n, v in (p.get("extras") or {}).items() if v >= SEUIL_PRIME}})
    debut_budget = (budget.get("periode") or {}).get("debut") or communs[0]
    rapprochement = rapprocher(paie, budget.get("operations") or [], debut_budget, fin) if budget.get("operations") else None
    impot = [c for c in paie.get("changements_impot") or [] if c["mois"] >= _mois_suivant(fin, -12)]
    return {
        "mois": mois, "debut": communs[0], "fin": communs[-1], "salaire": salaire, "depenses": depense,
        "taux_epargne": round(100 * (salaire - depense) / salaire, 1) if salaire else None,
        "ordinaires": {"n": len(ordinaires), "salaire": moy(ordinaires, "salaire"), "depenses": moy(ordinaires, "depenses"),
                       "reste": moy(ordinaires, "reste")},
        "primes": {"n": len(avec_primes), "salaire": moy(avec_primes, "salaire"), "depenses": moy(avec_primes, "depenses"),
                   "reste": moy(avec_primes, "reste")},
        "manque_ordinaire": round(-sum(x["reste"] for x in ordinaires if x["reste"] < 0), 2),
        "surplus_primes": round(sum(x["reste"] for x in avec_primes if x["reste"] > 0), 2),
        "cet": round(sum(x["cet"] for x in mois), 2),
        "annees": annees, "venir": venir, "budget_mensuel": round(budget_mensuel, 2), "source_budget": source_budget,
        "net_ordinaire": paie.get("net_ordinaire"), "rapprochement": rapprochement, "impot": impot,
    }


def _barres(mois: list[dict], largeur: int = 720, hauteur: int = 250) -> str:
    """Ce qui reste du salaire après les dépenses, mois par mois : au-dessus de zéro, de côté ; en dessous, un manque."""
    if not mois:
        return ""
    haut = max(max(x["reste"] for x in mois), 0) or 1
    bas = min(min(x["reste"] for x in mois), 0)
    g, d, h_, b = 56, 12, 12, 28
    zone = hauteur - h_ - b
    y = lambda v: h_ + zone * (haut - v) / ((haut - bas) or 1)
    pas = (largeur - g - d) / len(mois)
    barre = max(3, pas * 0.68)
    morceaux = [f'<svg class="courbes" viewBox="0 0 {largeur} {hauteur}" role="img" aria-label="Ce qui reste de ton salaire '
                "après tes dépenses, mois par mois\">"]
    for v in (haut, 0, bas) if bas < 0 else (haut, 0):
        morceaux.append(f'<line class="grille" x1="{g}" x2="{largeur - d}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>'
                        f'<text class="axe" x="{g - 8}" y="{y(v) + 4:.1f}" text-anchor="end">{nombre(v, 0)}</text>')
    for i, x in enumerate(mois):
        cx = g + i * pas + (pas - barre) / 2
        y0, y1 = sorted((y(0), y(x["reste"])))
        classe = "positif" if x["reste"] >= 0 else "negatif"
        primes = ", ".join(f"{n} {eur(v, 0)}" for n, v in x["primes"].items())
        titre = (f"{mois_lisible(x['mois'])} : salaire {eur(x['salaire'], 0)}, dépenses {eur(x['depenses'], 0)}, "
                 f"reste {signe_eur(x['reste'])}" + (f" (primes : {primes})" if primes else ""))
        morceaux.append(f'<rect class="barre-reste {classe}{" prime" if x["primes"] else ""}" x="{cx:.1f}" y="{y0:.1f}" '
                        f'width="{barre:.1f}" height="{max(1, y1 - y0):.1f}" rx="2"><title>{e(titre)}</title></rect>')
        if x["mois"].endswith("-01") or i == 0:
            morceaux.append(f'<text class="axe" x="{cx + barre / 2:.1f}" y="{hauteur - 8}" text-anchor="middle">'
                            f'{x["mois"][:4] if x["mois"].endswith("-01") else mois_lisible(x["mois"], court=True)}</text>')
    morceaux.append("</svg>")
    return ('<figure class="graphe">' + "".join(morceaux) + '<ul class="legende"><li><span class="pastille positif"></span>'
            "Mis de côté (salaire − dépenses)</li><li><span class=\"pastille negatif\"></span>Manque</li>"
            '<li><span class="pastille prime"></span>Mois avec une prime</li></ul></figure>')


def construire_page(c: dict, menu: str = "") -> str:
    o, p = c["ordinaires"], c["primes"]
    faits = [f"<li>De {mois_lisible(c['debut'])} à {mois_lisible(c['fin'])} : <strong>{eur(c['salaire'], 0)}</strong> de "
             f"salaire, <strong>{eur(c['depenses'], 0)}</strong> de dépenses"
             + (f", soit <strong>{pct(c['taux_epargne'])}</strong> du salaire mis de côté." if c["taux_epargne"] is not None and c["taux_epargne"] >= 0
                else f" : tes dépenses dépassent ton salaire de {pct(-c['taux_epargne'])}.") + "</li>"]
    if o["n"] and p["n"]:
        faits.append(f"<li>Un mois sans prime, {eur(o['salaire'], 0)} de salaire pour {eur(o['depenses'], 0)} de dépenses : "
                     f"<strong>{signe_eur(o['reste'])}</strong> en moyenne. Les mois de prime, <strong>{signe_eur(p['reste'])}</strong>.</li>")
    tete = (f'<header class="tete"><div><p class="sur">mas</p><h1>Ton salaire et ton budget</h1>'
            f'<p class="periode">Tes bulletins et tes relevés, sur les {len(c["mois"])} mois qu\'ils couvrent tous les deux.</p></div>'
            '<p class="confidentialite"><strong>Calculé sur ton PC,</strong> à partir des pages « Ton budget » et « Tes fiches '
            "de paie », toutes deux anonymisées.</p></header>"
            f'<ul class="faits">{"".join(faits)}</ul>')
    # mois ordinaires et mois de prime
    corps_mois = _barres(c["mois"])
    if o["n"] and p["n"]:
        lignes = [["Sans prime", str(o["n"]), eur(o["salaire"], 0), eur(o["depenses"], 0), signe_eur(o["reste"])],
                  ["Avec une prime", str(p["n"]), eur(p["salaire"], 0), eur(p["depenses"], 0), signe_eur(p["reste"])]]
        corps_mois += _tableau(["Mois", "Nombre", "Salaire moyen", "Dépenses moyennes", "Reste moyen"], lignes,
                               ["", "num", "num", "num", "num"])
        depense_plus = p["depenses"] - o["depenses"]
        couvre = c["surplus_primes"] / c["manque_ordinaire"] if c["manque_ordinaire"] else None
        phrases = [f"Les mois de prime, tu dépenses {eur(abs(depense_plus), 0)} {'de plus' if depense_plus >= 0 else 'de moins'} "
                   "qu'un mois ordinaire."]
        if couvre is not None:
            phrases.append(f"Les mois sans prime ont manqué de {eur(c['manque_ordinaire'], 0)} en tout ; les mois de prime ont "
                           f"laissé {eur(c['surplus_primes'], 0)} : " + ("les primes couvrent le manque." if couvre >= 1 else
                           f"les primes n'en couvrent que {nombre(100 * couvre, 0)} %."))
        corps_mois += "<ul class=\"points\">" + "".join(f"<li>{x}</li>" for x in phrases) + "</ul>"
    sections = [_section("t-mois", "Ce que ton salaire laisse, mois par mois", corps_mois,
                         "Ton net payé (bulletins) moins tes dépenses du mois (relevés).")]
    # salaire annoncé, salaire reçu
    r = c["rapprochement"]
    if r:
        recus = [m for m in r["mois"] if m["recu"] is not None]
        points = [f"<li><strong>{mois_lisible(m['mois']).capitalize()} :</strong> " + (
            f"le bulletin annonce {eur(m['net_paye'])}, aucun virement de ce montant (un autre compte, ou un relevé manque)."
            if m["recu"] is None else f"{eur(m['recu'])} reçus le {m['date'][8:10]}/{m['date'][5:7]} pour {eur(m['net_paye'])} annoncés.")
            + "</li>" for m in r["mois"] if m["recu"] is None or m["ecart"]]
        corps = (f"<p><strong>{len(recus)} mois sur {len(r['mois'])}</strong> : le virement reçu est le net qu'annonce ton bulletin"
                 + (", au centime." if recus and all(m["ecart"] == 0 for m in recus) else ".") + "</p>"
                 + ("<ul class=\"points\">" + "".join(points) + "</ul>" if points else ""))
        sections.append(_section("t-recu", "Le salaire annoncé, le salaire reçu", corps))
    # d'une année sur l'autre
    if len(c["annees"]) >= 2:
        lignes = [[str(a["annee"]) + ("" if a["nb_mois"] == 12 else f" ({a['nb_mois']} mois)"), eur(a["salaire"], 0),
                   signe_pct(a["hausse_salaire"]) if "hausse_salaire" in a else "–", eur(a["depenses"], 0),
                   signe_pct(a["hausse_depenses"]) if "hausse_depenses" in a else "–",
                   signe_pct(a["hausse_prix"]) if a.get("hausse_prix") is not None else "–"] for a in c["annees"]]
        dernier = c["annees"][-1]
        texte = ""
        if "hausse_salaire" in dernier:
            ecart = dernier["hausse_depenses"] - dernier["hausse_salaire"]
            de, a, n = dernier["memes_mois"]
            noms = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre")
            periode = f"de {noms[de - 1]} à {noms[a - 1]}" if n == a - de + 1 else f"sur les {n} mêmes mois"
            texte = (f"<p class=\"note\">Évolutions mesurées sur les mêmes mois des deux années ({periode}). En "
                     f"{dernier['annee']}, tes dépenses ont " + ("augmenté plus vite que ton salaire" if ecart > 0 else
                     "augmenté moins vite que ton salaire") + f" ({signe_pct(dernier['hausse_depenses'])} contre "
                     f"{signe_pct(dernier['hausse_salaire'])}).</p>")
        sections.append(_section("t-annees", "D'une année sur l'autre", _tableau(
            ["Année", "Salaire par mois", "Évolution", "Dépenses par mois", "Évolution", "Prix"], lignes,
            ["", "num", "num", "num", "num", "num"]) + texte))
    # les douze mois qui viennent
    if c["venir"]:
        lignes = [[mois_lisible(v["mois"]), eur(v["salaire"], 0), signe_eur(v["reste"]), signe_eur(v["cumul"]),
                   e(phrase_extras(v["extras"], eur))] for v in c["venir"]]
        final = c["venir"][-1]
        creux = [v for v in c["venir"] if v["reste"] < 0]
        intro = (f"Ton salaire prévu par tes bulletins, contre {c['source_budget']} ({eur(c['budget_mensuel'], 0)} par mois). "
                 f"Sur les {len(c['venir'])} mois, <strong>{signe_eur(final['cumul'])}</strong>"
                 + (f" ; {len(creux)} mois en manque, que les mois de prime rattrapent" if creux and final["cumul"] >= 0 else
                    f" ; {len(creux)} mois en manque" if creux else "") + ".")
        impot = "".join(f"<p class=\"note\">Depuis {mois_lisible(i['mois'])}, ton taux d'impôt est passé de {pct(i['avant'])} à "
                        f"{pct(i['apres'])} : {signe_eur(i['par_mois'])} d'impôt par mois, déjà compris dans ce salaire prévu.</p>"
                        for i in c["impot"][-1:])
        sections.append(_section("t-venir", "Les douze mois qui viennent", _tableau(
            ["Mois", "Salaire prévu", "Reste du mois", "Cumul", "Prime"], lignes, ["", "num", "num", "num", ""]) + impot, intro))
    if c["cet"]:
        sections.append(_section("t-cet", "L'épargne que tes relevés ne voient pas",
                                 f"<p>Sur ces {len(c['mois'])} mois, <strong>{eur(c['cet'], 0)}</strong> sont partis sur ton compte "
                                 "épargne temps, pris sur ton salaire avant le net. Ils s'ajoutent à ce que tes relevés montrent "
                                 "comme épargne.</p>"))
    pied = (f'<footer class="pied"><p>Fait le {date.today().strftime("%d/%m/%Y")} par mas, sur ton PC. Les dépenses sont celles '
            "de la page « Ton budget » (mois complets seulement), le salaire est le net payé de tes bulletins.</p></footer>")
    corps = _insecables(tete + "".join(sections) + pied)
    style = CSS + CSS_MENU + CSS_BARRES
    return ('<!doctype html>\n<html lang="fr">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f"<title>Ton salaire et ton budget · mas</title>\n<style>{style}</style>\n</head>\n<body>\n"
            f'<main class="feuille"><div class="ruban" aria-hidden="true"></div>{menu}{corps}</main>\n</body>\n</html>\n')


CSS_BARRES = """
.barre-reste.positif{fill:var(--plus)}.barre-reste.negatif{fill:var(--moins)}
.barre-reste.prime{stroke:var(--encre);stroke-width:1.5}
.barre-reste:hover{opacity:.8}
.pastille.positif{background:var(--plus)}.pastille.negatif{background:var(--moins)}
.pastille.prime{background:transparent;box-shadow:inset 0 0 0 1.5px var(--encre)}
"""
