"""Lecture d'un bulletin de paie PDF, sur ton PC et sans IA, en trois temps :

1. `extraire_pages` : les mots de chaque page, avec leur position, regroupés en lignes ;
2. l'anonymisation (paie/anonymisation.py) remplace nom, adresse, numéro de sécurité sociale… par des pseudonymes,
   mot par mot, sans toucher aux positions ;
3. `lire_bulletin` : le tableau. Code de rubrique, libellé, puis des colonnes de montants (base, taux, retenue
   salariale, gain, part employeur). Le texte seul ne dit pas dans quelle colonne tombe un montant : mas lit la
   position de chaque mot. Les colonnes se calibrent sur le bulletin lui-même (`calibrer`) ; à défaut, celles d'un
   bulletin A4 courant, réglables dans config.yaml (`paie.colonnes`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .modeles import Bulletin, Ligne
from .natures import nature_de, normaliser

NOMBRE = re.compile(r"^-?\d+,\d{2,3}-?$")
MILLIERS = re.compile(r"^-?\d{1,3}$")
SUITE = re.compile(r"^\d{3},\d{2,3}-?$")
CODE = re.compile(r"^(?:[0-9A-Z]{3}|(?=[A-Z]*\d)[0-9A-Z]{4})$")     # « 001 », « 34C », « MBR » ; pas « POUR »
LIGNE_BASE = re.compile(r"REMUNERATION BRUTE|SALAIRE DE BASE|TRAITEMENT DE BASE|APPOINTEMENT")
LIGNE_PAS = re.compile(r"\bPAS\b|PRELEVEMENT A LA SOURCE|IMPOT SUR LE REVENU PRELEVE")


@dataclass
class Colonnes:
    """Bord droit (x1, en points) au-delà duquel un montant change de colonne."""
    libelle: float = 285      # avant : code et libellé
    base: float = 340
    taux: float = 390
    retenue: float = 450
    gain: float = 520         # au-delà : part employeur, ignorée


def _valeur(texte: str) -> float:
    negatif = texte.startswith("-") or texte.endswith("-")
    return (-1 if negatif else 1) * float(texte.strip("-").replace(",", "."))


def _lignes(page, tolerance: float = 2.5) -> list[list[dict]]:
    mots = sorted(page.extract_words(keep_blank_chars=False, use_text_flow=False), key=lambda w: (w["top"], w["x0"]))
    lignes: list[list[dict]] = []
    for w in mots:
        if lignes and abs(lignes[-1][0]["top"] - w["top"]) <= tolerance:
            lignes[-1].append(w)
        else:
            lignes.append([w])
    resultat = []
    for ligne in lignes:
        ligne.sort(key=lambda w: w["x0"])
        fusion: list[dict] = []
        for w in ligne:          # « 3 » « 538,34 » : un seul nombre, 3 538,34
            mot = {"text": w["text"], "x0": w["x0"], "x1": w["x1"], "top": w["top"]}
            if (fusion and MILLIERS.match(fusion[-1]["text"]) and SUITE.match(mot["text"])
                    and mot["x0"] - fusion[-1]["x1"] < 8):
                fusion[-1] = {**fusion[-1], "text": fusion[-1]["text"] + mot["text"], "x1": mot["x1"]}
            else:
                fusion.append(mot)
        resultat.append(fusion)
    return resultat


def extraire_pages(chemin: Path | str) -> list[dict]:
    """[{hauteur, lignes: [[mot (text, x0, x1, top)…]…]}…] : rien n'est encore lu, ni anonymisé."""
    import pdfplumber

    with pdfplumber.open(chemin) as pdf:
        return [{"hauteur": page.height, "lignes": _lignes(page)} for page in pdf.pages]


def _decouper(ligne: list[dict], libelle_max: float) -> tuple[str, str, list[dict]]:
    mots = [w for w in ligne if w["text"] != "*"]
    if not mots:
        return "", "", []
    # Un code de rubrique (« 001 », « 34C ») ouvre la ligne, à gauche du libellé
    code = mots[0]["text"] if CODE.match(mots[0]["text"]) and mots[0]["x0"] < 60 and len(mots) > 1 else ""
    libelle = " ".join(w["text"] for w in mots[1 if code else 0:] if w["x1"] <= libelle_max).strip()
    nombres = [w for w in mots if NOMBRE.match(w["text"])]
    return code, libelle, nombres


def calibrer(pages: list[dict]) -> Colonnes | None:
    """Les colonnes d'après le bulletin lui-même : le salaire de base tombe dans la colonne des gains, le total des
    cotisations dans celle des retenues, la ligne d'impôt donne la base, le taux et la retenue. None si le bulletin
    n'a pas ces repères."""
    gain = retenue = base = taux = gauche = None
    for page in pages:
        for ligne in page["lignes"]:
            _, libelle, nombres = _decouper(ligne, 10_000)
            cle = normaliser(re.sub(r"[\d,\-]+", " ", libelle))
            if not nombres:
                continue
            if gain is None and LIGNE_BASE.search(cle) and not re.search(r"ANTER|RAPPEL|REGUL", cle):
                gain = nombres[-1]["x1"]
            elif retenue is None and cle.startswith("TOTAL COTISATIONS"):
                retenue = nombres[0]["x1"]
            elif base is None and LIGNE_PAS.search(cle) and len(nombres) >= 3:
                base, taux, retenue_pas = (w["x1"] for w in nombres[-3:])
                gauche = nombres[-3]["x0"]
                retenue = retenue or retenue_pas
    if None in (gain, retenue, base, taux, gauche) or not base < taux < retenue < gain:
        return None
    return Colonnes(libelle=gauche - 4, base=(base + taux) / 2, taux=(taux + retenue) / 2, retenue=(retenue + gain) / 2,
                    gain=gain + (gain - retenue) / 2)


def analyser_lignes(pages: list[dict], colonnes: Colonnes | None = None) -> dict:
    """Les pages (déjà anonymisées) → les champs du bulletin. Le tableau se lit en trois temps : les lignes de
    paie ; les cotisations (une ligne de cotisation a un taux ou une part employeur) jusqu'à leur total ; ce qui
    vient après (indemnités, frais, régularisations). Le net à payer est le montant le plus à droite du pied de la
    dernière page, le net avant impôt celui qui vaut le net à payer plus l'impôt."""
    col = colonnes or Colonnes()
    r = {"periode": None, "lignes": [], "apres_net": [], "brut": None, "net_social": None, "cotisations": None,
         "remboursements": 0.0, "net_imposable": None, "taux_pas": None, "impot": None, "net_avant_impot": None,
         "net_paye": None, "pas_libelle": ""}
    etape = "gains"
    commence = False          # le tableau commence au premier code de rubrique ou au salaire de base
    # Un bulletin qui numérote ses rubriques : une ligne sans code n'est pas une ligne de paie (l'en-tête répété en
    # haut de chaque page, un encart d'information…)
    avec_codes = sum(1 for page in pages for ligne in page["lignes"] if _decouper(ligne, col.libelle)[0]) >= 3
    pied: list[tuple[float, float]] = []
    for i, page in enumerate(pages):
        hauteur = page.get("hauteur") or 842
        for ligne in page["lignes"]:
            textes = [w["text"] for w in ligne]
            cle = normaliser(" ".join(textes))
            if cle.startswith("PERIODE"):
                dates = re.findall(r"\b(\d{2}) ?[/.]? ?(\d{2}) ?[/.]? ?(\d{4})\b", " ".join(textes[1:]))
                if dates and r["periode"] is None:
                    r["periode"] = f"{dates[0][2]}-{dates[0][1]}"
                continue
            if ligne[0]["top"] >= 0.875 * hauteur:
                if i == len(pages) - 1:
                    pied += [(w["x1"], _valeur(w["text"])) for w in ligne if NOMBRE.match(w["text"])]
                continue
            code, libelle, mots_nombres = _decouper(ligne, col.libelle)
            nombres = [(w["x1"], _valeur(w["text"])) for w in mots_nombres if w["x0"] >= col.libelle]
            par_colonne: dict[str, float] = {}
            for x, v in nombres:
                nom = ("base" if x <= col.base else "taux" if x <= col.taux else "retenue" if x <= col.retenue
                       else "gain" if x <= col.gain else "patronal")
                par_colonne.setdefault(nom, v)
            cle_lib = normaliser(libelle)
            if cle_lib.startswith("MONTANT BRUT") or cle_lib == "SALAIRE BRUT" or cle_lib == "TOTAL BRUT":
                r["brut"] = par_colonne.get("gain")
                etape = "cotisations"
                continue
            if cle_lib.startswith("MONTANT NET SOCIAL") or cle_lib == "NET SOCIAL":
                r["net_social"] = par_colonne.get("gain")
                etape = "apres"
                continue
            if cle_lib.startswith("TOTAL COTISATIONS") or cle_lib.startswith("TOTAL DES COTISATIONS"):
                # Le total imprime les cotisations remboursées dans la colonne des gains
                r["cotisations"] = round(par_colonne.get("retenue", 0.0) - par_colonne.get("gain", r["remboursements"]), 2)
                etape = "apres"
                continue
            if LIGNE_PAS.search(cle_lib) and "retenue" in par_colonne:
                # Le prélèvement du mois, puis ses éventuelles régularisations (« MT REGUL PAS JANVIER »)
                if r["impot"] is None:
                    r["net_imposable"], r["taux_pas"] = par_colonne.get("base"), par_colonne.get("taux")
                    r["pas_libelle"] = libelle
                r["impot"] = round((r["impot"] or 0.0) + par_colonne["retenue"], 2)
                continue
            if "NET SOCIAL" in cle_lib:             # régularisation du net social : pour information
                continue
            # Le tableau commence à la première ligne de paie : un code de rubrique ou le salaire de base, avec un
            # gain ou une retenue (un encart d'information au-dessus du tableau n'en est pas une)
            commence = commence or ((bool(code) or bool(LIGNE_BASE.search(cle_lib)))
                                    and ("gain" in par_colonne or "retenue" in par_colonne))
            if not commence or not libelle or ("gain" not in par_colonne and "retenue" not in par_colonne):
                continue
            if avec_codes and not code:
                continue
            cotisation = "taux" in par_colonne or "patronal" in par_colonne
            if etape != "apres" and (cotisation or etape == "cotisations"):
                etape = "cotisations"
                if "gain" in par_colonne:           # une cotisation remboursée (régularisation de retraite…)
                    r["remboursements"] += par_colonne["gain"]
                continue
            montant = par_colonne["gain"] if "gain" in par_colonne else -par_colonne["retenue"]
            r["lignes" if etape == "gains" else "apres_net"].append((code, libelle, round(montant, 2)))
    a_droite = [(x, v) for x, v in pied if x > col.gain]
    if a_droite:
        r["net_paye"] = max(a_droite)[1]
        attendu = r["net_paye"] + (r["impot"] or 0.0)
        r["net_avant_impot"] = next((v for _, v in pied if abs(v - attendu) < 0.015), None)
    r["remboursements"] = round(r["remboursements"], 2)
    return r


def lire_bulletin(pages: list[dict], fichier: str, corrections: dict[str, str] | None = None,
                  colonnes: Colonnes | None = None) -> Bulletin | None:
    """Le bulletin, lu dans des pages déjà anonymisées. None si ce n'est pas un bulletin lisible (pas de période,
    pas de lignes de paie ou pas de net)."""
    r = analyser_lignes(pages, colonnes or calibrer(pages))
    if not r["periode"] or not r["lignes"] or (r["net_paye"] is None and r["cotisations"] is None):
        return None
    paie = [Ligne(lib, m, nature_de(lib, corrections), code) for code, lib, m in r["lignes"]]
    apres = [Ligne(lib, m, nature_de(lib, corrections), code) for code, lib, m in r["apres_net"]]
    cotisations = r["cotisations"] if r["cotisations"] is not None else -r["remboursements"]
    net_avant = r["net_avant_impot"]
    if net_avant is None:
        net_avant = round(sum(l.montant for l in paie + apres) - cotisations, 2)
    # Ce qui est versé ou retenu après le total des cotisations (indemnités, frais régularisés…) compte comme
    # une ligne de paie : le net avant impôt reste lignes − cotisations
    return Bulletin(mois=r["periode"], lignes=paie + apres, cotisations=cotisations, net_avant_impot=net_avant,
                    impot=r["impot"] or 0.0, source="pdf", net_imposable=r["net_imposable"], taux_pas=r["taux_pas"],
                    net_social=r["net_social"], brut_bulletin=r["brut"], fichier=fichier, retenues_apres_net=apres,
                    taux_neutre=bool(re.search(r"\bNN\b|NON PERSO|NEUTRE", normaliser(r["pas_libelle"]))))
