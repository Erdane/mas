"""Petits relevés factices, une famille de mise en page chacun, pour le lecteur à colonnes déduites
(lecteur_deduit.py). Chaque ligne est décrite par ses textes et leurs positions : (texte, x, "g" ou "d"),
« d » pour un montant aligné à droite sur x. Aucune donnée réelle."""
from pathlib import Path


def ecrire(chemin: Path, lignes: list[list[tuple[str, float, str]]], pas: float = 14) -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(chemin), pagesize=A4)
    c.setFont("Helvetica", 8)
    y = 790
    for ligne in lignes:
        for texte, x, alignement in ligne:
            (c.drawRightString if alignement == "d" else c.drawString)(x, y, texte)
        y -= pas
    c.save()
    return chemin


def signe_et_soldes(chemin: Path) -> Path:
    """Une seule colonne de montants signés, dates « jj/mm/aa », soldes en tête et en fin."""
    return ecrire(chemin, [
        [("RELEVÉ DE COMPTE", 40, "g")],
        [("Date", 40, "g"), ("Libellé", 100, "g"), ("Montant", 470, "g")],
        [("Solde au 01/09/26", 100, "g"), ("800,00", 520, "d")],
        [("02/09/26", 40, "g"), ("PAIEMENT CARTE CAFE", 100, "g"), ("-4,20", 520, "d")],
        [("04/09/26", 40, "g"), ("VIREMENT RECU EMPLOYEUR", 100, "g"), ("+1 900,00", 520, "d")],
        [("11/09/26", 40, "g"), ("PRELEVEMENT INTERNET", 100, "g"), ("-29,99", 520, "d")],
        [("Solde au 30/09/26", 100, "g"), ("2 665,81", 520, "d")],
    ])


def trois_colonnes_dates_courtes(chemin: Path, faux_solde: bool = False) -> Path:
    """Débit, crédit, et solde après chaque opération ; dates « jj.mm », année tirée de la période."""
    return ecrire(chemin, [
        [("Période du 01/09/2026 au 30/09/2026", 40, "g")],
        [("Le", 40, "g"), ("Opération", 90, "g"), ("Sortie", 420, "g"), ("Entrée", 480, "g"), ("Reste", 540, "g")],
        [("03.09", 40, "g"), ("ABONNEMENT MUSIQUE", 90, "g"), ("10,99", 450, "d"), ("489,01", 570, "d")],
        [("06.09", 40, "g"), ("REMBOURSEMENT AMI", 90, "g"), ("25,00", 510, "d"), ("514,01", 570, "d")],
        [("12.09", 40, "g"), ("COURSES MARCHE", 90, "g"), ("1 032,50", 450, "d"),
         ("-518,49" if not faux_solde else "-518,50", 570, "d")],
    ])


def signe_et_solde_dates_en_lettres(chemin: Path) -> Path:
    """Montant signé avec « € », solde après chaque opération, dates « 5 sept. 2026 »."""
    return ecrire(chemin, [
        [("Transactions", 40, "g")],
        [("5", 40, "g"), ("sept.", 50, "g"), ("2026", 72, "g"), ("Carte Librairie", 120, "g"),
         ("-18,90", 430, "d"), ("€", 436, "g"), ("481,10", 520, "d"), ("€", 526, "g")],
        [("9", 40, "g"), ("sept.", 50, "g"), ("2026", 72, "g"), ("Virement de Exemple Test", 120, "g"),
         ("+300,00", 430, "d"), ("€", 436, "g"), ("781,10", 520, "d"), ("€", 526, "g")],
        [("21", 40, "g"), ("sept.", 50, "g"), ("2026", 72, "g"), ("Transport mensuel", 120, "g"),
         ("-75,00", 430, "d"), ("€", 436, "g"), ("706,10", 520, "d"), ("€", 526, "g")],
    ])


def sans_solde(chemin: Path) -> Path:
    """Deux colonnes débit / crédit, mais ni solde ni total imprimé : impossible à vérifier."""
    return ecrire(chemin, [
        [("05/09/2026", 46, "g"), ("ACHAT EN LIGNE", 95, "g"), ("05/09/2026", 375, "g"), ("42,00", 490, "d")],
        [("07/09/2026", 46, "g"), ("VIREMENT RECU", 95, "g"), ("07/09/2026", 375, "g"), ("100,00", 560, "d")],
    ])
