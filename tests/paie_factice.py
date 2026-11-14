"""Une paie inventée, pour les tests : un classeur de la même forme qu'un vrai (feuilles « Brut AAAA » et « Net
AAAA », un mois par ligne), et des mots de bulletin PDF fabriqués (texte et position).

Deux ans de paie fictive : salaire de base 2 000 €, primes de 3 % et 5 %, 13e mois en juin (50 %), novembre (40 %) et
décembre (10 %), une hausse de 2 % en avril qui vaut depuis janvier (rappel de trois mois), une part variable en
avril, des frais de transport, un taux d'impôt de 5 %. Aucune valeur ne vient d'une vraie fiche de paie.
"""
from __future__ import annotations

import openpyxl

COLONNES = ["Salaire de base", "Prime d'assiduite", "Prime de poste", "Gratification fin d'année",
            "Salaire de base rappel", "Prime variable exer anter", "Frais transport", "Cotisations"]
TAUX_COTIS = 0.22


def mois_fictif(annee: int, m: int, base_avant: float = 2000.0) -> dict:
    base = round(base_avant * (1.02 if (annee, m) >= (2025, 4) else 1.0), 2)
    lignes = {"Salaire de base": base, "Prime d'assiduite": round(0.03 * base, 2), "Prime de poste": round(0.05 * base, 2),
              "Frais transport": 40.0}
    if m in (6, 11, 12):
        lignes["Gratification fin d'année"] = round({6: 0.5, 11: 0.4, 12: 0.1}[m] * base, 2)
    if (annee, m) == (2025, 4):
        lignes["Salaire de base rappel"] = round(3 * (base - base_avant), 2)
    if m == 4:
        lignes["Prime variable exer anter"] = 1500.0
    soumis = sum(v for k, v in lignes.items() if k != "Frais transport")
    cotis = round(TAUX_COTIS * soumis, 2)
    net_avant = round(sum(lignes.values()) - cotis, 2)
    impot = round(0.05 * (net_avant - 40.0), 2)
    return {"lignes": lignes, "cotis": cotis, "net_avant": net_avant, "net_apres": round(net_avant - impot, 2)}


def ecrire_classeur(chemin, annees=(2024, 2025), mois_2025: int = 12, signe_inverse: bool = False) -> None:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for annee in annees:
        brut, net = wb.create_sheet(f"Brut {annee}"), wb.create_sheet(f"Net {annee}")
        brut.append(["Mois", *COLONNES])
        net.append(["Mois", "Net avant impôts", "Impôts", "Net après impôts"])
        derniers = mois_2025 if annee == 2025 else 12
        for m in range(1, 13):
            if m > derniers:
                brut.append([m]); net.append([m])
                continue
            x = mois_fictif(annee, m)
            lignes = dict(x["lignes"])
            if signe_inverse and (annee, m) == (2025, 2):
                lignes["Frais transport"] = -lignes["Frais transport"]      # saisi à l'envers
            brut.append([m, *[lignes.get(c) for c in COLONNES[:-1]], -x["cotis"]])
            net.append([m, x["net_avant"], round(x["net_avant"] - x["net_apres"], 2), x["net_apres"]])
        net.append([])
        net.append([None, "Moyenne Impôts"])
        faits = [mois_fictif(annee, m) for m in range(1, derniers + 1)]
        net.append([None, round(sum(f["net_avant"] - f["net_apres"] for f in faits) / 12, 2)])   # divisé par 12 : faux si l'année n'est pas finie
        net.append([None, "Annuel"])
        net.append([None, annee + 1 if annee == 2024 else annee])                                   # étiquette fausse en 2024
    wb.save(chemin)


# --- mots de bulletin PDF -------------------------------------------------------------------------------------------

def mot(texte, x0, x1, top):
    return {"text": texte, "x0": x0, "x1": x1, "top": top}


def ligne(top, code, libelle, *montants):
    """montants : (texte, bord droit) ; le code à 43, le libellé à 62."""
    mots = [mot(code, 43, 57, top)] if code else []
    mots += [mot(m, 62 + 40 * i, 62 + 40 * i + 6 * len(m), top) for i, m in enumerate(libelle.split())]
    mots += [mot(t, x1 - 6 * len(t), x1, top) for t, x1 in montants]
    return mots


def page(*lignes, hauteur=842):
    return {"hauteur": hauteur, "lignes": list(lignes)}


def bulletin_recent(mois="03", annee="2026", avec_identite=False):
    """Un bulletin au format récent : brut, cotisations, total, net social, impôt (et sa régularisation), frais."""
    entete = [[mot("PERIODE:", 23, 61, 29), mot("01", 75, 85, 29), mot(mois, 90, 99, 29), mot(annee, 104, 123, 29)]]
    if avec_identite:
        entete += [[mot("M.", 330, 340, 60), mot("JEAN", 345, 370, 60), mot("DUPONT", 375, 410, 60)],
                   [mot("12", 330, 340, 72), mot("RUE", 345, 365, 72), mot("DES", 370, 385, 72), mot("LILAS", 390, 420, 72)],
                   [mot("NIR", 23, 40, 90), mot("1", 60, 64, 90), mot("85", 68, 78, 90), mot("09", 82, 92, 90), mot("75", 96, 106, 90),
                    mot("118", 110, 125, 90), mot("082", 130, 145, 90), mot("58", 150, 160, 90)]]
    return [page(
        *entete,
        [mot("POUR", 23, 50, 200), mot("EN", 55, 65, 200), mot("SAVOIR", 70, 100, 200), mot("PLUS", 105, 125, 200),
         mot("21,67", 466, 486, 200), mot("158,69", 535, 559, 200)],                  # un encart, pas une ligne de paie
        ligne(307, "001", "SALAIRE DE BASE", ("2000,00", 503)),
        ligne(315, "34C", "PRIME D'ASSIDUITE", ("60,00", 503)),
        ligne(324, "71F", "CET PRIME", ("60,00", 435)),
        ligne(375, "MBR", "MONTANT BRUT", ("2000,00", 503)),
        ligne(418, "870", "COT VIEILLESSE", ("2000,00", 327), ("10,00", 368), ("200,00", 435), ("400,00", 571)),
        ligne(426, "8AO", "RET SUP T2", ("-100,00", 327), ("0,70", 368), ("1,50", 503), ("-3,00", 571)),
        ligne(435, "", "TOTAL COTISATIONS ET CONTRIBUTIONS", ("440,00", 435), ("1,50", 503), ("900,00", 571)),
        ligne(450, "MNS", "MONTANT NET SOCIAL", ("1561,50", 503)),
        ligne(460, "RNS", "REGUL NET SOCIAL JANVIER", ("50,00", 435)),
        ligne(470, "P60", "MONTANT PAS", ("1600,00", 327), ("5,00", 368), ("80,00", 435)),
        ligne(478, "P80", "MT REGUL PAS FEVRIER", ("10,00", 327), ("5,00", 368), ("0,50", 435)),
        ligne(486, "BEB", "FRAIS TRANSPORT MOIS ANTER", ("20,00", 435)),
        [mot("1541,50", 446, 485, 815), mot("1461,00", 539, 571, 815)],
    )]
