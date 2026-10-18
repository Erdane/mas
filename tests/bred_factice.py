"""Relevé factice à la mise en page BRED : tableau sans bordures (colonnes Date, Référence, Débit,
Crédit, Valeur), libellé sur deux lignes, totaux et soldes imprimés, puis deux livrets (LDD, Livret A)
dans le même relevé. Sert à tester la lecture structurée sans données réelles."""

from pathlib import Path

COL_DATE, COL_LIBELLE, COL_DEBIT, COL_CREDIT, COL_VALEUR = 34, 80, 421, 520, 532
LIGNE = 13


def _entete_tableau(c, y):
    for texte, x in (("Date", 34), ("Référence", 174), ("Débit", 364), ("Crédit", 461), ("Valeur", 532)):
        c.drawString(x, y, texte)


def _ligne(c, y, date="", libelle="", debit="", credit="", valeur=""):
    if date:
        c.drawString(COL_DATE, y, date)
    if libelle:
        c.drawString(COL_LIBELLE, y, libelle)
    if debit:
        c.drawRightString(COL_DEBIT, y, debit)
    if credit:
        c.drawRightString(COL_CREDIT, y, credit)
    if valeur:
        c.drawString(COL_VALEUR, y, valeur)


def ecrire_releve_bred(chemin: Path) -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(chemin), pagesize=A4)
    c.setFont("Helvetica", 8)
    # ---- page 1 : compte principal, puis LDD
    c.drawString(50, 800, "Relevé de comptes")
    c.drawString(50, 788, "Date N° de compte N° de relevé")
    c.drawString(50, 776, "5 mai 2026 941.76.7595 5 1/2")
    c.drawString(330, 760, "M. JEAN DUPONT")
    y = 700
    _entete_tableau(c, y)
    lignes = [
        ("07.04", "Solde précédent", "", "1.000,00", ""),
        ("09.04", "Carte 1234567 monoprix le 08/04/26", "45,10", "", "09.04.26"),
        ("10.04", "Virement 9900089", "300,00", "", "10.04.26"),
        ("12.04", "Virement SEPA émis 9027718 12.04.26 JEAN DUPONT", "500,00", "", "12.04.26"),
        ("", "BOUSFRPPXXX", "", "", ""),                                   # suite du libellé
        ("15.04", "Prélèvement SEPA 2931880 edf clients particuliers", "81,30", "", "15.04.26"),
        ("28.04", "Virement reçu salaire acme", "", "2.400,00", "28.04.26"),
        ("30.04", "Virement 9900099", "", "150,00", "30.04.26"),
        ("", "Total des mouvements", "926,40", "2.550,00", ""),
        ("05.05", "Nouveau solde", "", "2.623,60", ""),
        ("", "Total des frais de gestion débités du 01.04 au 30.04.2026", "12,62", "", ""),
    ]
    for date, libelle, debit, credit, valeur in lignes:
        y -= LIGNE if date or libelle != "BOUSFRPPXXX" else 10
        _ligne(c, y, date, libelle, debit, credit, valeur)
    y -= 2 * LIGNE
    _entete_tableau(c, y)
    for date, libelle, debit, credit, valeur in [
        ("", "LDD Développement Durable et Solidaire", "", "", ""),
        ("27.03", "Solde précédent", "", "1.917,33", ""),
        ("10.04", "Virement 9910086", "", "300,00", "10.04.26"),
        ("", "Total des mouvements", "", "300,00", ""),
        ("05.05", "Nouveau solde", "", "2.217,33", ""),
    ]:
        y -= LIGNE
        _ligne(c, y, date, libelle, debit, credit, valeur)
    c.showPage()
    # ---- page 2 : Livret A
    c.setFont("Helvetica", 8)
    c.drawString(50, 776, "5 mai 2026 941.76.7595 5 2/2")
    y = 720
    _entete_tableau(c, y)
    for date, libelle, debit, credit, valeur in [
        ("", "Livret A", "", "", ""),
        ("01.04", "Solde précédent", "", "7.723,45", ""),
        ("29.04", "Virement 9906271", "150,00", "", "30.04.26"),
        ("", "Total des mouvements", "150,00", "", ""),
        ("05.05", "Nouveau solde", "", "7.573,45", ""),
    ]:
        y -= LIGNE
        _ligne(c, y, date, libelle, debit, credit, valeur)
    y -= 2 * LIGNE
    c.drawString(COL_LIBELLE, y, "Information préalable sur les frais à débiter le 25/05/2026")
    c.save()
    return chemin
