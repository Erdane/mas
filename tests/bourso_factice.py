"""Relevé factice à la mise en page Boursorama, reconstruite d'après le squelette de `mas structure`
(positions seulement, aucune donnée réelle) : encart d'identification du compte (date, RIB en 4 blocs,
devise), puis opérations à dates complètes « 05/09/2026 » : libellé (parfois sur deux lignes), date de
valeur, montant aligné à droite dans la colonne Débit ou Crédit. Pas d'en-tête « Date … Débit … Crédit »
sur une seule ligne, et « SOLDEAU » / « NOUVEAUSOLDEAU » collés, comme dans le vrai PDF."""

from pathlib import Path

X_DATE, X_LIBELLE, X_SUITE, X_VALEUR, X_SOLDE = 46, 95, 112, 375, 327
BORD_DEBIT, BORD_CREDIT = 490, 560
LIGNE = 13

OPERATIONS = [   # date, libellé, suite du libellé, valeur, débit, crédit
    [("02/09/2026", "CARTE 01/09 BOULANGERIE DU PORT", "", "02/09/2026", "12,40", ""),
     ("03/09/2026", "PRLV SEPA ENERGIE PLUS", "REF 2026-09 CONTRAT 4411", "03/09/2026", "64,90", ""),
     ("05/09/2026", "VIR SALAIRE ACME", "", "05/09/2026", "", "2 450,00"),
     ("08/09/2026", "CARTE 07/09 SUPERMARCHE CENTRE", "", "08/09/2026", "1 103,25", "")],
    [("15/09/2026", "VIR INSTANTANE LOYER", "", "15/09/2026", "780,00", ""),
     ("20/09/2026", "REMBOURSEMENT MUTUELLE", "", "20/09/2026", "", "35,00")],
]
SOLDE_DEBUT = "1 000,00"
SOLDE_FIN = "1 524,45"          # 1 000 − 12,40 − 64,90 + 2 450 − 1 103,25 − 780 + 35


def ecrire_releve_bourso(chemin: Path, solde_fin: str = SOLDE_FIN) -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(chemin), pagesize=A4)
    for numero, operations in enumerate(OPERATIONS):
        c.setFont("Helvetica", 8)
        y = 780
        if numero == 0:
            c.drawString(X_DATE, 800, "Relevé de compte")
            for texte, x in (("Date", 46), ("Référence", 94), ("Devise", 262), ("Intitulé", 293),
                             ("Montantautorisé", 411), ("Période", 472)):
                c.drawString(x, 560, texte)
            for texte, x in (("30/09/2026", 46), ("30004", 97), ("01234", 130), ("00012345678", 166), ("12", 236),
                             ("€", 266), ("COMPTE COURANT", 295), ("01/09/2026", 360), ("M. TEST EXEMPLE", 426)):
                c.drawString(x, 545, texte)
            y = 500
        c.drawString(X_DATE, y, "Date")
        for texte, x in (("Opérations", 95), ("Valeur", 381), ("Mouvements", 442)):
            c.drawString(x, y - 12, texte)
        y -= 30
        if numero == 0:
            c.drawString(X_SOLDE, y, "SOLDEAU")
            c.drawString(X_VALEUR + 1, y, "01/09/2026")
            c.drawRightString(BORD_CREDIT, y, SOLDE_DEBUT)
            y -= LIGNE
        for date, libelle, suite, valeur, debit, credit in operations:
            c.drawString(X_DATE, y, date)
            c.drawString(X_LIBELLE, y, libelle)
            c.drawString(X_VALEUR, y, valeur)
            if debit:
                c.drawRightString(BORD_DEBIT, y, debit)
            if credit:
                c.drawRightString(BORD_CREDIT, y, credit)
            if suite:
                y -= 10
                c.drawString(X_SUITE, y, suite)
            y -= LIGNE
        if numero == len(OPERATIONS) - 1:
            c.drawString(X_LIBELLE, y, "Total des opérations")
            c.drawRightString(BORD_DEBIT, y, "1 960,55")
            c.drawRightString(BORD_CREDIT, y, "2 485,00")
            y -= LIGNE
            c.drawString(X_SOLDE - 30, y, "NOUVEAUSOLDEAU")
            c.drawString(X_VALEUR + 1, y, "30/09/2026")
            c.drawRightString(BORD_CREDIT, y, solde_fin)
        else:
            c.drawString(X_LIBELLE, y, "Totalpage")
        c.showPage()
    c.save()
    return chemin
