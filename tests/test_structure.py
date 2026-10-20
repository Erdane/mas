"""`mas structure` : le squelette d'un relevé inconnu, sans aucune donnée personnelle."""
from pathlib import Path

from mas.structure import decrire, squelette_ligne, type_de

PERSO = ["Camille", "Rousseau", "BOULANGERIE", "Lemaire", "FR76", "3000", "Bordeaux", "Voltaire", "camille.rousseau"]


def ecrire_autre_banque(chemin: Path) -> Path:
    """Mise en page inconnue de mas : une seule colonne Montant signée, dates longues, pas de Débit/Crédit."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(chemin), pagesize=A4)
    c.drawString(40, 800, "AUTRE BANQUE - Relevé de compte")
    c.drawString(40, 785, "Mme Camille Rousseau, 12 rue Voltaire, 33000 Bordeaux")
    c.drawString(40, 770, "IBAN FR76 3000 4000 5000 6000 7000 123 - camille.rousseau@example.com")
    for texte, x in (("Dateopération", 40), ("Libellé", 130), ("Date valeur", 380), ("Montant", 480)):
        c.drawString(x, 720, texte)
    lignes = [("03/09/2026", "CB BOULANGERIE LEMAIRE BORDEAUX", "04/09/2026", "-12,40"),
              ("05/09/2026", "VIR SEPA CAMILLE ROUSSEAU", "05/09/2026", "1 250,00"),
              ("09/09/2026", "PRLV SEPA ASSURANCE", "09/09/2026", "-38,15")]
    for k, (d, lib, v, m) in enumerate(lignes):
        y = 700 - 14 * k
        c.drawString(40, y, d)
        c.drawString(130, y, lib)
        c.drawString(380, y, v)
        c.drawRightString(530, y, m)
    c.drawString(130, 640, "NOUVEAUSOLDE au 30/09/2026")   # mots collés, comme dans certains PDF
    c.drawRightString(530, 640, "2 104,32")
    c.save()
    return chemin


def test_types_sans_valeurs():
    assert [type_de(m) for m in ("03/09/2026", "05.09", "-12,40", "1250,00", "42", "CB")] == \
        ["DATE_LONGUE", "DATE_COURTE", "-MONTANT", "MONTANT", "NOMBRE", "TEXTE"]
    mots = [{"text": t, "x0": x, "x1": x + 20} for t, x in (("03/09/2026", 40), ("CB", 130), ("X", 152), ("1", 500), ("250,00", 504))]
    assert squelette_ligne(mots) == "DATE_LONGUE@40 TEXTE×2@130 MONTANT@500"


def test_squelette_d_une_banque_inconnue_sans_donnees(tmp_path):
    ecrire_autre_banque(tmp_path / "releve.pdf")
    sortie = "\n".join(decrire(tmp_path))
    assert "Document 1/1 : 1 page(s), lecture directe : non reconnue (" in sortie
    assert "en-tête" in sortie and "date…@40" in sortie and "montant@480" in sortie and "libellé@130" in sortie
    assert "premières lignes d'opérations :\n      DATE_LONGUE@40 TEXTE×4@130 DATE_LONGUE@380 -MONTANT@" in sortie
    assert "mots repérés : nouveau, solde" in sortie
    for mot in PERSO:                                   # rien de personnel, sous aucune forme
        assert mot.lower() not in sortie.lower(), mot


def test_releve_deja_lu_non_decrit_sauf_tous(tmp_path):
    from bred_factice import ecrire_releve_bred
    ecrire_releve_bred(tmp_path / "bred.pdf")
    assert decrire(tmp_path) == ["Tous les documents sont lus directement : rien à décrire."]
    assert "lecture directe : reconnue, en-tête Date / Débit / Crédit" in decrire(tmp_path, tous=True)[0]
