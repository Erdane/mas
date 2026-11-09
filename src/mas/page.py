"""Page HTML du rapport budgétaire.

Construite à partir des données de l'analyse (pas du Markdown) : barre des revenus, dépenses par
catégorie, dépenses récurrentes, synthèse. Un seul fichier, styles et script intégrés, aucune
ressource externe (l'ouvrir ne fait aucune requête réseau), thème clair/sombre, imprimable.

Deux versions de la même page :
- anonyme : les pseudonymes ([PERSONNE_1]…) apparaissent comme des « masques » ;
- personnelle : les vraies valeurs, remises en local, sont signalées comme telles.

Les données sont aussi écrites en JSON (avec les pseudonymes, jamais les vraies valeurs) pour
pouvoir régénérer les pages plus tard avec `mas exporter`.
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime
from pathlib import Path

from markdown_it import MarkdownIt

VERSION_DONNEES = 1

# HTML brut désactivé : le texte vient d'un LLM et les libellés d'un relevé bancaire
_MD = MarkdownIt("commonmark", {"html": False})
_JETON = re.compile(r"\[([A-Z]+_\d+)\]")

CATEGORIES = {
    "logement": "Logement", "energie": "Énergie", "telecom": "Télécom", "assurance": "Assurances",
    "transport": "Transport", "alimentation": "Alimentation", "restauration": "Restauration",
    "abonnement": "Abonnements", "sante": "Santé", "impots_taxes": "Impôts et taxes",
    "credit": "Crédits", "epargne": "Épargne", "shopping": "Shopping", "loisirs": "Loisirs",
    "frais_bancaires": "Frais bancaires", "retrait": "Retraits d'espèces",
    "virement_personnel": "Virements à des proches", "revenu": "Revenus", "autre": "Autres",
}
TYPES_JETON = {
    "PERSONNE": "Personne", "ADRESSE": "Adresse", "IBAN": "IBAN", "COMPTE": "Compte",
    "TELEPHONE": "Téléphone", "EMAIL": "E-mail", "REF": "Référence", "CARTE": "Carte",
    "NIR": "N° de sécu", "RIB": "RIB", "DONNEE": "Donnée", "LIEU": "Lieu",
}
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre",
        "octobre", "novembre", "décembre"]
MOIS_COURTS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.",
               "nov.", "déc."]
# (nature, couleur dans la barre des revenus, titre, explication)
NATURES = [
    ("obligatoire", "s1", "À payer quoi qu'il arrive",
     "Charges fixes : logement, énergie, crédits, impôts, assurances."),
    ("abonnement_optionnel", "s2", "Abonnements que tu peux arrêter",
     "Rien ne t'oblige à les garder : c'est là que se trouvent les économies les plus simples."),
    ("courant_variable", "s3", "Dépenses courantes qui reviennent",
     "Des dépenses régulières dont le montant varie : courses, carburant, sorties."),
]

ICONE_MASQUE = (
    '<svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" '
    'fill-rule="evenodd" d="M2 8.6C2 7.1 3.2 6.1 4.8 6.4c2.2.4 4.5 1.2 7.2 1.2s5-.8 7.2-1.2C20.8 6.1 '
    '22 7.1 22 8.6c0 4.2-2.3 8-5.6 8-2.1 0-3.2-1.9-4.4-1.9s-2.3 1.9-4.4 1.9C4.3 16.6 2 12.8 2 8.6Zm5.3 '
    '1.5c-1.2 0-2.1.6-2.1 1.4s1 1.2 2.1 1.1c1-.1 1.9-.6 1.9-1.3s-.9-1.2-1.9-1.2Zm9.4 0c-1 0-1.9.5-1.9 '
    '1.2s.9 1.2 1.9 1.3c1.1.1 2.1-.3 2.1-1.1s-.9-1.4-2.1-1.4Z"/></svg>'
)
ICONE_CADENAS = (
    '<svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" '
    'd="M12 2a5 5 0 0 0-5 5v3H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8a2 2 0 0 0-2-2h-1V7a5 '
    '5 0 0 0-5-5Zm-3 8V7a3 3 0 1 1 6 0v3H9Z"/></svg>'
)
ICONE_ALERTE = (
    '<svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" '
    'd="M12 2.5 1.5 21h21L12 2.5Zm-1 7h2v6h-2v-6Zm0 8h2v2h-2v-2Z"/></svg>'
)


# ---------------------------------------------------------------- données

def donnees_rapport(budget: dict, classements, synthese: str, alertes: int | list[str] = 0,
                    traitement: dict | None = None, genere_le: datetime | None = None,
                    lectures: list[dict] | None = None, operations: list | None = None,
                    livrets: list[dict] | None = None) -> dict:
    """Données de la page (sérialisables en JSON). Les libellés gardent leurs pseudonymes.
    `alertes` : nombre de pages en écart (extraction par l'IA) ou liste de messages de contrôle."""
    messages = [a for a in alertes if isinstance(a, str) and a.startswith("Relevé ")] if isinstance(alertes, list) else []
    nb_alertes = len(alertes) if isinstance(alertes, list) else alertes
    justifications = {c.cle: c.justification for c in classements}
    debut, _, fin = str(budget.get("periode", "?")).partition(" → ")
    recurrents = [
        {
            "nature": nature, "libelle": g.libelle, "categorie": g.categorie,
            "periodicite": g.periodicite, "occurrences": g.occurrences,
            "montant_mensuel": round(g.montant_mensuel, 2), "montant_moyen": round(g.montant_moyen, 2),
            "variable": g.montant_variable,
            "justification": justifications.get(g.cle, ""),
        }
        for nature, groupes in budget.get("par_nature", {}).items()
        for g in groupes
    ]
    return {
        "version": VERSION_DONNEES,
        "genere_le": (genere_le or datetime.now()).isoformat(timespec="minutes"),
        "periode": {"debut": debut, "fin": fin or debut, "nb_mois": budget.get("nb_mois", 0)},
        "revenus": round(budget.get("revenus_mensuels", 0.0), 2),
        "depenses": round(budget.get("depenses_mensuelles", 0.0), 2),
        "obligatoire": round(budget.get("total_obligatoire", 0.0), 2),
        "optionnel": round(budget.get("total_optionnel", 0.0), 2),
        "categories": [{"categorie": k, "montant": round(v, 2)}
                       for k, v in budget.get("par_categorie", {}).items()],
        "recurrents": recurrents,
        "transferts": {k: {"sortis": round(v["sortis"], 2), "rentres": round(v["rentres"], 2)}
                       for k, v in (budget.get("transferts") or {}).items()},
        "par_mois": budget.get("par_mois") or {},
        "proches": ({k: round(v, 2) for k, v in budget["proches"].items()} if budget.get("proches") else None),
        "proches_detail": budget.get("proches_detail") or [],    # par personne, libellés pseudonymisés
        "recus_proches_en_revenu": bool(budget.get("recus_proches_en_revenu")),
        "a_verifier": budget.get("a_verifier") or [],
        "loyers": budget.get("loyers") or [],
        "synthese": synthese,
        "alertes_extraction": nb_alertes,
        "controles": messages,
        "traitement": traitement,
        "lectures": lectures or [],       # comment chaque relevé a été lu (voir Orchestrateur.lectures)
        "livrets": livrets or [],         # bilan de chaque livret (voir orchestrateur.bilan_livrets)
        # Chaque opération classée, libellé pseudonymisé : pour la page de détail (catégorie, puis mois)
        "operations": [{"date": o["date"], "libelle": o["libelle"], "montant": round(o["montant"], 2),
                        "categorie": o.get("categorie", "autre")}
                       for o in sorted((o if isinstance(o, dict) else o.model_dump() for o in operations or []),
                                       key=lambda o: o["date"])],
    }


# ---------------------------------------------------------------- formats

def _eur(x: float, decimales: int = 2) -> str:
    texte = f"{abs(x):,.{decimales}f}".replace(",", " ").replace(".", ",")
    return ("−" if x < 0 else "") + texte + " €"


def _pct(part: float, total: float) -> str:
    return f"{round(100 * part / total)} %" if total else "—"


def _periode_lisible(periode: dict) -> str:
    def mois(aaaa_mm: str) -> tuple[str, str] | None:
        try:
            annee, m = aaaa_mm.split("-")
            return MOIS[int(m) - 1], annee
        except (ValueError, IndexError):
            return None

    debut, fin = mois(periode.get("debut", "")), mois(periode.get("fin", ""))
    if not debut or not fin:
        return "Période non déterminée"
    if debut == fin:
        texte = f"En {debut[0]} {debut[1]}"
    elif debut[1] == fin[1]:
        texte = f"De {debut[0]} à {fin[0]} {fin[1]}"
    else:
        texte = f"De {debut[0]} {debut[1]} à {fin[0]} {fin[1]}"
    n = periode.get("nb_mois", 0)
    if not n:
        return texte
    n_txt = str(int(n)) if float(n).is_integer() else f"{n:.1f}".replace(".", ",")
    return f"{texte}, {n_txt} mois de relevés"


def _duree(secondes: float) -> str:
    s = int(round(secondes))
    return f"{s} s" if s < 60 else f"{s // 60} min {s % 60:02d} s"


def _date_lisible(iso: str) -> str:
    try:
        d = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return ""
    return f"le {d.day} {MOIS[d.month - 1]} {d.year} à {d:%H:%M}"


def _jour(iso: str) -> str:
    """« 2026-05-12 » -> « 12 mai 2026 »."""
    try:
        d = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return iso
    return f"{d.day} {MOIS[d.month - 1]} {d.year}"


def _attr(texte: str) -> str:
    return html.escape(texte, quote=True)


def _typographie(fragment_html: str) -> str:
    """Espaces insécables à la française dans un texte libre : « 47,99 € », « 54 % », « 1 037 »,
    « optionnels : ». Appliqué à du HTML sans attributs contenant ces motifs."""
    fragment_html = re.sub(r"(\d) (?=€|%)", "\\1\u00a0", fragment_html)
    while re.search(r"(\d) (\d{3})(?!\d)", fragment_html):
        fragment_html = re.sub(r"(\d) (\d{3})(?!\d)", "\\1\u202f\\2", fragment_html)
    return re.sub(r" ([:;!?»])", "\u00a0\\1", fragment_html)


# ---------------------------------------------------------------- pseudonymes

def _jetons(fragment_html: str, valeurs: dict[str, str] | None) -> str:
    """Remplace les [JETON_n] d'un fragment déjà échappé : masque (version anonyme) ou vraie
    valeur signalée (version personnelle)."""

    def remplacer(m: re.Match) -> str:
        jeton = m.group(1)
        type_, _, numero = jeton.rpartition("_")
        lisible = f"{TYPES_JETON.get(type_, type_.capitalize())} {numero}"
        if valeurs is not None and jeton in valeurs:
            return (f'<mark class="demasque" title="Remis en clair sur ton ordinateur : l\'IA n\'a vu '
                    f'que le pseudonyme « {html.escape(lisible)} »">{html.escape(valeurs[jeton])}</mark>')
        return (f'<span class="masque" title="Pseudonyme : la vraie valeur n\'a jamais quitté ton '
                f'ordinateur">{ICONE_MASQUE}{html.escape(lisible)}</span>')

    return _JETON.sub(remplacer, fragment_html)


def _texte(texte: str, valeurs: dict[str, str] | None) -> str:
    return _jetons(html.escape(texte, quote=False), valeurs)


def _sans_jetons(texte: str, valeurs: dict[str, str] | None) -> str:
    """Pour les attributs (infobulles) : texte brut, pseudonymes lisibles ou vraies valeurs."""
    def remplacer(m: re.Match) -> str:
        jeton = m.group(1)
        if valeurs is not None and jeton in valeurs:
            return valeurs[jeton]
        type_, _, numero = jeton.rpartition("_")
        return f"{TYPES_JETON.get(type_, type_.capitalize())} {numero}"
    return _JETON.sub(remplacer, texte)


# ---------------------------------------------------------------- sections

def _entete(d: dict, personnelle: bool) -> str:
    if personnelle:
        badge = (f'<p class="confidentialite perso">{ICONE_CADENAS}<span><strong>Version personnelle.</strong> '
                 "Elle contient tes vrais noms : garde-la pour toi.</span></p>")
    else:
        badge = (f'<p class="confidentialite anonyme">{ICONE_MASQUE}<span><strong>Version anonyme.</strong> '
                 "C'est exactement ce qu'a vu l'IA.</span></p>")
    return (
        '<header class="tete">'
        '<div class="tete-titres"><h1>Analyse budgétaire</h1>'
        f'<p class="periode">{html.escape(_periode_lisible(d["periode"]))}</p></div>'
        f"{badge}</header>"
    )


def _alerte(d: dict) -> str:
    controles = d.get("controles") or []
    if controles:
        items = "".join(f"<li>{html.escape(c)}</li>" for c in controles)
        return (f'<div class="alerte" role="note">{ICONE_ALERTE}<div><strong>À vérifier :</strong> la lecture '
                "de certains relevés ne correspond pas aux totaux imprimés par ta banque. Ces chiffres "
                f"peuvent être faux.<ul>{items}</ul></div></div>")
    n = d.get("alertes_extraction", 0)
    if not n:
        return ""
    pages = "1 page contient" if n == 1 else f"{n} pages contiennent"
    return (f'<p class="alerte" role="note">{ICONE_ALERTE}<span><strong>À vérifier :</strong> {pages} '
            "des écarts entre les montants lus par l'IA et ceux du relevé. Contrôle ces chiffres "
            "avant de t'y fier.</span></p>")


TRANSFERTS = {
    "epargne": "vers ton épargne (livrets, LDD…)",
    "entre_tes_comptes": "entre tes comptes de deux relevés (débité sur l'un, crédité sur l'autre)",
    "tes_comptes": "vers tes autres comptes déclarés",
    "a_ton_nom": "vers des comptes à ton nom",
    "proches": "en virements avec des proches",
    "exceptionnel": "pour un achat exceptionnel et son financement (hors moyenne mensuelle)",
}


def _hors_depenses(d: dict) -> str:
    """Ce qui n'est pas compté comme dépense : l'argent qui change seulement de compte."""
    t = d.get("transferts") or {}
    lignes = [(cle, v) for cle, v in t.items() if v.get("sortis") or v.get("rentres")]
    if not lignes:
        return ""
    items = "".join(
        f"<li><strong>{_eur(v['sortis'], 0)}</strong> par mois {TRANSFERTS.get(cle, cle)}"
        + (f" <span class=\"retour\">({_eur(v['rentres'], 0)} en sens inverse)</span>" if v.get("rentres") else "")
        + "</li>"
        for cle, v in lignes
    )
    note = ""
    if "a_ton_nom" in t:
        note = ('<p class="hors-note">« À ton nom » : le bénéficiaire porte le nom déclaré dans ton '
                "config.yaml. Si ce n'est pas toi (homonyme, proche), mets "
                "<code>virements_a_ton_nom: depense</code> dans la section <code>analyse</code> pour les "
                "compter comme des dépenses.</p>")
    return ('<div class="hors-depenses"><p class="hors-titre">Pas compté dans tes dépenses : de l\'argent '
            f"qui change seulement de compte</p><ul>{items}</ul>{note}</div>")


def _segment(classe: str, part: float, valeur: str, libelle: str, detail: str) -> str:
    return (f'<span class="seg {classe}" style="flex-grow:{part:.4f}" tabindex="0" '
            f'data-valeur="{_attr(valeur)}" data-libelle="{_attr(libelle)}" data-detail="{_attr(detail)}">'
            "</span>")


def _recap(d: dict) -> str:
    revenus, depenses = d["revenus"], d["depenses"]
    oblig, opt = d["obligatoire"], d["optionnel"]
    courantes = max(0.0, depenses - oblig - opt)
    reste = revenus - depenses
    echelle = max(revenus, depenses) or 1.0

    def par_an(x: float) -> str:
        return f"{_pct(x, revenus)} des revenus, {_eur(12 * x, 0)} par an" if revenus else f"{_eur(12 * x, 0)} par an"

    segments = [
        _segment("s1", oblig / echelle, _eur(oblig), "Dépenses obligatoires", par_an(oblig)),
        _segment("s2", opt / echelle, _eur(opt), "Abonnements optionnels", par_an(opt)),
        _segment("s3", courantes / echelle, _eur(courantes), "Dépenses courantes", par_an(courantes)),
    ]
    if reste > 0:
        segments.append(_segment("piste", reste / echelle, _eur(reste), "Ce qu'il te reste",
                                 f"{_pct(reste, revenus)} des revenus, {_eur(12 * reste, 0)} par an"))
    repere = ""
    if revenus and reste < 0:
        repere = (f'<span class="repere" style="left:{100 * revenus / echelle:.2f}%">'
                  '<span>tes revenus</span></span>')

    if not revenus:
        droite = ('<p class="reste"><span class="reste-libelle">revenus</span>'
                  '<strong class="hero hero-neutre">non détectés</strong></p>')
    elif reste >= 0:
        droite = (f'<p class="reste"><span class="reste-libelle">il te reste</span>'
                  f'<strong class="hero">{_eur(reste, 0)}</strong></p>')
    else:
        droite = (f'<p class="reste deficit"><span class="reste-libelle">{ICONE_ALERTE} tu dépenses de plus</span>'
                  f'<strong class="hero">{_eur(-reste, 0)}</strong></p>')

    resume_barre = (f"Sur {_eur(revenus, 0)} de revenus mensuels : {_eur(oblig, 0)} de dépenses obligatoires, "
                    f"{_eur(opt, 0)} d'abonnements optionnels, {_eur(courantes, 0)} de dépenses courantes"
                    + (f", il reste {_eur(reste, 0)}." if reste > 0 else "."))
    legende = [
        ("s1", "Obligatoires", oblig), ("s2", "Abonnements optionnels", opt), ("s3", "Courantes", courantes),
    ]
    items = "".join(
        f'<li><span class="pastille {c}" aria-hidden="true"></span>{nom} <strong>{_eur(v, 0)}</strong>'
        f'<span class="part">{_pct(v, revenus)}</span></li>'
        for c, nom, v in legende
    )
    if reste > 0:
        items += (f'<li><span class="pastille piste" aria-hidden="true"></span>Reste <strong>{_eur(reste, 0)}</strong>'
                  f'<span class="part">{_pct(reste, revenus)}</span></li>')
    base = (f'<p class="base">Moyennes mensuelles, sur {_eur(revenus, 0)} de revenus par mois.</p>' if revenus
            else '<p class="base">Aucun revenu détecté dans ces relevés : la barre montre seulement les dépenses.</p>')
    return (
        '<section class="recap" aria-labelledby="t-recap">'
        '<h2 id="t-recap" class="visuellement-cache">Ton mois type</h2>'
        '<div class="recap-haut">'
        f'<p class="depense">Tu dépenses <strong>{_eur(depenses, 0)}</strong> par mois</p>{droite}</div>'
        f'<div class="barre" role="img" aria-label="{_attr(resume_barre)}">{"".join(segments)}{repere}</div>'
        f'<ul class="legende">{items}</ul>{base}{_hors_depenses(d)}</section>'
    )


def _notes_categories(d: dict, valeurs: dict[str, str] | None) -> str:
    """Ce qui a été déduit plutôt que lu dans les libellés : à vérifier par l'utilisateur."""
    notes = []
    for loyer in d.get("loyers") or []:
        notes.append(
            f"Logement comprend {_eur(loyer['montant_mensuel'], 0)} par mois versés à "
            f"{_texte('[' + loyer['beneficiaire'] + ']', valeurs)} : même montant {loyer['mois']} mois de suite, "
            "c'est sans doute un loyer. Si ce n'en est pas un : <code>analyse.loyers_sans_libelle: non</code>."
        )
    proches = d.get("proches")
    if proches and proches.get("rembourse", 0) >= 0.5:
        notes.append(
            f"Virements avec des proches : {_eur(proches['envoye'], 0)} envoyés et {_eur(proches['recu'], 0)} reçus "
            f"par mois, dont {_eur(proches['rembourse'], 0)} de remboursements. Ceux-ci ne comptent ni en dépense ni "
            f"en revenu : restent {_eur(proches['depense'], 0)} de dépense, et {_eur(proches['revenu'], 0)} reçus en plus "
            + ("de ce que tu as envoyé, comptés dans tes revenus." if d.get("recus_proches_en_revenu") else
               "de ce que tu as envoyé, montrés à part : ce n'est pas un revenu régulier.")
        )
    return "".join(f'<p class="note">{n}</p>' for n in notes)


def _lien(detail: str | None, nom_html: str, categorie: str, mois: str | None = None, classe: str = "vers-detail") -> str:
    """Lien vers la page de détail (catégorie, ou mois d'une catégorie) ; sans page de détail, le texte seul."""
    if not detail:
        return nom_html
    ancre = f"cat-{categorie}" + (f"-{mois}" if mois else "")
    return f'<a class="{classe}" href="{_attr(detail)}#{ancre}">{nom_html}</a>'


def _categories(d: dict, valeurs: dict[str, str] | None = None, page_detail: str | None = None) -> str:
    cats = [c for c in d["categories"] if c["montant"] > 0]
    if not cats:
        return ""
    total = sum(c["montant"] for c in cats)
    maxi = max(c["montant"] for c in cats)
    lignes, rangs = [], []
    for c in cats:
        nom = CATEGORIES.get(c["categorie"], c["categorie"].replace("_", " ").capitalize())
        m = c["montant"]
        detail = f"{_pct(m, total)} des dépenses, {_eur(12 * m, 0)} par an"
        lignes.append(
            f'<li class="ligne" tabindex="0" data-valeur="{_attr(_eur(m) + " par mois")}" '
            f'data-libelle="{_attr(nom)}" data-detail="{_attr(detail)}">'
            f'<span class="nom">{_lien(page_detail, html.escape(nom), c["categorie"])}</span>'
            f'<span class="piste-cat" aria-hidden="true"><span class="remplissage" style="width:{100 * m / maxi:.2f}%"></span></span>'
            f'<span class="montant">{_eur(m, 0)}</span></li>'
        )
        rangs.append(f"<tr><td>{_lien(page_detail, html.escape(nom), c['categorie'])}</td><td class=\"num\">{_eur(m)}</td>"
                     f"<td class=\"num\">{_eur(12 * m, 0)}</td><td class=\"num\">{_pct(m, total)}</td></tr>")
    return (
        '<section class="categories" aria-labelledby="t-cat">'
        '<h2 id="t-cat">Où va ton argent</h2>'
        '<p class="intro">Dépenses moyennes par mois, de la plus grosse à la plus petite.'
        + (" Touche une catégorie pour voir ses dépenses, mois par mois." if page_detail else "") + "</p>"
        f'<ol class="barres">{"".join(lignes)}</ol>'
        '<details><summary>Voir les montants exacts</summary><div class="tableau"><table>'
        '<thead><tr><th>Catégorie</th><th class="num">Par mois</th><th class="num">Par an</th>'
        f'<th class="num">Part</th></tr></thead><tbody>{"".join(rangs)}</tbody></table></div></details>'
        f"{_notes_categories(d, valeurs)}</section>"
    )


def _a_verifier(d: dict, valeurs: dict[str, str] | None) -> str:
    """Ce que mas n'a pas pu classer avec certitude : à confirmer, et comment le corriger."""
    lignes = d.get("a_verifier") or []
    if not lignes:
        return ""
    rangs = "".join(
        f'<tr><td>{_jour(v["date"])}</td><td class="poste">{_texte(v["libelle"], valeurs)}</td>'
        f'<td>{html.escape(CATEGORIES.get(v["categorie"], v["categorie"]) if v.get("categorie") else "mis à part")}</td>'
        f'<td class="num">{_eur(v["montant"])}</td><td class="pourquoi">{html.escape(v["raison"])}</td></tr>'
        for v in lignes
    )
    return (
        '<section class="a-verifier" aria-labelledby="t-ver">'
        '<h2 id="t-ver">À vérifier</h2>'
        '<p class="intro">Ces opérations pèsent dans ton budget, et mas n\'a pas pu les classer avec certitude. '
        "Ce que tu sais d'un commerçant se note dans la section <code>analyse</code> de ton config.yaml, "
        "sous <code>categories</code> (par exemple <code>GARAGE DUPONT: transport</code>), avec son nom tel que "
        "tu le vois dans ta version personnelle : il servira à chaque analyse.</p>"
        '<div class="tableau"><table><thead><tr><th>Date</th><th>Libellé</th><th>Classé en</th>'
        f'<th class="num">Montant</th><th>Pourquoi</th></tr></thead><tbody>{rangs}</tbody></table></div></section>'
    )


def _par_mois(d: dict, detail: str | None = None) -> str:
    """Tableau catégories × mois ; la couleur de chaque case suit son montant (une seule teinte)."""
    pm = d.get("par_mois") or {}
    mois, lignes = pm.get("mois") or [], pm.get("lignes") or []
    if len(mois) < 2 or not lignes:
        return ""
    partiels = set(pm.get("partiels") or [])
    maxi = max((x for l in lignes for x in l["montants"]), default=0) or 1.0
    moyennes = {c["categorie"]: c["montant"] for c in d.get("categories", [])}

    entetes, annee_prec = [], None
    for m in mois:
        annee, num = m.split("-")
        an = f'<span class="annee">{annee}</span>' if annee != annee_prec else ""
        incomplet = '<span class="incomplet">incomplet</span>' if m in partiels else ""
        entetes.append(f'<th scope="col" class="num">{MOIS_COURTS[int(num) - 1]}{an}{incomplet}</th>')
        annee_prec = annee

    def cellule(x: float, categorie: str, m: str, oblig: float = 0.0) -> str:
        if abs(x) < 0.5:
            return '<td class="num vide">—</td>'
        if x < 0:
            return (f'<td class="num" title="Plus de remboursements que de dépenses ce mois-là">'
                    f'{_lien(detail, _eur(x, 0), categorie, m, "")}</td>')
        part = round(8 + 47 * min(x / maxi, 1.0))
        texte = _lien(detail, _eur(x, 0), categorie, m, "")
        if oblig >= 0.5:
            # La part « à payer quoi qu'il arrive » dans sa couleur, le reste dans celle des autres dépenses,
            # chacune sur la largeur de son montant
            coupe = min(oblig / x, 1.0) * 100
            # un bleu toujours reconnaissable, même pour un petit montant (sinon il se confond avec le gris)
            fond = (f"linear-gradient(90deg, color-mix(in srgb, var(--s1) {max(part, 24)}%, transparent) {coupe:.0f}%, "
                    f"color-mix(in srgb, var(--cat) {part}%, transparent) {coupe:.0f}%)")
            reste = x - oblig
            titre = (f"{_eur(oblig, 0)} à payer quoi qu'il arrive" + (f", {_eur(reste, 0)} d'autres dépenses" if reste >= 0.5 else ""))
            return f'<td class="num oblig" title="{_attr(titre)}" style="background:{fond}">{texte}</td>'
        return f'<td class="num" style="background:color-mix(in srgb, var(--cat) {part}%, transparent)">{texte}</td>'

    corps = "".join(
        "<tr>"
        f'<th scope="row">{_lien(detail, html.escape(CATEGORIES.get(l["categorie"], l["categorie"].replace("_", " ").capitalize())), l["categorie"])}</th>'
        + "".join(cellule(x, l["categorie"], m, o) for x, m, o
                  in zip(l["montants"], mois, l.get("obligatoire") or [0.0] * len(mois)))
        + f'<td class="num moyenne">{_eur(moyennes.get(l["categorie"], 0.0), 0)}</td></tr>'
        for l in lignes
    )
    totaux = "".join(f'<td class="num">{_eur(x, 0)}</td>' for x in pm.get("totaux") or [])
    note = ('<p class="note">Mois incomplet : les relevés n\'en couvrent qu\'une partie, ses montants sont '
            "donc plus bas. La moyenne, elle, est calculée sur la durée réelle des relevés.</p>"
            if partiels else "")
    if any(o >= 0.5 for l in lignes for o in l.get("obligatoire") or []):
        note = ('<ul class="legende"><li><span class="pastille s1" aria-hidden="true"></span>À payer quoi qu\'il arrive '
                "(tes dépenses récurrentes obligatoires)</li>"
                '<li><span class="pastille cat" aria-hidden="true"></span>Tes autres dépenses</li></ul>'
                '<p class="note">Une case des deux couleurs mêle les deux : chaque couleur y occupe la part de son '
                "montant. Survole-la pour voir le détail.</p>") + note
    return (
        '<section class="par-mois" aria-labelledby="t-mois">'
        '<h2 id="t-mois">Mois par mois</h2>'
        '<p class="intro">Tes dépenses de chaque catégorie, mois après mois. Plus la case est colorée, '
        "plus la dépense est élevée." + (" Touche une case pour voir les opérations de ce mois." if detail else "")
        + "</p>"
        '<div class="chaleur"><table><thead><tr><th scope="col">Catégorie</th>'
        f'{"".join(entetes)}<th scope="col" class="num moyenne">Moyenne</th></tr></thead>'
        f"<tbody>{corps}</tbody>"
        f'<tfoot><tr><th scope="row">Total</th>{totaux}'
        f'<td class="num moyenne">{_eur(d.get("depenses", 0.0), 0)}</td></tr></tfoot></table></div>'
        f"{note}</section>"
    )


def _synthese(d: dict, valeurs: dict[str, str] | None) -> str:
    texte = (d.get("synthese") or "").strip()
    if not texte:
        corps = "<p>La synthèse n'a pas pu être rédigée pour cette analyse.</p>"
    else:
        corps = _MD.render(texte)
        # « **Constat budgétaire** » seul sur sa ligne : un intertitre, pas un paragraphe en gras
        corps = re.sub(r"<p><strong>([^<]+)</strong></p>", r'<p class="intertitre">\1</p>', corps)
        corps = _jetons(_typographie(corps), valeurs)
    note = ("Analyse sans IA : les catégories viennent de mots-clés et ce texte est calculé sur ton ordinateur."
            if (d.get("traitement") or {}).get("sans_ia") else
            "Texte rédigé par l'IA à partir des chiffres de cette page. Les montants, eux, "
            "sont calculés sur ton ordinateur.")
    return (
        '<section class="synthese" aria-labelledby="t-syn">'
        '<h2 id="t-syn">Ce que dit l\'analyse</h2>'
        f'<div class="prose">{corps}</div>'
        f'<p class="note">{html.escape(note, quote=False)}</p></section>'
    )


NATURES_PROCHES = {
    "recus": "Reçus seulement",
    "allers_retours": "Allers-retours : avances, remboursements",
    "regulier": "Régulier : presque tous les mois",
    "ponctuel": "Ponctuel : un ou deux virements",
    "occasionnel": "Occasionnel",
}


def _nom_proche(personne: str, valeurs: dict[str, str] | None) -> str:
    jeton = f"[{personne}]"
    return _texte(jeton if _JETON.fullmatch(jeton) else personne, valeurs)


def _proches(d: dict, valeurs: dict[str, str] | None) -> str:
    """Virements avec des proches, personne par personne : qui pèse dans le total, et chaque virement."""
    detail = d.get("proches_detail") or []
    if not detail:
        return ""
    n = d["periode"].get("nb_mois") or 1
    compte = d.get("proches") is not None       # sinon : montrés à part, hors dépenses
    rangs, listes = [], []
    for p in detail:
        nom = _nom_proche(p["personne"], valeurs)
        dans_depenses = (f'{_eur(p["depense"])}<span class="variable">{_eur(p["depense"] / n, 0)} par mois</span>'
                         if compte else "—")
        gros = (f'{_eur(p["plus_gros"]["montant"])}<span class="variable">le {_jour(p["plus_gros"]["date"])}</span>'
                if p.get("plus_gros") else "—")
        rangs.append(
            f'<tr><td class="poste">{nom}</td><td class="num">{p["virements"]}</td>'
            f'<td class="num">{_eur(p["envoye"])}</td><td class="num">{_eur(p["recu"])}</td>'
            f'<td class="num">{dans_depenses}</td><td class="num">{gros}</td>'
            f'<td>{html.escape(NATURES_PROCHES.get(p["nature"], p["nature"]))}</td></tr>'
        )
        operations = "".join(
            f'<tr><td>{_jour(o["date"])}</td><td class="poste">{_texte(o["libelle"], valeurs)}</td>'
            f'<td class="num">{_eur(o["montant"])}</td></tr>'
            for o in p["operations"]
        )
        listes.append(f'<h3>{nom}</h3><div class="tableau"><table><thead><tr><th>Date</th><th>Libellé</th>'
                      f'<th class="num">Montant</th></tr></thead><tbody>{operations}</tbody></table></div>')
    intro = (f"Sur toute la période ({_nb_mois(n)} mois), du plus gros poids dans tes dépenses au plus petit. "
             "« Compté en dépense » : ce qui reste une fois les remboursements déduits." if compte else
             f"Sur toute la période ({_nb_mois(n)} mois). Ils sont montrés à part : rien n'est compté en dépense.")
    return (
        '<section class="proches" aria-labelledby="t-pro">'
        '<h2 id="t-pro">Virements avec des proches, personne par personne</h2>'
        f'<p class="intro">{intro}</p>'
        '<div class="tableau"><table><thead><tr><th>Personne</th><th class="num">Virements</th>'
        '<th class="num">Envoyé</th><th class="num">Reçu</th><th class="num">Compté en dépense</th>'
        f'<th class="num">Plus gros virement</th><th>Type</th></tr></thead><tbody>{"".join(rangs)}</tbody></table></div>'
        '<p class="note">Un de ces virements va en fait vers un compte à toi ? Ajoute le nom tel qu\'il apparaît sur '
        "le relevé (ou le nom de la banque, l'IBAN) à <code>comptes_personnels</code>, dans la section "
        "<code>analyse</code> de ton config.yaml : au prochain <code>mas analyser</code>, il sera mis à part.</p>"
        f'<details><summary>Voir chaque virement</summary>{"".join(listes)}</details></section>'
    )


def _nb_mois(n: float) -> str:
    return str(int(n)) if float(n).is_integer() else f"{n:.1f}".replace(".", ",")


RYTHMES = {  # périodicité -> (en clair, paiements par an)
    "hebdomadaire": ("chaque semaine", 52), "mensuelle": ("chaque mois", 12),
    "bimestrielle": ("tous les deux mois", 6), "trimestrielle": ("chaque trimestre", 4),
    "semestrielle": ("deux fois par an", 2), "annuelle": ("une fois par an", 1),
}


def _rythme(r: dict) -> str:
    texte, _ = RYTHMES.get(r["periodicite"], (r["periodicite"], None))
    return f"{texte}, payé {r['occurrences']} fois" if r["periodicite"] != "mensuelle" else f"{texte}, {r['occurrences']} fois"


def _par_an(r: dict) -> float:
    """Ce qui est payé en un an : le paiement moyen autant de fois que dans une année (une assurance
    annuelle compte une fois, pas douze), sans l'arrondi du montant ramené au mois."""
    _, fois = RYTHMES.get(r["periodicite"], (None, None))
    return r["montant_moyen"] * fois if fois and r.get("montant_moyen") is not None else 12 * r["montant_mensuel"]


def _recurrents(d: dict, valeurs: dict[str, str] | None) -> str:
    groupes = []
    for nature, couleur, titre, explication in NATURES:
        lignes = [r for r in d["recurrents"] if r["nature"] == nature]
        if not lignes:
            continue
        mensuel = sum(r["montant_mensuel"] for r in lignes)
        variable = '<span class="variable">montant variable</span>'
        ramene = '<span class="variable">ramené au mois</span>'
        rangs = "".join(
            "<tr>"
            f'<td class="poste">{_texte(r["libelle"], valeurs)}</td>'
            f'<td>{html.escape(CATEGORIES.get(r["categorie"], r["categorie"]))}</td>'
            f'<td>{html.escape(_rythme(r))}</td>'
            f'<td class="num">{_eur(r["montant_mensuel"])}{variable if r.get("variable") else ""}'
            f'{ramene if r["periodicite"] != "mensuelle" else ""}</td>'
            f'<td class="num">{_eur(_par_an(r), 0)}</td>'
            f'<td class="pourquoi">{_texte(r.get("justification") or "", valeurs)}</td>'
            "</tr>"
            for r in lignes
        )
        groupes.append(
            f'<div class="groupe {nature}">'
            f'<div class="groupe-tete"><h3><span class="pastille {couleur}" aria-hidden="true"></span>{titre}</h3>'
            f'<p class="groupe-total"><strong>{_eur(mensuel, 0)}</strong> par mois, soit {_eur(12 * mensuel, 0)} par an</p></div>'
            f'<p class="groupe-explication">{explication}</p>'
            '<div class="tableau"><table><thead><tr><th>Poste</th><th>Catégorie</th><th>Rythme</th>'
            '<th class="num">Par mois</th><th class="num">Par an</th><th>Pourquoi ce classement</th></tr></thead>'
            f"<tbody>{rangs}</tbody></table></div></div>"
        )
    if not groupes:
        corps = ('<p class="vide">Aucune dépense récurrente repérée. Il faut au moins trois mois de relevés '
                 "pour qu'une dépense se répète assez.</p>")
    else:
        corps = "".join(groupes)
    return ('<section class="recurrents" aria-labelledby="t-rec">'
            '<h2 id="t-rec">Tes dépenses récurrentes</h2>'
            '<p class="intro">Les dépenses qui reviennent chaque mois ou chaque trimestre, classées selon '
            f"que tu peux t'en passer ou non.</p>{corps}</section>")


def _lectures(d: dict) -> str:
    """Comment chaque relevé a été lu : directement (contrôlé au centime) ou par l'IA, et pourquoi."""
    lectures = d.get("lectures") or []
    if not lectures:
        return ""
    rangs = []
    for l in lectures:
        periode = f'<span class="variable">{html.escape(l["periode"])}</span>' if l.get("periode") else ""
        etat = "juste" if l.get("ok") else "ecart" if l.get("ok") is False else "inconnu"
        rangs.append(f'<tr><td>{l["releve"]}{periode}</td><td class="num">{l["pages"]}</td>'
                     f'<td>{html.escape(l["lecture"])}</td><td class="{etat}">{html.escape(l["controle"])}</td></tr>')
    constat = ("Un relevé non reconnu n'est pas compté sans l'IA." if (d.get("traitement") or {}).get("sans_ia")
               else "Un relevé lu par l'IA n'est pas vérifiable au centime.")
    conseil = (f'<p class="intro">{html.escape(constat, quote=False)} Pour qu\'il soit lu '
               "directement : <code>mas structure</code>, puis « Ta banque n'est pas reconnue ? » dans le README.</p>"
               if any(not l.get("directe") for l in lectures) else "")
    return ('<section class="lectures" aria-labelledby="t-lec">'
            '<h2 id="t-lec">Comment tes relevés ont été lus</h2>'
            '<p class="intro">Lus directement, les relevés sont vérifiés au centime avec les soldes ou les totaux '
            f"imprimés par ta banque.</p>{conseil}"
            '<div class="tableau"><table><thead><tr><th>Relevé</th><th class="num">Pages</th><th>Lecture</th>'
            f"<th>Contrôle</th></tr></thead><tbody>{''.join(rangs)}</tbody></table></div></section>")


def _pied(d: dict) -> str:
    lignes = []
    quand = _date_lisible(d.get("genere_le", ""))
    lignes.append(f"<p>Généré sur ton ordinateur par Mas {quand}.</p>" if quand
                  else "<p>Généré sur ton ordinateur par Mas.</p>")
    t = d.get("traitement")
    if t and t.get("sans_ia"):
        lignes.append(
            f"<p>Analyse sans IA en {_duree(t.get('duree_analyse') or 0)}, aucune donnée envoyée. "
            f"Anonymisation sur ton ordinateur en {_duree(t.get('duree_anonymisation') or 0)}.</p>"
        )
    elif t:
        tokens = (t.get("tokens_entree") or 0) + (t.get("tokens_sortie") or 0)
        tokens_txt = f"{tokens:,}".replace(",", " ")
        cout = t.get("cout_usd")
        cout_txt = f", coût estimé {cout:.3f}".replace(".", ",") + " $" if cout is not None else ""
        appels = t.get("appels") or 0
        cache = t.get("reponses_cache") or 0
        cache_txt = f" ({cache} réponses reprises du cache, non facturées)" if cache else ""
        pluriel = "s" if appels > 1 else ""
        modele = html.escape(str(t.get("modele", "")))
        lignes.append(
            f"<p>Analyse en {_duree(t.get('duree_analyse') or 0)} par {modele} : "
            f"{appels} appel{pluriel} à l'IA{cache_txt}, {tokens_txt} tokens{cout_txt}. "
            f"Anonymisation sur ton ordinateur en {_duree(t.get('duree_anonymisation') or 0)}.</p>"
        )
    return f'<footer class="pied">{"".join(lignes)}</footer>'


# ---------------------------------------------------------------- page

def _signe(x: float, decimales: int = 0) -> str:
    return ("+" if x >= 0 else "−") + _eur(abs(x), decimales)


def _graduation(etendue: float) -> float:
    """Pas des lignes de repère : trois à six lignes."""
    for pas in (50, 100, 200, 250, 500, 1000, 2000, 2500, 5000, 10000, 20000, 25000, 50000):
        if etendue / pas <= 6:
            return pas
    return 100000


def _repere_euros(v: float, pas: float) -> str:
    signe = "+" if v > 0 else "−" if v < 0 else ""
    return f"{signe}{abs(v) / 1000:g} k€" if pas >= 1000 else f"{signe}{abs(v):g} €"


def _dessin_ecart(lignes: list[tuple], largeur: int, hauteur: int, marge: int, variante: str) -> str:
    """Barres de part et d'autre de zéro, une par mois, et la moyenne en pointillé."""
    droite, haut, bas = 10, 22, 40
    etroit = variante == "mobile"
    ecarts = [e for *_, e in lignes]
    haut_max, bas_max = max(0.0, max(ecarts)), max(0.0, -min(ecarts))
    pas = _graduation(haut_max + bas_max)
    haut_max, bas_max = haut_max * 1.08 or pas / 2, bas_max * 1.08 or pas / 2
    zone = hauteur - haut - bas
    echelle = zone / (haut_max + bas_max)
    y0 = haut + haut_max * echelle
    pas_x = (largeur - marge - droite) / len(lignes)
    barre = max(pas_x - 4, 1.5)
    els = []
    v = -pas * int(bas_max // pas)
    while v <= haut_max:
        if v:
            y = y0 - v * echelle
            els.append(f'<line class="grille" x1="{marge}" x2="{largeur - droite}" y1="{y:.1f}" y2="{y:.1f}"/>'
                       f'<text class="axe" x="{marge - 8}" y="{y + 4:.1f}" text-anchor="end">{_repere_euros(v, pas)}</text>')
        v += pas
    els.append(f'<line class="zero" x1="{marge}" x2="{largeur - droite}" y1="{y0:.1f}" y2="{y0:.1f}"/>'
               f'<text class="axe" x="{marge - 8}" y="{y0 + 4:.1f}" text-anchor="end">0</text>')
    n = len(lignes)
    tous = n <= (6 if etroit else 12)
    reperes = ("01", "07") if etroit and n > 12 else ("01", "04", "07", "10")
    annee_prec, dernier = None, None
    for i, (m, revenus, depenses, e) in enumerate(lignes):
        x = marge + i * pas_x + 2
        h = abs(e) * echelle
        annee, num = m.split("-")
        els.append(
            f'<rect class="{"excedent" if e >= 0 else "depassement"}" x="{x:.1f}" y="{(y0 - h) if e >= 0 else y0:.1f}" '
            f'width="{barre:.1f}" height="{max(h, 1):.1f}" rx="2" tabindex="0" data-valeur="{_attr(_signe(e))}" '
            f'data-libelle="{_attr(MOIS[int(num) - 1] + " " + annee)}" '
            f'data-detail="{_attr(f"revenus {_eur(revenus, 0)}, dépenses {_eur(depenses, 0)}")}"/>')
        # le premier mois et les repères trimestriels (ou semestriels) ; deux étiquettes trop proches : la seconde saute
        if tous or ((num in reperes or i == 0) and (dernier is None or i - dernier >= 2)):
            dernier = i
            libelle = MOIS_COURTS[int(num) - 1] + (f" {annee[2:]}" if annee != annee_prec else "")
            annee_prec = annee
            els.append(f'<text class="axe" x="{x + barre / 2:.1f}" y="{hauteur - 18}" text-anchor="middle">{libelle}</text>')
    moyenne = sum(ecarts) / n
    ym = y0 - moyenne * echelle
    els.append(f'<line class="moyenne" x1="{marge}" x2="{largeur - droite}" y1="{ym:.1f}" y2="{ym:.1f}"/>'
               f'<text class="libelle-moyenne" x="{largeur - droite - 4}" y="{(ym + 15) if moyenne < 0 else (ym - 7):.1f}" '
               f'text-anchor="end">moyenne {_signe(moyenne)}</text>')
    debut, fin = lignes[0][0].split("-"), lignes[-1][0].split("-")
    aria = (f"Écart entre tes revenus et tes dépenses, de {MOIS[int(debut[1]) - 1]} {debut[0]} à "
            f"{MOIS[int(fin[1]) - 1]} {fin[0]} : {sum(1 for e in ecarts if e < 0)} mois sur {n} où tu as dépensé "
            f"plus que tes revenus ; en moyenne, {_signe(moyenne)} par mois.")
    return (f'<svg class="graphe {variante}" viewBox="0 0 {largeur} {hauteur}" role="img" '
            f'aria-label="{_attr(aria)}">{"".join(els)}</svg>')


def _ecart(d: dict) -> str:
    """Revenus − dépenses, mois par mois, avec la moyenne : les mois où le budget déborde."""
    pm = d.get("par_mois") or {}
    partiels = set(pm.get("partiels") or [])
    lignes = [(m, r, dep, r - dep) for m, r, dep in zip(pm.get("mois") or [], pm.get("revenus") or [], pm.get("totaux") or [])
              if m not in partiels]
    if len(lignes) < 2 or not any(r for _, r, _, _ in lignes):
        return ""
    moyenne = sum(e for *_, e in lignes) / len(lignes)
    rangs = "".join(f'<tr><td>{MOIS[int(m[5:]) - 1]} {m[:4]}</td><td class="num">{_eur(r)}</td>'
                    f'<td class="num">{_eur(dep)}</td><td class="num">{_signe(e, 2)}</td></tr>' for m, r, dep, e in lignes)
    note = (" Les mois incomplets sont laissés de côté." if partiels else "")
    return (
        '<section class="ecart" aria-labelledby="t-ecart">'
        '<h2 id="t-ecart">Revenus et dépenses, mois par mois</h2>'
        '<p class="intro">Ce qu\'il reste de tes revenus une fois tes dépenses payées. Une barre sous zéro : '
        "ce mois-là, tu as dépensé plus que tes revenus.</p>"
        + _dessin_ecart(lignes, 720, 280, 64, "bureau") + _dessin_ecart(lignes, 360, 240, 52, "mobile")
        + '<ul class="legende"><li><span class="pastille excedent" aria-hidden="true"></span>Revenus supérieurs aux dépenses</li>'
        '<li><span class="pastille depassement" aria-hidden="true"></span>Dépenses supérieures aux revenus</li>'
        f'<li><span class="trait-moyenne" aria-hidden="true"></span>Moyenne sur {len(lignes)} mois : '
        f"<strong>{_signe(moyenne)}</strong> par mois</li></ul>"
        '<details><summary>Voir les montants exacts</summary><div class="tableau"><table><thead><tr><th>Mois</th>'
        '<th class="num">Revenus</th><th class="num">Dépenses</th><th class="num">Écart</th></tr></thead>'
        f"<tbody>{rangs}</tbody></table></div></details>"
        '<p class="note">Les virements entre tes comptes et vers ton épargne ne sont pas des dépenses : ils ne '
        f"comptent pas ici. Un loyer payé à cheval sur deux mois peut faire paraître l'un lourd et l'autre léger.{note}</p>"
        "</section>"
    )


def _livrets(d: dict) -> str:
    """Tes livrets : ce que tu y as mis, ce que tu en as repris, les intérêts, et le bilan (gain ou perte)."""
    livrets = d.get("livrets") or []
    if not livrets:
        return ""
    maxi = max(max(b["verse"], b["retire"]) for b in livrets) or 1.0
    cartes = []
    for b in livrets:
        gain = b["bilan"] >= 0
        barre = lambda classe, libelle, x: (
            f'<div class="lv-ligne"><span class="lv-quoi">{libelle}</span>'
            f'<span class="lv-piste"><span class="lv-barre {classe}" style="width:{100 * x / maxi:.1f}%"></span></span>'
            f'<span class="lv-montant">{_eur(x, 0)}</span></div>')
        soldes = ""
        if b.get("solde_debut") and b.get("solde_fin"):
            soldes = (f'<p class="note">Solde : {_eur(b["solde_debut"]["montant"], 0)} le {_jour(b["solde_debut"]["date"])}, '
                      f'{_eur(b["solde_fin"]["montant"], 0)} le {_jour(b["solde_fin"]["date"])}.</p>')
        if b.get("ecart_soldes"):
            soldes += (f'<p class="note">Écart de {_eur(b["ecart_soldes"])} avec les soldes imprimés : '
                       "un relevé manque peut-être.</p>")
        mois = "".join(f'<tr><td>{MOIS[int(m["mois"][5:]) - 1]} {m["mois"][:4]}</td><td class="num">{_eur(m["verse"])}</td>'
                       f'<td class="num">{_eur(m["retire"])}</td></tr>' for m in b.get("mois") or [])
        detail = ('<details><summary>Mois par mois</summary><div class="tableau"><table><thead><tr><th>Mois</th>'
                  f'<th class="num">Versé</th><th class="num">Repris</th></tr></thead><tbody>{mois}</tbody></table></div>'
                  "</details>") if mois else ""
        sens = "de plus que tu n'en as repris" if gain else "de plus que tu n'y as mis"
        cartes.append(
            f'<div class="livret"><h3>{html.escape(b["nom"])}</h3>'
            f'<p class="lv-bilan {"gain" if gain else "perte"}"><strong>{"+" if gain else "−"}{_eur(abs(b["bilan"]), 0)}</strong>'
            f'<span>{"mis" if gain else "repris"} {sens}, intérêts compris</span></p>'
            + barre("verse", "Versé", b["verse"]) + barre("repris", "Repris", b["retire"])
            + f'<p class="lv-interets">Intérêts : <strong>{_eur(b["interets"])}</strong></p>'
            + soldes + detail + "</div>")
    return ('<section class="livrets" aria-labelledby="t-livrets"><h2 id="t-livrets">Tes livrets</h2>'
            '<p class="intro">De l\'épargne : ni dépense ni revenu. Ce que tu y as versé, ce que tu en as repris '
            "(vers ton compte courant ou ailleurs), les intérêts, et ce qu'il en reste en plus ou en moins sur la période.</p>"
            f'<div class="lv-grille">{"".join(cartes)}</div></section>')


# ---------------------------------------------------------------- page de détail

def _libelle_lisible(libelle: str) -> str:
    """Libellé allégé pour la lecture : sans références de carte, de mandat ni identifiants techniques.
    Les pseudonymes [JETON_n] restent, pour être masqués ou remis en clair ensuite."""
    l = re.sub(r"(\d+,\d+)([A-Z]{3})/1euro=[\d,]+", r"(\1 \2)", libelle)
    l = re.sub(r"(?i)\s*/?\s*(ref\s*)?cb\.?x+\d+.*$", "", l)
    l = re.sub(r"(?i)\s*/\s*carte \d+x+\d+.*$", "", l)
    l = re.sub(r"(?i)\s*cb\*\d{4}", "", l)
    l = re.sub(r"(?i)^carte\s*\d{2}/\d{2}/\d{2}", "Carte ", l)
    l = re.sub(r"(?i)^carte \d{7} ", "Carte ", l)
    l = re.sub(r" le \d{2}/\d{2}/\d{2}", "", l)
    l = re.sub(r"(?i)^(virement (?:sepa |instantané )?(?:émis|reçu)|virement automatique|prélèvement sepa|virement) "
               r"[0-9a-z]{6,8}\b", r"\1", l)
    l = re.sub(r"(?i)\s*\(facture:[^)]*\)", "", l)
    l = re.sub(r"(?i)\s*\bfr\d{2}\s?zzz\w*.*$", "", l)                      # identifiant de créancier SEPA, et la suite
    l = re.sub(r"(?i)\s+\S+\s+sepa\s+\S+\s+(rcur|frst|ooff|fnal)\b.*$", "", l)  # référence de mandat
    l = re.sub(r"(?i)\bech \d{6}\b", "", l)
    # le numéro seul : les lettres collées devant restent (« ECHPRET0001234567 » → « ECHPRET »)
    l = re.sub(r"(?<![\[_\w])(?:ref\s*:?\s*)?\d{8,}[\w-]*|(?<=[A-Za-z])\d{8,}[\w-]*|\b0\dx+\d+\b|\b[0-9a-f]{16,}\b", "", l,
               flags=re.IGNORECASE)
    l = re.sub(r"(?<=[a-z])[A-Z]{1,2}\d{6,}\w*|(?<=[A-Z]{3})[A-Z]\d{6,}\w*", "", l)   # code du magasin collé au nom
    l = re.sub(r"\b[a-zA-Z]?\d{6,}[a-zA-Z]?\b|(?<=[a-z])\d{6,}\b", "", l)
    return re.sub(r"\s{2,}", " ", l).strip(" /:-") or libelle


def _mois_detail(categorie: str, m: str, ops: list[dict], valeurs: dict[str, str] | None, partiel: bool) -> str:
    annee, num = m.split("-")
    total = -sum(o["montant"] for o in ops)
    rangs = "".join(
        f'<tr><td class="date">{o["date"][8:10]}/{o["date"][5:7]}</td>'
        f'<td class="poste">{_texte(_libelle_lisible(o["libelle"]), valeurs)}'
        + (' <span class="marque">remboursement</span>' if o["montant"] > 0 else "")
        + f'</td><td class="num">{("+" if o["montant"] > 0 else "") + _eur(abs(o["montant"]))}</td></tr>'
        for o in ops)
    return (
        f'<details id="cat-{categorie}-{m}"><summary><span class="mois">{MOIS[int(num) - 1]} {annee}'
        + (' <span class="incomplet">incomplet</span>' if partiel else "")
        + f'</span><span class="total">{_eur(total)}</span>'
        f'<span class="nb">{len(ops)} opération{"s" if len(ops) > 1 else ""}</span></summary>'
        '<div class="tableau"><table><thead><tr><th>Date</th><th>Libellé</th><th class="num">Montant</th></tr></thead>'
        f"<tbody>{rangs}</tbody></table></div></details>"
    )


SCRIPT_DETAIL = """
(() => {
  const ouvrir = () => {
    const id = decodeURIComponent(location.hash.slice(1));
    const el = id && document.getElementById(id);
    if (!el) return;
    // une catégorie : tous ses mois dépliés ; un mois : celui-là seulement
    if (el.tagName === "DETAILS") el.open = true;
    else el.querySelectorAll(":scope > details").forEach((d) => { d.open = true; });
    el.scrollIntoView({ block: "start" });
  };
  addEventListener("hashchange", ouvrir);
  ouvrir();
})();
"""


def construire_detail(donnees: dict, valeurs: dict[str, str] | None = None, rapport: str = "") -> str:
    """Page de détail : chaque catégorie de dépense, puis chaque mois, avec toutes ses opérations. Le mois
    le plus récent en haut. Liée depuis le rapport (`rapport` : nom du fichier de la page du rapport)."""
    personnelle = valeurs is not None
    ops = donnees.get("operations") or []
    nb_mois = (donnees.get("periode") or {}).get("nb_mois") or 1
    partiels = set((donnees.get("par_mois") or {}).get("partiels") or [])
    categories = [c for c in donnees.get("categories") or [] if c["montant"] > 0]
    vues = {c["categorie"] for c in categories}
    categories += [{"categorie": l["categorie"], "montant": 0.0}
                   for l in (donnees.get("par_mois") or {}).get("lignes") or [] if l["categorie"] not in vues]
    sommaire, blocs = [], []
    for c in categories:
        k = c["categorie"]
        nom = html.escape(CATEGORIES.get(k, k.replace("_", " ").capitalize()))
        les_ops = [o for o in ops if o["categorie"] == k]
        sommaire.append(f'<li><a href="#cat-{k}">{nom}<span>{_eur(c["montant"], 0)} par mois</span></a></li>')
        mois = sorted({o["date"][:7] for o in les_ops}, reverse=True)
        contenu = "".join(_mois_detail(k, m, [o for o in les_ops if o["date"][:7] == m], valeurs, m in partiels)
                          for m in mois) or '<p class="note">Aucune opération à afficher pour cette catégorie.</p>'
        blocs.append(
            f'<section class="detail-cat" id="cat-{k}" aria-labelledby="h-{k}"><h2 id="h-{k}">{nom}</h2>'
            f'<p class="intro">{_eur(c["montant"], 0)} par mois en moyenne, soit {_eur(c["montant"] * nb_mois, 0)} '
            f"sur la période, en {len(les_ops)} opération{'s' if len(les_ops) > 1 else ''}. "
            f"Le mois le plus récent est en haut.</p>{contenu}"
            f'<p class="retour"><a href="#sommaire">Toutes les catégories</a>'
            + (f' · <a href="{_attr(rapport)}#t-cat">Retour au rapport</a>' if rapport else "") + "</p></section>")
    badge = (f'<p class="confidentialite perso">{ICONE_CADENAS}<span><strong>Version personnelle.</strong> '
             "Elle contient tes vrais noms : garde-la pour toi.</span></p>" if personnelle else
             f'<p class="confidentialite anonyme">{ICONE_MASQUE}<span><strong>Version anonyme.</strong> '
             "Les noms restent des pseudonymes.</span></p>")
    titre = "Le détail de tes dépenses" + ("" if personnelle else " (version anonyme)")
    corps = (
        '<header class="tete"><div class="tete-titres"><h1>Le détail de tes dépenses</h1>'
        f'<p class="periode">{html.escape(_periode_lisible(donnees["periode"]))}. Catégorie par catégorie, mois par mois.</p>'
        f"</div>{badge}</header>"
        + (f'<p class="retour"><a href="{_attr(rapport)}">Retour au rapport</a></p>' if rapport else "")
        + f'<nav class="sommaire" id="sommaire" aria-label="Catégories"><ul>{"".join(sommaire)}</ul></nav>'
        + "".join(blocs)
    )
    return (
        '<!doctype html>\n<html lang="fr">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="color-scheme" content="light dark">\n'
        f"<title>{html.escape(titre)}</title>\n<style>{CSS}</style>\n</head>\n<body>\n"
        f'<main class="feuille"><div class="ruban" aria-hidden="true"></div>{corps}</main>\n'
        f"<script>{SCRIPT}{SCRIPT_DETAIL}</script>\n</body>\n</html>\n"
    )


def construire_page(donnees: dict, valeurs: dict[str, str] | None = None, detail: str | None = None) -> str:
    """Page complète. `valeurs` (table pseudonyme -> vraie valeur) donne la version personnelle ;
    sans elle, la version anonyme. `detail` : nom de la page de détail, vers laquelle mènent les catégories."""
    personnelle = valeurs is not None
    titre = "Analyse budgétaire" + ("" if personnelle else " (version anonyme)")
    corps = (
        _entete(donnees, personnelle)
        + _alerte(donnees)
        + _recap(donnees)
        + f'<div class="colonnes">{_synthese(donnees, valeurs)}{_categories(donnees, valeurs, detail)}</div>'
        + _a_verifier(donnees, valeurs)
        + _ecart(donnees)
        + _livrets(donnees)
        + _par_mois(donnees, detail)
        + _proches(donnees, valeurs)
        + _recurrents(donnees, valeurs)
        + _lectures(donnees)
        + _pied(donnees)
    )
    return (
        '<!doctype html>\n<html lang="fr">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="color-scheme" content="light dark">\n'
        f"<title>{html.escape(titre)}</title>\n<style>{CSS}</style>\n</head>\n<body>\n"
        f'<main class="feuille"><div class="ruban" aria-hidden="true"></div>{corps}</main>\n'
        f"<script>{SCRIPT}</script>\n</body>\n</html>\n"
    )


def ecrire_pages(chemin_md: Path, donnees: dict, valeurs: dict[str, str],
                 ecrire_donnees: bool = True) -> tuple[Path, Path, Path]:
    """rapport.md -> rapport.html (personnelle), rapport_anonyme.html, rapport.json (données), et quand
    les opérations sont là, leur page de détail : rapport_detail.html et rapport_anonyme_detail.html."""
    perso = chemin_md.with_suffix(".html")
    anonyme = chemin_md.with_name(chemin_md.stem + "_anonyme.html")
    chemin_json = chemin_md.with_suffix(".json")
    detail_perso = detail_anonyme = None
    if donnees.get("operations"):
        detail_perso = chemin_md.with_name(chemin_md.stem + "_detail.html")
        detail_anonyme = chemin_md.with_name(chemin_md.stem + "_anonyme_detail.html")
        detail_perso.write_text(construire_detail(donnees, valeurs, perso.name), encoding="utf-8")
        detail_anonyme.write_text(construire_detail(donnees, None, anonyme.name), encoding="utf-8")
    perso.write_text(construire_page(donnees, valeurs, detail_perso and detail_perso.name), encoding="utf-8")
    anonyme.write_text(construire_page(donnees, None, detail_anonyme and detail_anonyme.name), encoding="utf-8")
    if ecrire_donnees:
        chemin_json.write_text(json.dumps(donnees, ensure_ascii=False, indent=2), encoding="utf-8")
    return perso, anonyme, chemin_json


SCRIPT = """
(() => {
  const bulle = document.createElement("div");
  bulle.className = "bulle";
  bulle.setAttribute("role", "tooltip");
  bulle.hidden = true;
  const valeur = document.createElement("strong");
  const libelle = document.createElement("span");
  const detail = document.createElement("span");
  bulle.append(valeur, libelle, detail);
  document.body.append(bulle);
  const montrer = (el, x, y) => {
    valeur.textContent = el.dataset.valeur;
    libelle.textContent = el.dataset.libelle;
    detail.textContent = el.dataset.detail || "";
    bulle.hidden = false;
    const r = bulle.getBoundingClientRect();
    let gauche = Math.min(x + 14, window.innerWidth - r.width - 8);
    let haut = y - r.height - 12;
    if (haut < 8) haut = y + 20;
    bulle.style.left = Math.max(8, gauche) + "px";
    bulle.style.top = haut + "px";
  };
  const cacher = () => { bulle.hidden = true; };
  document.querySelectorAll("[data-valeur]").forEach((el) => {
    el.addEventListener("pointermove", (e) => montrer(el, e.clientX, e.clientY));
    el.addEventListener("pointerleave", cacher);
    el.addEventListener("focus", () => {
      const r = el.getBoundingClientRect();
      montrer(el, r.left + Math.min(r.width / 2, 120), r.top);
    });
    el.addEventListener("blur", cacher);
  });
  window.addEventListener("beforeprint", () => {
    document.querySelectorAll("details").forEach((d) => { d.open = true; });
  });
})();
"""

CSS = """
:root{
  color-scheme:light;
  --plan:#e6eeec; --feuille:#fcfcfb; --encre:#12303a; --encre-2:#48646d; --encre-3:#566c74;
  --filet:#dbe3e1; --lagon:#0b6a70; --lagon-voile:rgba(11,106,112,.10);
  --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --piste:#dde5e3; --cat:#4d6f7c;
  --alerte:#8a4b00; --alerte-fond:#fff3dc; --alerte-icone:#fab219; --critique:#d03b3b;
  --police-ui:"Bahnschrift","DIN Alternate","DIN 2014","Barlow","Segoe UI",system-ui,sans-serif;
  --police-texte:"Sitka Text","Iowan Old Style",Charter,"Bitstream Charter",Cambria,Georgia,serif;
}
@media (prefers-color-scheme:dark){:root{
  color-scheme:dark;
  --plan:#0b1416; --feuille:#172123; --encre:#eef3f2; --encre-2:#b4c4c6; --encre-3:#8a9da1;
  --filet:#2a3638; --lagon:#63c7cc; --lagon-voile:rgba(99,199,204,.14);
  --s1:#3987e5; --s2:#d95926; --s3:#199e70; --piste:#2a3638; --cat:#8db3bf;
  --alerte:#fbd38a; --alerte-fond:#3a2a10; --critique:#e66767;
}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;padding:clamp(12px,3vw,40px) clamp(10px,3vw,32px);background:var(--plan);color:var(--encre);
  font:400 15px/1.5 var(--police-ui)}
.feuille{position:relative;max-width:1100px;margin:0 auto;background:var(--feuille);border:1px solid var(--filet);
  border-radius:4px;padding:clamp(20px,4.5vw,56px);overflow:hidden}
.ruban{position:absolute;inset:0 0 auto 0;height:8px;
  background:linear-gradient(0deg,rgba(255,255,255,.22) 0 2px,transparent 2px 5px,rgba(0,0,0,.08) 5px 6px,transparent 6px),
  repeating-linear-gradient(90deg,#eda100 0 22px,#e34948 22px 26px,#eda100 26px 38px,#008300 38px 52px,
  #12303a 52px 54px,#eb6834 54px 74px,#2a78d6 74px 78px,#008300 78px 92px,#e34948 92px 104px)}
h1,h2,h3{font-family:var(--police-ui);font-stretch:87.5%;letter-spacing:-.005em;margin:0}
h1{font-size:40px;line-height:1.1;font-weight:650}
h2{font-size:28px;line-height:1.2;font-weight:600;margin-bottom:6px}
h3{font-size:19px;line-height:1.3;font-weight:600;display:flex;align-items:center;gap:10px}
p{margin:0}
strong{font-weight:650}
.visuellement-cache{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.ico{width:1.05em;height:1.05em;flex:none;vertical-align:-.15em}
:focus-visible{outline:2px solid var(--lagon);outline-offset:3px;border-radius:2px}

.tete{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:flex-start;gap:16px 32px;margin-top:8px}
.periode{margin-top:8px;font-size:17px;color:var(--encre-2)}
.confidentialite{display:flex;gap:10px;align-items:flex-start;max-width:340px;padding:10px 14px;border-radius:4px;
  font-size:14px;line-height:1.4;color:var(--encre-2);border:1px solid var(--filet)}
.confidentialite .ico{color:var(--lagon);margin-top:1px}
.confidentialite strong{color:var(--encre)}

.alerte{display:flex;gap:10px;align-items:flex-start;margin-top:28px;padding:12px 16px;border-radius:4px;
  background:var(--alerte-fond);color:var(--alerte);font-size:15px}
.alerte .ico{color:var(--alerte-icone);margin-top:2px}

.recap{margin-top:clamp(32px,6vw,64px)}
.recap-haut{display:grid;grid-template-columns:1fr auto;align-items:end;gap:8px 24px;margin-bottom:14px}
.depense{font-size:21px;color:var(--encre-2);padding-bottom:10px}
.depense strong{color:var(--encre)}
.reste{text-align:right;display:flex;flex-direction:column;align-items:flex-end}
.reste-libelle{font-size:17px;color:var(--encre-2);display:flex;gap:6px;align-items:center}
.hero{font-size:clamp(48px,9vw,76px);line-height:.95;font-weight:650;font-stretch:87.5%;letter-spacing:-.02em;color:var(--encre)}
.hero-neutre{font-size:clamp(28px,5vw,40px);color:var(--encre-2)}
.deficit .hero{color:var(--critique)}
.deficit .ico{color:var(--critique)}
.barre{position:relative;display:flex;gap:2px;height:24px;background:var(--feuille);border-radius:0 4px 4px 0}
.seg{display:block;flex-basis:0;min-width:2px;height:100%;cursor:default}
.seg:last-of-type{border-radius:0 4px 4px 0}
.seg.s1{background:var(--s1)}.seg.s2{background:var(--s2)}.seg.s3{background:var(--s3)}.seg.piste{background:var(--piste)}
.seg:hover,.seg:focus-visible{filter:brightness(1.12)}
.seg.piste:hover,.seg.piste:focus-visible{filter:brightness(.96)}
.repere{position:absolute;top:-8px;bottom:-8px;width:0;border-left:2px solid var(--encre)}
.repere span{position:absolute;top:100%;left:6px;margin-top:4px;font-size:13px;color:var(--encre-2);white-space:nowrap}
@media (prefers-reduced-motion:no-preference){
  .barre{animation:deroule .9s cubic-bezier(.2,.7,.2,1) both .15s}
  @keyframes deroule{from{clip-path:inset(0 100% 0 0)}to{clip-path:inset(0 0 0 0)}}
}
.legende{list-style:none;margin:16px 0 0;padding:0;display:flex;flex-wrap:wrap;gap:8px 28px;font-size:15px;color:var(--encre-2)}
.legende li{display:flex;align-items:center;gap:8px}
.legende strong{color:var(--encre)}
.legende .part{color:var(--encre-3);font-size:13px}
.pastille{display:inline-block;width:12px;height:12px;border-radius:2px;flex:none}
.pastille.s1{background:var(--s1)}.pastille.s2{background:var(--s2)}.pastille.s3{background:var(--s3)}
.pastille.cat{background:var(--cat)}
.pastille.piste{background:var(--piste);box-shadow:inset 0 0 0 1px var(--filet)}
.base{margin-top:10px;font-size:13px;color:var(--encre-3)}
.hors-depenses{margin-top:22px;padding:14px 16px;border-left:3px solid var(--piste);background:var(--lagon-voile);
  border-radius:0 4px 4px 0;max-width:72ch}
.hors-titre{font-size:14px;font-weight:600;color:var(--encre-2)}
.hors-depenses ul{list-style:none;margin:8px 0 0;padding:0;display:grid;gap:4px;font-size:15px;color:var(--encre-2)}
.hors-depenses strong{color:var(--encre)}
.hors-depenses .retour{font-size:13px;color:var(--encre-3)}
.hors-note{margin-top:10px;font-size:13px;color:var(--encre-3)}
.hors-note code{font-size:12px;padding:1px 4px;border-radius:3px;background:var(--feuille)}
.alerte ul{margin:8px 0 0;padding-left:1.2em;font-size:14px}

.colonnes{display:grid;grid-template-columns:minmax(0,7fr) minmax(0,5fr);gap:clamp(32px,5vw,64px);
  margin-top:clamp(40px,6vw,72px);padding-top:clamp(32px,4vw,48px);border-top:1px solid var(--filet)}
.intro{color:var(--encre-2);margin-bottom:20px}
.prose{font-family:var(--police-texte);font-size:17px;line-height:1.65;max-width:68ch;margin-top:14px}
.prose p{margin:0 0 1em}
.prose ol,.prose ul{margin:0 0 1em;padding-left:1.3em}
.prose li{margin:.45em 0}
.prose strong{font-weight:700}
.prose .intertitre{margin:1.6em 0 .5em;font-family:var(--police-ui);font-size:15px;font-weight:600;
  color:var(--encre-2);letter-spacing:.01em}
.prose .intertitre:first-child{margin-top:0}
.note{font-size:13px;color:var(--encre-3);max-width:68ch}
.categories .note{margin-top:12px}

.barres{list-style:none;margin:0;padding:0;display:grid;gap:2px}
.ligne{display:grid;grid-template-columns:minmax(96px,38%) 1fr auto;align-items:center;gap:12px;
  padding:6px 4px;border-radius:3px;outline-offset:1px}
.ligne:hover,.ligne:focus-visible{background:var(--lagon-voile)}
.ligne .nom{font-size:14px;color:var(--encre-2);overflow-wrap:anywhere}
.piste-cat{display:block;height:12px}
.remplissage{display:block;height:100%;min-width:2px;background:var(--cat);border-radius:0 4px 4px 0}
.ligne .montant{font-size:14px;font-variant-numeric:tabular-nums;color:var(--encre);min-width:4.5em;text-align:right}
details{margin-top:16px;font-size:14px}
summary{cursor:pointer;color:var(--lagon);width:max-content}

.par-mois{margin-top:clamp(40px,6vw,72px);padding-top:clamp(32px,4vw,48px);border-top:1px solid var(--filet)}
.chaleur{overflow-x:auto;margin-top:4px}
.chaleur table{min-width:640px;border-collapse:separate;border-spacing:2px;font-size:13.5px}
.chaleur th,.chaleur td{border:0;padding:7px 9px;white-space:nowrap}
.chaleur td{border-radius:3px;font-variant-numeric:tabular-nums}
.chaleur thead th{font-size:12.5px;font-weight:600;color:var(--encre-3);vertical-align:bottom}
.chaleur thead .annee,.chaleur thead .incomplet{display:block;font-weight:400}
.chaleur thead .incomplet{font-style:italic}
.chaleur tbody th,.chaleur tfoot th,.chaleur thead th:first-child{position:sticky;left:0;z-index:1;
  background:var(--feuille);text-align:left}
.chaleur tbody th{font-weight:500;color:var(--encre-2)}
.chaleur td.vide{color:var(--encre-3)}
.chaleur .moyenne{font-weight:650;box-shadow:inset 2px 0 0 var(--filet)}
.chaleur tfoot th,.chaleur tfoot td{font-weight:650;box-shadow:inset 0 1px 0 var(--filet)}
.chaleur tfoot td.moyenne{box-shadow:inset 2px 1px 0 var(--filet)}
.recurrents{margin-top:clamp(40px,6vw,72px);padding-top:clamp(32px,4vw,48px);border-top:1px solid var(--filet)}
.groupe{margin-top:36px}
.groupe-tete{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:baseline;gap:4px 24px}
.groupe-total{font-size:15px;color:var(--encre-2)}
.groupe-total strong{font-size:19px;color:var(--encre)}
.abonnement_optionnel .groupe-total strong{color:var(--encre)}
.groupe-explication{margin-top:4px;font-size:14px;color:var(--encre-3);max-width:72ch}
.tableau{overflow-x:auto;margin-top:14px}
table{width:100%;border-collapse:collapse;font-size:14px}
th{text-align:left;font-weight:600;font-size:13px;color:var(--encre-3);padding:8px 12px 8px 0;
  border-bottom:1px solid var(--filet);white-space:nowrap}
td{padding:10px 12px 10px 0;border-bottom:1px solid var(--filet);vertical-align:top}
tbody tr:last-child td{border-bottom:0}
.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
td.poste{font-weight:500;overflow-wrap:anywhere}
td.pourquoi{color:var(--encre-2)}
/* mêmes colonnes dans tous les groupes : les montants restent alignés d'un tableau à l'autre */
.groupe table{table-layout:fixed;min-width:760px}
.groupe th:nth-child(1){width:29%}.groupe th:nth-child(2){width:12%}.groupe th:nth-child(3){width:14%}
.groupe th:nth-child(4){width:10%}.groupe th:nth-child(5){width:9%}.groupe th:nth-child(6){width:26%}
.groupe td:nth-child(3){white-space:nowrap}
.variable{display:block;font-size:12px;color:var(--encre-3)}
.vide{margin-top:16px;color:var(--encre-2)}
.lectures{margin-top:clamp(40px,6vw,72px);padding-top:clamp(32px,4vw,48px);border-top:1px solid var(--filet)}
.lectures .intro{margin-bottom:8px}
.a-verifier{margin-top:clamp(40px,6vw,72px);padding-top:clamp(32px,4vw,48px);border-top:1px solid var(--filet)}
.a-verifier table{min-width:760px}
.proches{margin-top:clamp(40px,6vw,72px);padding-top:clamp(32px,4vw,48px);border-top:1px solid var(--filet)}
.proches table{min-width:760px}
.proches details table{min-width:0}
.proches h3{margin-top:24px;font-size:15px}
.proches .note{margin-top:14px}
.lectures td.juste{color:var(--encre-2)}
.lectures td.ecart{color:var(--critique);font-weight:600}
.lectures td.inconnu{color:var(--alerte)}

.masque{display:inline-flex;align-items:center;gap:4px;padding:0 7px 0 5px;border-radius:999px;
  background:var(--lagon-voile);color:var(--lagon);font-family:var(--police-ui);font-size:.88em;
  font-weight:500;line-height:1.55;white-space:nowrap;vertical-align:baseline}
.demasque{background:none;color:inherit;text-decoration:underline dotted var(--lagon);
  text-decoration-thickness:2px;text-underline-offset:3px;cursor:help}

.pied{margin-top:clamp(40px,6vw,72px);padding-top:20px;border-top:1px solid var(--filet);
  font-size:13px;color:var(--encre-3);display:grid;gap:4px}

.bulle[hidden]{display:none}
.bulle{position:fixed;z-index:10;pointer-events:none;display:grid;gap:2px;max-width:260px;padding:9px 12px;
  border-radius:4px;background:var(--encre);color:var(--feuille);font-size:13px;line-height:1.35;
  box-shadow:0 6px 20px rgba(0,0,0,.18)}
.bulle strong{font-size:15px}
.bulle span:last-child{opacity:.8}

@media (max-width:860px){
  .colonnes{grid-template-columns:1fr}
}
@media (max-width:560px){
  h1{font-size:32px}
  .recap-haut{grid-template-columns:1fr}
  .reste{align-items:flex-start;text-align:left}
  .depense{padding-bottom:0}
  .confidentialite{max-width:none}
  .chaleur tbody th,.chaleur tfoot th{white-space:normal;min-width:7.5em;max-width:9em}
}
@media print{
  body{background:#fff;padding:0}
  .feuille{border:0;max-width:none;padding:0}
  .bulle{display:none}
  .barre,.seg,.remplissage,.pastille,.ruban,.chaleur td{-webkit-print-color-adjust:exact;print-color-adjust:exact}
  .chaleur{overflow:visible}.chaleur table{min-width:0;font-size:11px}
  .barre{animation:none}
  .groupe,tr{break-inside:avoid}
  h2,h3{break-after:avoid}
}
.graphe{width:100%;height:auto;display:block;margin:12px 0 8px;font-family:var(--police-ui)}
.graphe .grille{stroke:var(--filet);stroke-width:1}
.graphe .zero{stroke:var(--encre-3);stroke-width:1.5}
.graphe .axe{fill:var(--encre-3);font-size:12px}
.graphe rect:focus-visible{outline:2px solid var(--lagon);outline-offset:2px}
.graphe .excedent,.pastille.excedent{fill:var(--lagon);background:var(--lagon)}
.graphe .depassement,.pastille.depassement{fill:var(--s2);background:var(--s2)}
.graphe .moyenne{stroke:var(--encre);stroke-width:1.75;stroke-dasharray:6 4}
.graphe .libelle-moyenne{fill:var(--encre);font-size:12px;font-weight:600;paint-order:stroke;stroke:var(--feuille);stroke-width:4px;stroke-linejoin:round}
.trait-moyenne{display:inline-block;width:18px;border-top:2px dashed var(--encre);flex:none}
.graphe.mobile{display:none}
@media (max-width:600px){.graphe.bureau{display:none}.graphe.mobile{display:block}}
.vers-detail{color:inherit;text-decoration-color:var(--filet);text-underline-offset:3px}
.vers-detail:hover,.vers-detail:focus-visible{text-decoration-color:var(--lagon)}
.barres .ligne,.categories tbody tr{position:relative;cursor:pointer}
.barres .ligne .vers-detail::after,.categories tbody .vers-detail::after{content:"";position:absolute;inset:0}
.barres .ligne:hover .vers-detail,.categories tbody tr:hover .vers-detail{text-decoration-color:var(--lagon)}
.chaleur td a{color:inherit;text-decoration:none;display:block}
.chaleur td a:hover,.chaleur td a:focus-visible{text-decoration:underline}
.retour{font-family:var(--police-ui);margin:16px 0 0}
.retour a{color:inherit;text-decoration-color:var(--filet);text-underline-offset:3px}
.sommaire ul{list-style:none;padding:0;margin:24px 0 0;display:flex;flex-wrap:wrap;gap:8px}
.sommaire a{display:inline-flex;gap:7px;align-items:baseline;padding:6px 12px;border:1px solid var(--filet);border-radius:999px;color:var(--encre);text-decoration:none;font-family:var(--police-ui)}
.sommaire a:hover,.sommaire a:focus-visible{border-color:var(--lagon)}
.sommaire a span{font-size:13px;color:var(--encre-3);font-variant-numeric:tabular-nums}
.detail-cat{margin-top:44px;scroll-margin-top:16px}
.detail-cat>details{border-top:1px solid var(--filet);scroll-margin-top:16px}
.detail-cat summary{display:flex;width:auto;gap:16px;align-items:baseline;padding:10px 8px;color:var(--encre);font-family:var(--police-ui)}
.detail-cat summary .mois{flex:1;font-weight:600}
.detail-cat summary .total{font-variant-numeric:tabular-nums;font-weight:600}
.detail-cat summary .nb{color:var(--encre-3);font-size:14px;min-width:120px;text-align:right}
.detail-cat details[open]>summary{background:var(--lagon-voile)}
.detail-cat td.date{white-space:nowrap;color:var(--encre-3)}
.livrets{margin-top:clamp(32px,6vw,64px)}
.lv-grille{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:20px 28px}
.livret{padding-top:14px;border-top:2px solid var(--piste)}
.lv-bilan{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 10px;margin:6px 0 14px}
.lv-bilan strong{font-size:30px;line-height:1.1;font-variant-numeric:tabular-nums}
.lv-bilan span{color:var(--encre-2);font-size:14px}
.lv-bilan.gain strong{color:var(--s3)}
.lv-bilan.perte strong{color:var(--critique)}
.lv-ligne{display:grid;grid-template-columns:64px 1fr auto;align-items:center;gap:10px;margin:6px 0;font-size:14px}
.lv-quoi{color:var(--encre-2)}
.lv-piste{height:10px;border-radius:999px;background:var(--piste);overflow:hidden}
.lv-barre{display:block;height:100%;border-radius:999px}
.lv-barre.verse{background:var(--s3)}
.lv-barre.repris{background:var(--s2)}
.lv-montant{font-variant-numeric:tabular-nums;color:var(--encre);min-width:72px;text-align:right}
.lv-interets{margin:10px 0 4px;font-size:14px;color:var(--encre-2)}
.detail-cat summary .incomplet{font-weight:400;font-style:italic;color:var(--encre-3)}
.marque{font-size:12px;padding:1px 6px;border-radius:4px;background:var(--lagon-voile);color:var(--lagon);font-family:var(--police-ui);white-space:nowrap}
@media (max-width:600px){.detail-cat summary .nb{min-width:0}}
"""
