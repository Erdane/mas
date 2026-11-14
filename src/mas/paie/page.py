"""La page du rapport : un seul fichier HTML, sans bibliothèque ni appel extérieur, clair et sombre.

Même famille visuelle que la page du budget (couleurs, polices, feuille), et un menu commun aux trois pages
(budget, bulletins, salaire et budget) : voir `navigation`.
"""
from __future__ import annotations

import html
import json
import re
from datetime import date

from ..navigation import CSS as CSS_MENU
from . import analyses as A
from .format import eur, mois_lisible, nombre, pct, signe_eur, signe_pct
from .natures import NATURES

e = lambda t: html.escape(str(t), quote=False)
COMPOSITION = [("base", "Salaire de base", "c1"), ("mensuelle", "Primes du mois", "c2"), ("treizieme", "13e mois", "c3"),
               ("variable", "Part variable", "c4"), ("interessement", "Intéressement", "c5"),
               ("exceptionnelle", "Primes exceptionnelles", "c6")]
NOM_EXTRA = {"treizieme": "13e mois", "variable": "part variable", "interessement": "intéressement",
             "exceptionnelle": "prime exceptionnelle", "rappel": "rappel d'augmentation"}


# --- petites briques ------------------------------------------------------------------------------------------

def _section(ident: str, titre: str, corps: str, intro: str = "") -> str:
    return (f'<section class="bloc" aria-labelledby="{ident}"><h2 id="{ident}">{e(titre)}</h2>'
            + (f'<p class="intro">{intro}</p>' if intro else "") + corps + "</section>")


def _tableau(entetes: list[str], lignes: list[list[str]], classes: list[str] | None = None, legende: str = "") -> str:
    classes = classes or [""] * len(entetes)
    th = "".join(f'<th scope="col" class="{c}">{e(t)}</th>' for t, c in zip(entetes, classes))
    tr = "".join("<tr>" + "".join(f'<td class="{c}">{v}</td>' for v, c in zip(l, classes)) + "</tr>" for l in lignes)
    cap = f"<caption>{e(legende)}</caption>" if legende else ""
    return f'<div class="tableau"><table>{cap}<thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>'


def _courbes(series: list[dict], hauteur: int = 260, largeur: int = 720, escalier: bool = False, unite: str = "€",
             bandes: list[tuple[str, str, str]] | None = None) -> str:
    """Courbes en SVG, un seul axe. series : [{nom, classe, points: [(mois, valeur)]}]. bandes : (début, fin, texte)."""
    tous = [v for s in series for _, v in s["points"] if v is not None]
    if not tous:
        return ""
    mois = sorted({m for s in series for m, _ in s["points"]})
    bas, haut = min(tous), max(tous)
    marge = (haut - bas) * 0.12 or 1
    bas, haut = bas - marge, haut + marge
    g, d, h_, b = 56, 16, 14, 30
    x = lambda m: g + (largeur - g - d) * (mois.index(m) / max(1, len(mois) - 1))
    y = lambda v: h_ + (hauteur - h_ - b) * (1 - (v - bas) / (haut - bas))
    morceaux = [f'<svg class="courbes" viewBox="0 0 {largeur} {hauteur}" role="img" aria-label="{e(", ".join(s["nom"] for s in series))}">']
    for debut, fin, texte in bandes or []:
        if debut in mois:
            x0, x1 = x(debut), x(fin if fin in mois else mois[-1])
            morceaux.append(f'<rect class="bande" x="{x0:.1f}" y="{h_}" width="{max(2, x1 - x0):.1f}" height="{hauteur - h_ - b}"><title>{e(texte)}</title></rect>'
                            f'<text class="bande-texte" x="{x0 + 6:.1f}" y="{h_ + 14}">{e(texte)}</text>')
    pas = (haut - bas) / 4
    for i in range(5):
        v = bas + i * pas
        morceaux.append(f'<line class="grille" x1="{g}" x2="{largeur - d}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>'
                        f'<text class="axe" x="{g - 8}" y="{y(v) + 4:.1f}" text-anchor="end">{nombre(v, 1 if unite == "%" else 0)}</text>')
    for m in mois:
        if m.endswith("-01"):
            morceaux.append(f'<text class="axe" x="{x(m):.1f}" y="{hauteur - 8}" text-anchor="middle">{m[:4]}</text>'
                            f'<line class="repere-an" x1="{x(m):.1f}" x2="{x(m):.1f}" y1="{h_}" y2="{hauteur - b}"/>')
    for s in series:
        pts = [(x(m), y(v)) for m, v in s["points"] if v is not None]
        if escalier:
            chemin = "M" + " ".join(f"{px:.1f},{py:.1f}" if i == 0 else f"H{px:.1f} V{py:.1f}" for i, (px, py) in enumerate(pts))
        else:
            chemin = "M" + " L".join(f"{px:.1f},{py:.1f}" for px, py in pts)
        morceaux.append(f'<path class="trait {s["classe"]}" d="{chemin}"/>')
        for (m, v), (px, py) in zip([p for p in s["points"] if p[1] is not None], pts):
            libelle = f"{s['nom']}, {mois_lisible(m)} : " + (pct(v) if unite == "%" else eur(v))
            morceaux.append(f'<circle class="point {s["classe"]}" cx="{px:.1f}" cy="{py:.1f}" r="7"><title>{e(libelle)}</title></circle>')
    morceaux.append("</svg>")
    legende = "".join(f'<li><span class="pastille {s["classe"]}"></span>{e(s["nom"])}</li>' for s in series)
    return f'<figure class="graphe">{"".join(morceaux)}<ul class="legende">{legende}</ul></figure>'


def _barre(parts: list[tuple[str, float, str, str]], total: float) -> str:
    """Une barre empilée : (classe, valeur, libellé, détail)."""
    segs = "".join(f'<span class="seg {c}" style="flex-grow:{max(v, 0):.2f}" title="{e(l)} : {e(d)}"></span>'
                   for c, v, l, d in parts if v > 0)
    return f'<div class="barre" role="img" aria-label="{e(" ; ".join(f"{l} {d}" for _, v, l, d in parts if v > 0))}">{segs}</div>'


# --- les sections -----------------------------------------------------------------------------------------------

def _tete(r: dict) -> str:
    d = r["donnees"]
    nb_pdf = sum(b.source == "pdf" for b in d.bulletins)
    nb_xl = len(d.bulletins) - nb_pdf
    douze = d.emploi[-12:]
    net12 = sum(b.net_paye for b in douze)
    ordinaire = r["calendrier"]["net_ordinaire"]
    pa = r["pouvoir_achat"]
    faits = [f"<li><strong>{eur(net12, 0)}</strong> touchés sur les 12 derniers mois, soit {eur(net12 / len(douze), 0)} par mois en moyenne"
             + (f" ; un mois sans prime, environ <strong>{eur(ordinaire, 0)}</strong>" if ordinaire else "") + ".</li>"]
    if pa:
        faits.append(f"<li>Salaire de base : <strong>{eur(pa['base_actuelle'], 0)}</strong>, {signe_pct(pa['nominal'])} depuis "
                     f"{mois_lisible(pa['depuis'])} pour {signe_pct(pa['prix'])} de prix : ton pouvoir d'achat a bougé de "
                     f"<strong>{signe_pct(pa['reel'])}</strong>.</li>")
    return (f'<header class="tete"><div><p class="sur">mas</p><h1>Tes fiches de paie</h1>'
            f'<p class="periode">De {mois_lisible(d.emploi[0].mois)} à {mois_lisible(d.emploi[-1].mois)} : '
            f'{len(d.bulletins)} bulletins, dont {nb_pdf} PDF de ton employeur et {nb_xl} de ton classeur.</p></div>'
            '<p class="confidentialite"><strong>Anonymisé, puis calculé sur ton PC.</strong> '
            + (f"{d.remplacements} données personnelles masquées dans tes bulletins avant leur lecture. " if d.remplacements else "")
            + "Rien n'est envoyé : seul l'indice des prix est téléchargé, le même pour tout le monde, à l'INSEE.</p></header>"
            f'<ul class="faits">{"".join(faits)}</ul>')


def _a_regarder(r: dict) -> str:
    d, points = r["donnees"], []
    for c in r["impots"]["changements"][-2:]:
        if abs(c["par_mois"]) >= 20:
            sens = "de plus" if c["par_mois"] > 0 else "de moins"
            points.append(f"<strong>Ton taux d'impôt est passé de {pct(c['avant'])} à {pct(c['apres'])} en "
                          f"{mois_lisible(c['mois'])}</strong> : environ {eur(abs(c['par_mois']), 0)} d'impôt {sens} chaque mois. "
                          "Le taux change après ta déclaration de revenus ; tu peux le vérifier ou le moduler sur impots.gouv.fr.")
    a_corriger = [x for x in d.differences if not x["petit"]] + [x for x in d.ecarts if not x["petit"] and x["source"] == "excel"]
    if a_corriger or d.formules:
        n = len(a_corriger)
        points.append(f"<strong>Ton classeur a {n} mois à corriger</strong>"
                      + (f" et {len(d.formules)} formule{'s' if len(d.formules) > 1 else ''} qui calcule{'nt' if len(d.formules) > 1 else ''} de travers" if d.formules else "")
                      + " : voir « Ton classeur ». Ses totaux en dépendent.")
    aujourd_hui = date.today()
    precedent = f"{aujourd_hui.year}-{aujourd_hui.month:02d}"
    manquants, m = [], A.mois_plus(d.bulletins[-1].mois, 1)
    while m < precedent:
        manquants.append(m)
        m = A.mois_plus(m, 1)
    if manquants:
        points.append(f"<strong>{', '.join(mois_lisible(x) for x in manquants).capitalize()}</strong> "
                      f"{'ne sont' if len(manquants) > 1 else 'n’est'} pas encore dans tes bulletins ni dans ton classeur : "
                      "la prévision les estime en attendant.")
    pa = r["pouvoir_achat"]
    if pa and pa["annees"] and pa["annees"][-1]["reel"] is not None and pa["annees"][-1]["reel"] < 0:
        a = pa["annees"][-1]
        points.append(f"<strong>En {a['annee']}, ton salaire de base a augmenté de {pct(a['hausse_salaire'])} pour "
                      f"{pct(a['hausse_prix'])} de prix</strong> (jusqu'à {mois_lisible(a['prix_jusqua'])}) : "
                      f"{signe_pct(a['reel'])} de pouvoir d'achat cette année. Un argument pour ton prochain entretien.")
    if not points:
        return ""
    return _section("t-regarder", "À regarder", "<ul class=\"points\">" + "".join(f"<li>{p}</li>" for p in points) + "</ul>")


def _pouvoir_achat(r: dict) -> str:
    pa = r["pouvoir_achat"]
    if not pa:
        return _section("t-pa", "Ton pouvoir d'achat", "<p>L'indice des prix n'a pas pu être téléchargé : cette partie "
                        "s'affichera au prochain rapport fait avec une connexion.</p>")
    ecart = pa["base_actuelle"] - pa["base_qui_suit"]
    intro = (f"Ton salaire de base de {mois_lisible(pa['depuis'])}, {eur(pa['base_depart'], 0)}, aurait dû passer à "
             f"<strong>{eur(pa['base_qui_suit'], 0)}</strong> pour suivre les prix jusqu'en {mois_lisible(pa['jusqua'])}. "
             f"Il est de <strong>{eur(pa['base_actuelle'], 0)}</strong> : "
             + (f"{eur(ecart, 0)} par mois au-dessus des prix." if ecart >= 0 else f"{eur(-ecart, 0)} par mois en dessous des prix."))
    courbes = _courbes([
        {"nom": "Ton salaire de base", "classe": "s1", "points": [(p["mois"], p["base"]) for p in pa["serie"]]},
        {"nom": f"Le salaire de {mois_lisible(pa['depuis'])}, s'il avait suivi les prix", "classe": "s2",
         "points": [(p["mois"], p["suivie"]) for p in pa["serie"]]},
    ], escalier=True)
    lignes = [[str(a["annee"]), signe_pct(a["hausse_salaire"]), signe_pct(a["hausse_prix"]) if a["hausse_prix"] is not None else "–",
               f'<strong class="{"plus" if (a["reel"] or 0) >= 0 else "moins"}">{signe_pct(a["reel"])}</strong>' if a["reel"] is not None else "–"]
              for a in pa["annees"]]
    table = _tableau(["Année", "Hausse du salaire de base", "Hausse des prix", "Pouvoir d'achat"], lignes,
                     ["", "num", "num", "num"],
                     "Hausses comptées au mois où elles prennent effet (une hausse versée en avril avec rappel compte pour janvier) ; "
                     "prix de décembre à décembre.")
    note = (f'<p class="note">Indice des prix à la consommation de l\'INSEE, ensemble des ménages, connu jusqu\'à '
            f'{mois_lisible(pa["prix_connus_jusqua"])}.</p>')
    return _section("t-pa", "Ton pouvoir d'achat", courbes + table + note, intro)


def _calendrier(r: dict) -> str:
    cal = r["calendrier"]
    grille = cal["grille"]
    valeurs = [c["net_paye"] for an in grille.values() for c in an.values()]
    bas, haut = min(valeurs), max(valeurs)
    entetes = "".join(f'<th scope="col">{m}</th>' for m in ("janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."))
    lignes = []
    for an, mois in grille.items():
        cellules = []
        for m in range(1, 13):
            c = mois.get(m)
            if not c:
                cellules.append('<td class="vide"></td>')
                continue
            t = (c["net_paye"] - bas) / ((haut - bas) or 1)
            extras = ", ".join(f"{NOM_EXTRA[n]} {eur(v, 0)}" for n, v in c["extras"])
            titre = f"{mois_lisible(c['mois'])} : {eur(c['net_paye'])} net" + (f" ({extras})" if extras else "")
            cellules.append(f'<td style="--t:{t:.2f}" class="{"fort" if t > .55 else ""}" title="{e(titre)}">'
                            f'{nombre(c["net_paye"] / 1000, 1)}{"<i>•</i>" if c["extras"] else ""}</td>')
        lignes.append(f'<tr><th scope="row">{an}</th>{"".join(cellules)}</tr>')
    carte = (f'<div class="tableau"><table class="carte"><thead><tr><td></td>{entetes}</tr></thead><tbody>{"".join(lignes)}'
             "</tbody></table></div><p class=\"note\">Net payé chaque mois, en milliers d'euros ; un point : une prime ou un "
             "rappel ce mois-là.</p>")
    par_mois = {}
    for h in cal["habitudes"]:
        par_mois.setdefault(h["mois"], []).append(h)
    noms = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre")
    rdv = []
    for m, hs in sorted(par_mois.items()):
        quoi = " ; ".join(
            f"{NOM_EXTRA[h['nature']]} " + (f"de {eur(h['min'], 0)} à {eur(h['max'], 0)}, {eur(h['dernier'], 0)} la dernière fois"
                                           if h["max"] - h["min"] > 50 else f"d'environ {eur(h['dernier'], 0)}")
            for h in hs)
        rdv.append(f"<li><strong>{noms[m - 1].capitalize()} :</strong> {quoi}.</li>")
    creux = cal["mois_creux"]
    if creux and cal["net_ordinaire"]:
        rdv.append(f"<li><strong>Les autres mois</strong> ({', '.join(noms[m - 1] for m in creux)}) : ton salaire seul, "
                   f"environ {eur(cal['net_ordinaire'], 0)} net. Ce sont eux qu'il faut regarder pour ton budget de tous les mois.</li>")
    composition = []
    for an in r["par_annee"]:
        total = sum(an["natures"][n] for n, *_ in COMPOSITION) + an["natures"]["rappel"]
        parts = []
        for n, lib, c in COMPOSITION:
            v = an["natures"][n] + (an["natures"]["rappel"] if n == "mensuelle" else 0)
            parts.append((c, v, lib, eur(v, 0)))
        variable = sum(an["natures"][n] for n in ("variable", "interessement", "exceptionnelle"))
        composition.append(f'<div class="ligne-barre"><span class="an">{an["annee"]}{"*" if an["nb_mois"] < 12 else ""}</span>'
                           f'{_barre(parts, total)}<span class="valeur">{eur(an["remuneration"], 0)}'
                           f'<small>{nombre(100 * variable / an["remuneration"], 0) if an["remuneration"] else 0} % variable</small></span></div>')
    legende = "".join(f'<li><span class="pastille {c}"></span>{lib}</li>' for _, lib, c in COMPOSITION)
    partiel = next((a for a in r["par_annee"] if a["nb_mois"] < 12), None)
    corps = (carte + "<h3>Les rendez-vous de chaque année</h3><ul class=\"points\">" + "".join(rdv) + "</ul>"
             + "<h3>Ce qui compose ta rémunération</h3>" + "".join(composition) + f'<ul class="legende">{legende}</ul>'
             + (f'<p class="note">* {partiel["annee"]} : {partiel["nb_mois"]} mois. Rémunération hors frais remboursés, CET compris ; '
                "les primes du mois comprennent les rappels.</p>" if partiel else ""))
    return _section("t-cal", "Ce que tu touches, mois par mois", corps,
                    "Ton salaire n'est pas le même tous les mois : les primes arrivent toujours aux mêmes moments.")


def _impots(r: dict) -> str:
    imp = r["impots"]
    lignes = []
    for an in r["par_annee"]:
        p = A.partage(an)
        if not p:
            continue
        parts = [("ci", p["net"], "Pour toi", pct(p["net"])), ("cc", p["cet"], "Épargne temps", pct(p["cet"])),
                 ("cb", p["impot"], "Impôt", pct(p["impot"])), ("ca", p["cotisations"], "Cotisations", pct(p["cotisations"]))]
        lignes.append(f'<div class="ligne-barre"><span class="an">{an["annee"]}</span>{_barre(parts, 100)}'
                      f'<span class="valeur">{nombre(p["net"], 0)} € pour toi</span></div>')
    legende = ('<ul class="legende"><li><span class="pastille ci"></span>Ce que tu touches (hors frais)</li>'
               '<li><span class="pastille cc"></span>Épargne temps (CET)</li><li><span class="pastille cb"></span>Impôt prélevé</li>'
               '<li><span class="pastille ca"></span>Cotisations</li></ul>')
    points = [(m["mois"], m["taux"]) for m in imp["mois"] if m["taux"] is not None]
    bandes = [(imp["mois"][0]["mois"], imp["fin_grille"], "taux non personnalisé")] if imp["fin_grille"] else []
    courbe = _courbes([{"nom": "Taux du prélèvement à la source", "classe": "s1", "points": points}], hauteur=220,
                      escalier=True, unite="%", bandes=bandes)
    textes = []
    if imp["fin_grille"]:
        textes.append(f"<li><strong>Jusqu'en {mois_lisible(imp['fin_grille'])}, ton employeur appliquait le taux non personnalisé</strong> "
                      "(la grille de l'administration, faute de taux personnel) : il monte les mois de prime, d'où les pics. "
                      "L'écart avec ton vrai impôt a été régularisé l'année suivante, lors de ta déclaration.</li>")
    for c in imp["changements"]:
        textes.append(f"<li><strong>{mois_lisible(c['mois']).capitalize()} :</strong> {pct(c['avant'])} → {pct(c['apres'])}, "
                      f"soit {signe_eur(c['par_mois'])} d'impôt par mois.</li>")
    estimes = [m for m in imp["mois"] if not m["lu"]]
    note = (f'<p class="note">Les taux de {mois_lisible(estimes[0]["mois"])} à {mois_lisible(estimes[-1]["mois"])} viennent de ton '
            "classeur, qui n'a pas le net imposable : ils sont estimés à partir des bulletins précédents.</p>" if estimes else "")
    return _section("t-imp", "Impôts et cotisations",
                    "<h3>Sur 100 € gagnés</h3>" + "".join(lignes) + legende + "<h3>Ton taux d'impôt</h3>" + courbe
                    + "<ul class=\"points\">" + "".join(textes) + "</ul>" + note,
                    "Entre ce que ton employeur te verse et ce qui arrive sur ton compte : les cotisations (retraite, santé, "
                    "chômage…), l'impôt prélevé à la source, et ce que tu mets de côté sur ton CET.")


def _annonce(r: dict) -> str:
    coche = '<span class="ok" aria-label="conforme">✓</span>'
    croix = '<span class="ko" aria-label="à vérifier">!</span>'
    attente = '<span class="att" aria-label="en attente">…</span>'
    statut = {"conforme": coche, "ecart": croix, "attente": attente}
    blocs = []
    # les augmentations
    lignes = []
    for a in r["augmentations"]:
        if a["rappel"]:
            rappel = f'{eur(a["rappel"])} en {mois_lisible(a["mois_rappel"])} = {a["mois_rappeles"]} × {eur(a["delta"])} {coche}'
        else:
            rappel = "–"
        lignes.append([mois_lisible(a["effet"]), mois_lisible(a["mois"]), f'{eur(a["avant"])} → {eur(a["apres"])}',
                       signe_pct(a["pct"], 2), rappel])
    blocs.append("<h3>Tes augmentations</h3>" + _tableau(
        ["Prend effet", "Versée à partir de", "Salaire de base", "Hausse", "Rappel des mois d'avant"], lignes,
        ["", "", "num", "num", ""],
        "Une hausse versée en avril mais qui vaut depuis janvier arrive avec un rappel : mas vérifie qu'il couvre bien chaque mois."))
    # les règles
    regles = []
    for g in r["regles"]:
        nom = g["libelle"]
        quoi = "mis sur ton CET" if g["nature"] == "cet" else "versé"
        etat = coche if not g["absents"] else croix + " manque en " + ", ".join(mois_lisible(m) for m in g["absents"])
        regles.append(f"<li><strong>« {e(nom)} » : {pct(abs(g['taux']))} du salaire de base</strong>, {quoi} chaque mois depuis "
                      f"{mois_lisible(g['depuis'])} {etat}</li>")
    t13 = r["treizieme"]
    for a in t13["annees"]:
        if a["complet"]:
            regles.append(f"<li><strong>13e mois {a['annee']} : {eur(a['total'])}</strong>, un mois de salaire de base de décembre "
                          f"({eur(a['base_decembre'])}) {coche if a['conforme'] else croix}</li>")
        else:
            regles.append(f"<li><strong>13e mois {a['annee']} :</strong> {eur(a['total'])} versés jusqu'ici, le reste attendu en "
                          "novembre et décembre " + attente + "</li>")
    if t13["calendrier"]:
        noms = {6: "juin", 11: "novembre", 12: "décembre"}
        regles.append("<li>Le 13e mois arrive en " + ", ".join(f"{noms.get(m, m)} ({nombre(100 * f, 0)} %)" for m, f in t13["calendrier"].items())
                      + ".</li>")
    blocs.append("<h3>Ce qui revient chaque mois et chaque année</h3><ul class=\"points\">" + "".join(regles) + "</ul>")
    # les annonces de config.yaml
    if r["annonces"]:
        lignes = [[statut[x["statut"]], e(x["annonce"]), e(x["constat"])] for x in r["annonces"]]
        blocs.append("<h3>Ce que ton employeur t'a annoncé</h3>" + _tableau(["", "Annonce", "Sur tes bulletins"], lignes, ["etat", "", ""]))
    else:
        blocs.append("<h3>Ce que ton employeur t'a annoncé</h3><p>Ajoute dans <code>config.yaml</code> (<code>paie.annonces</code>) "
                     "ce qu'on t'a annoncé (une augmentation, ta part variable, ton intéressement, ta rémunération annuelle) : mas le compare à tes "
                     "bulletins. Le modèle est dans <code>config.example.yaml</code>.</p>")
    return _section("t-annonce", "Ce qui est annoncé, ce qui est versé", "".join(blocs),
                    "Les règles de ta paie, retrouvées dans tes bulletins et vérifiées mois par mois.")


def _classeur(r: dict) -> str:
    d = r["donnees"]
    if not d.classeur:
        return ""
    gros = [x for x in d.differences if not x["petit"]]
    petits = [x for x in d.differences if x["petit"]]
    internes = [x for x in d.ecarts if x["source"] == "excel"]
    blocs = []
    if gros:
        blocs.append("<h3>Mal saisi, d'après le bulletin</h3><ul class=\"points\">" + "".join(
            f"<li><strong>{mois_lisible(x['mois']).capitalize()} :</strong> {e(' ; '.join(x['constats']))}.</li>" for x in gros) + "</ul>")
    if internes:
        blocs.append("<h3>Sans bulletin PDF pour comparer</h3><ul class=\"points\">" + "".join(
            f"<li><strong>{mois_lisible(x['mois']).capitalize()} :</strong> tes lignes ne retombent pas sur ton net "
            f"({signe_eur(x['ecart'], 2)}) : {e(x['piste'])}.</li>" for x in internes) + "</ul>")
    if d.formules:
        blocs.append("<h3>Les formules du classeur</h3><ul class=\"points\">" + "".join(
            f"<li><strong>{e(x['feuille'])}{' ' + e(x['cellule']) if x['cellule'] else ''} :</strong> {e(x['texte'])}.</li>"
            for x in d.formules) + "</ul>")
    if petits:
        blocs.append(f"<details><summary>{len(petits)} petits écarts, sans effet sur ton net</summary><ul class=\"points\">" + "".join(
            f"<li><strong>{mois_lisible(x['mois']).capitalize()} :</strong> {e(' ; '.join(x['constats']))}.</li>" for x in petits)
            + "</ul></details>")
    if not blocs:
        blocs.append("<p>Ton classeur et tes bulletins disent la même chose, mois par mois.</p>")
    commun = sum(1 for b in d.classeur if b.mois in {p.mois for p in d.pdfs})
    return _section("t-classeur", "Ton classeur", "".join(blocs),
                    f"Comparé aux bulletins de ton employeur sur les {commun} mois que les deux couvrent. Ton net, lui, est juste "
                    "partout : ce sont des lignes de détail, mais elles faussent les totaux bruts de ta Synthèse.")


def _prevision(r: dict) -> str:
    p = r["prevision"]
    if not p:
        return ""
    d = r["donnees"]
    an = d.emploi[-1].annee
    reel = sum(b.net_paye for b in d.emploi if b.annee == an)
    lignes = []
    for m in p["mois"]:
        extras = ", ".join(f"{NOM_EXTRA[n]} {eur(v, 0)}" for n, v in m["extras"])
        lignes.append(f'<tr data-mois="{m["mois"]}" data-net="{m["net_paye"]}" data-point="{m["par_point"]}">'
                      f'<td>{mois_lisible(m["mois"])}</td><td class="num">{eur(m["base"], 0)}</td>'
                      f'<td class="num net">{eur(m["net_paye"], 0)}</td><td>{e(extras)}</td></tr>')
    estime_an = sum(m["net_paye"] for m in p["mois"] if m["mois"][:4] == str(an))
    suivant = sum(m["net_paye"] for m in p["mois"] if m["mois"][:4] == str(an + 1))
    curseur = (f'<div class="curseur"><label for="hausse">Hausse d\'avril {an + 1} : <output id="hausse-valeur">'
               f'{nombre(p["hausse_avril"], 1)} %</output></label><input type="range" id="hausse" min="0" max="6" step="0.1" '
               f'value="{p["hausse_avril"]}" data-depart="{p["hausse_avril"]}"></div>')
    totaux = (f'<div class="totaux"><p><span>{an}</span><strong>{eur(reel + estime_an, 0)}</strong>'
              f'<small>{eur(reel, 0)} déjà touchés + {eur(estime_an, 0)} estimés</small></p>'
              f'<p><span>{an + 1}</span><strong id="total-suivant" data-depart="{suivant:.2f}">{eur(suivant, 0)}</strong>'
              f'<small>net payé estimé, soit <span id="mensuel-suivant">{eur(suivant / 12, 0)}</span> par mois</small></p></div>')
    table = (f'<div class="tableau"><table id="prevision"><thead><tr><th scope="col">Mois</th><th scope="col" class="num">Salaire de base</th>'
             f'<th scope="col" class="num">Net payé estimé</th><th scope="col">Ce qui s\'ajoute</th></tr></thead><tbody>{"".join(lignes)}'
             "</tbody></table></div>")
    hypotheses = (f"<p class=\"note\">Hypothèses : hausse de {pct(p['hausse_janvier'])} en janvier et de {pct(p['hausse_avril'])} en avril "
                  f"(les médianes de tes trois dernières années), versée avec trois mois de rappel ; primes de {pct(p['taux_mensuels'])} "
                  f"du salaire de base chaque mois, {pct(abs(p['taux_cet']))} sur ton CET ; primes annuelles égales à celles des "
                  f"douze derniers mois ; cotisations de {pct(p['cotisations']['salaire'])} sur le salaire et {pct(p['cotisations']['primes'])} "
                  f"sur les primes annuelles ; impôt au taux actuel de {pct(p['taux_impot'])}. Règle-les dans config.yaml (<code>paie.hausse_janvier</code>, <code>paie.hausse_avril</code>).</p>")
    script = """<script>
(function(){
  var c=document.getElementById('hausse'); if(!c) return;
  var fmt=function(x){return Math.round(x).toLocaleString('fr-FR')+'\\u00a0€'};
  var total=document.getElementById('total-suivant'), mensuel=document.getElementById('mensuel-suivant');
  var an=String(%d);
  c.addEventListener('input',function(){
    var dx=parseFloat(c.value)-parseFloat(c.dataset.depart), somme=0;
    document.getElementById('hausse-valeur').textContent=parseFloat(c.value).toLocaleString('fr-FR',{minimumFractionDigits:1})+'\\u00a0%%';
    document.querySelectorAll('#prevision tbody tr').forEach(function(tr){
      var net=parseFloat(tr.dataset.net)+dx*parseFloat(tr.dataset.point);
      tr.querySelector('.net').textContent=fmt(net);
      if(tr.dataset.mois.slice(0,4)===an) somme+=net;
    });
    total.textContent=fmt(somme); mensuel.textContent=fmt(somme/12);
  });
})();
</script>""" % (an + 1)
    return _section("t-prev", "Les mois qui viennent", totaux + curseur + table + hypotheses + script,
                    "Une estimation, d'après les habitudes de tes bulletins. Fais glisser la hausse d'avril pour voir ce qu'elle change.")


def _cet(r: dict) -> str:
    c = r["cet"]
    if not c["total"]:
        return ""
    par_an = ", ".join(f"{an} : {eur(v, 0)}" for an, v in c["par_annee"].items())
    return _section("t-cet", "Ton compte épargne temps",
                    f"<p><strong>{eur(c['total'], 0)}</strong> mis de côté sur ton CET depuis {mois_lisible(c['depuis'])} "
                    f"({par_an}), {eur(c['dernier_mensuel'])} par mois aujourd'hui. C'est de l'épargne, comptée en brut avant "
                    "cotisations : elle n'apparaît pas sur tes relevés.</p>")


def _pied(r: dict) -> str:
    d = r["donnees"]
    sources = []
    if d.classeur:
        sources.append(f"ton classeur ({len(d.classeur)} mois)")
    if d.pdfs:
        sources.append(f"{len(d.pdfs)} bulletins PDF")
    avant = (f" Avant {mois_lisible(d.emploi[0].mois)}, {len(d.avant)} bulletins de stage ne comptent pas dans les analyses."
             if d.avant else "")
    return (f'<footer class="pied"><p>Fait le {date.today().strftime("%d/%m/%Y")} par mas, sur ton PC, à partir de '
            f"{' et '.join(sources)}. Pour un mois présent des deux côtés, le bulletin PDF fait foi.{avant} "
            f"{e(r['source_ipc'])}.</p></footer>")


def _insecables(fragment: str) -> str:
    """Les espaces de la typographie française ne coupent pas une ligne : « mot », mot :, mot ;, 3,5 %."""
    morceaux = re.split(r"(<script.*?</script>|<[^>]+>)", fragment, flags=re.S)
    for i, m in enumerate(morceaux):
        if m and not m.startswith("<"):
            m = re.sub(r"« ", "«\u00a0", m)
            morceaux[i] = re.sub(r" ([»:;?!%])", "\u00a0\\1", m)
    return "".join(morceaux)


def construire_page(r: dict, menu: str = "") -> str:
    """La page des bulletins. `menu` : le menu commun aux pages du rapport (navigation.py)."""
    corps = (_tete(r) + _a_regarder(r) + _pouvoir_achat(r) + _calendrier(r) + _impots(r) + _annonce(r) + _classeur(r)
             + _prevision(r) + _cet(r) + _pied(r))
    corps = _insecables(corps)
    return ('<!doctype html>\n<html lang="fr">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f"<title>Tes fiches de paie · mas</title>\n<style>{CSS}{CSS_MENU}</style>\n</head>\n<body>\n"
            f'<main class="feuille"><div class="ruban" aria-hidden="true"></div>{menu}{corps}</main>\n</body>\n</html>\n')


CSS = """
:root{
  color-scheme:light;
  --plan:#e6eeec; --feuille:#fcfcfb; --encre:#12303a; --encre-2:#48646d; --encre-3:#566c74;
  --filet:#dbe3e1; --lagon:#0b6a70; --lagon-voile:rgba(11,106,112,.10);
  --s1:#2a78d6; --s2:#eb6834; --plus:#127a52; --moins:#c43c3c; --alerte-fond:#fff3dc;
  --c1:#2a78d6; --c2:#8fb8ef; --c3:#1baf7a; --c4:#eb6834; --c5:#d4a72c; --c6:#9b6bd6;
  --ca:#b9c7c4; --cb:#eb6834; --cc:#d4a72c; --ci:#2a78d6; --chaud:11,106,112;
  --police-ui:"Bahnschrift","DIN Alternate","DIN 2014","Barlow","Segoe UI",system-ui,sans-serif;
}
@media (prefers-color-scheme:dark){:root{
  color-scheme:dark;
  --plan:#0b1416; --feuille:#172123; --encre:#eef3f2; --encre-2:#b4c4c6; --encre-3:#8a9da1;
  --filet:#2a3638; --lagon:#63c7cc; --lagon-voile:rgba(99,199,204,.14);
  --s1:#3987e5; --s2:#d95926; --plus:#4cc38f; --moins:#e66767; --alerte-fond:#3a2a10;
  --c1:#3987e5; --c2:#6d9bd6; --c3:#199e70; --c4:#d95926; --c5:#c79a24; --c6:#8b5fc8;
  --ca:#46585b; --cb:#d95926; --cc:#c79a24; --ci:#3987e5; --chaud:99,199,204;
}
.carte tbody td.fort{color:#0b1416}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;padding:clamp(12px,3vw,40px) clamp(10px,3vw,32px);background:var(--plan);color:var(--encre);font:400 15px/1.5 var(--police-ui)}
.feuille{position:relative;max-width:1100px;margin:0 auto;background:var(--feuille);border:1px solid var(--filet);border-radius:4px;
  padding:clamp(20px,4.5vw,56px);overflow:hidden}
.ruban{position:absolute;inset:0 0 auto 0;height:8px;background:repeating-linear-gradient(90deg,#2a78d6 0 34px,#1baf7a 34px 40px,
  #d4a72c 40px 62px,#eb6834 62px 66px,#12303a 66px 70px)}
h1,h2,h3{font-family:var(--police-ui);font-stretch:87.5%;margin:0}
h1{font-size:40px;line-height:1.1;font-weight:650}
h2{font-size:28px;line-height:1.2;font-weight:600;margin-bottom:6px}
h3{font-size:18px;line-height:1.3;font-weight:600;margin:28px 0 10px}
p{margin:0}
strong{font-weight:650}
code{font-size:.92em;padding:1px 5px;border-radius:3px;background:var(--lagon-voile)}
:focus-visible{outline:2px solid var(--lagon);outline-offset:3px;border-radius:2px}
.tete{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:flex-start;gap:16px 32px;margin-top:8px}
.sur{font-size:14px;font-weight:600;color:var(--lagon);margin-bottom:4px}
.periode{margin-top:8px;font-size:17px;color:var(--encre-2);max-width:60ch}
.confidentialite{max-width:340px;padding:10px 14px;border-radius:4px;font-size:14px;line-height:1.4;color:var(--encre-2);border:1px solid var(--filet)}
.confidentialite strong{color:var(--encre)}
.faits{list-style:none;margin:28px 0 0;padding:0;display:grid;gap:8px;font-size:20px;color:var(--encre-2);max-width:62ch}
.faits strong{color:var(--encre)}
.bloc{margin-top:clamp(40px,7vw,72px)}
.intro{color:var(--encre-2);font-size:16px;max-width:70ch;margin-bottom:8px}
.note{margin-top:10px;font-size:13px;color:var(--encre-3);max-width:80ch}
.points{margin:8px 0 0;padding-left:20px;display:grid;gap:8px;max-width:80ch}
.points li::marker{color:var(--lagon)}
#t-regarder + .points, section[aria-labelledby="t-regarder"]{background:var(--alerte-fond);border-radius:4px;padding:18px 22px 20px}
section[aria-labelledby="t-regarder"] h2{font-size:22px}
.tableau{overflow-x:auto;margin-top:14px}
table{border-collapse:collapse;width:100%;font-size:14px;font-variant-numeric:tabular-nums}
caption{caption-side:bottom;text-align:left;font-size:13px;color:var(--encre-3);padding-top:8px}
th,td{padding:7px 10px;border-bottom:1px solid var(--filet);text-align:left;vertical-align:top}
th{font-weight:600;color:var(--encre-2);font-size:13px}
.num{text-align:right;white-space:nowrap}
.plus{color:var(--plus)}.moins{color:var(--moins)}
.ok{color:var(--plus);font-weight:700}.ko{color:var(--moins);font-weight:700}.att{color:var(--encre-3)}
td.etat{width:2em;text-align:center}
.graphe{margin:18px 0 0}
.courbes{width:100%;height:auto;display:block;overflow:visible}
.courbes .grille{stroke:var(--filet);stroke-width:1}
.courbes .repere-an{stroke:var(--filet);stroke-dasharray:2 4}
.courbes .axe{fill:var(--encre-3);font-size:12px}
.courbes .trait{fill:none;stroke-width:2.2;stroke-linejoin:round}
.courbes .trait.s1{stroke:var(--s1)}.courbes .trait.s2{stroke:var(--s2);stroke-dasharray:5 4}
.courbes .point{fill:transparent;stroke:none}
.courbes .point:hover{fill:currentColor;stroke:var(--feuille);stroke-width:2}
.courbes .point.s1{color:var(--s1)}.courbes .point.s2{color:var(--s2)}
.courbes .bande{fill:var(--lagon-voile)}
.courbes .bande-texte{fill:var(--encre-3);font-size:12px}
.legende{list-style:none;margin:12px 0 0;padding:0;display:flex;flex-wrap:wrap;gap:6px 22px;font-size:14px;color:var(--encre-2)}
.legende li{display:flex;align-items:center;gap:8px}
.pastille{display:inline-block;width:12px;height:12px;border-radius:2px;flex:none}
.pastille.s1{background:var(--s1)}.pastille.s2{background:repeating-linear-gradient(90deg,var(--s2) 0 5px,transparent 5px 8px)}
.pastille.c1,.seg.c1{background:var(--c1)}.pastille.c2,.seg.c2{background:var(--c2)}.pastille.c3,.seg.c3{background:var(--c3)}
.pastille.c4,.seg.c4{background:var(--c4)}.pastille.c5,.seg.c5{background:var(--c5)}.pastille.c6,.seg.c6{background:var(--c6)}
.pastille.ca,.seg.ca{background:var(--ca)}.pastille.cb,.seg.cb{background:var(--cb)}.pastille.cc,.seg.cc{background:var(--cc)}
.pastille.ci,.seg.ci{background:var(--ci)}
.ligne-barre{display:grid;grid-template-columns:3.5em 1fr minmax(7em,auto);align-items:center;gap:12px;margin-top:10px}
.ligne-barre .an{font-weight:600;color:var(--encre-2)}
.ligne-barre .valeur{text-align:right;font-variant-numeric:tabular-nums;display:flex;flex-direction:column;line-height:1.2}
.ligne-barre small{color:var(--encre-3);font-size:12px}
.barre{display:flex;gap:2px;height:22px}
.seg{display:block;flex-basis:0;min-width:2px;height:100%}
.seg:first-child{border-radius:4px 0 0 4px}.seg:last-child{border-radius:0 4px 4px 0}
.carte th,.carte td{text-align:center;padding:6px 4px;border:2px solid var(--feuille)}
.carte tbody td{background:rgba(var(--chaud),calc(.08 + var(--t,0)*.8));color:var(--encre);border-radius:4px;font-size:13px;min-width:3em}
.carte tbody td.fort{color:#fff}
.carte tbody td.vide{background:transparent}
.carte i{font-style:normal;margin-left:2px}
.carte tbody th{color:var(--encre-2)}
details{margin-top:16px}
summary{cursor:pointer;color:var(--encre-2)}
.totaux{display:flex;flex-wrap:wrap;gap:16px 48px;margin-top:16px}
.totaux p{display:flex;flex-direction:column}
.totaux span{color:var(--encre-2);font-size:15px}
.totaux strong{font-size:36px;font-weight:650;font-stretch:87.5%;line-height:1.1}
.totaux small{color:var(--encre-3);font-size:13px}
.curseur{margin-top:20px;display:flex;flex-wrap:wrap;align-items:center;gap:8px 16px}
.curseur input{width:min(320px,100%);accent-color:var(--lagon)}
.curseur output{font-weight:650}
.pied{margin-top:56px;padding-top:16px;border-top:1px solid var(--filet);font-size:13px;color:var(--encre-3);max-width:90ch}
@media (max-width:640px){
  h1{font-size:32px}.faits{font-size:17px}
  .ligne-barre{grid-template-columns:3em 1fr;}.ligne-barre .valeur{grid-column:2;text-align:left}
}
"""
