"""Lecture directe d'un relevé à dates complètes (mise en page Boursorama), sans IA."""
from datetime import date

from bourso_factice import ecrire_releve_bourso

from mas.anonymisation import Coffre
from mas.ingestion import lire_pdf
from mas.orchestrateur import Orchestrateur


def test_releve_bourso_lu_directement(tmp_path):
    doc = lire_pdf(ecrire_releve_bourso(tmp_path / "bourso.pdf"))
    assert doc.structure is not None
    p = doc.structure.principal
    assert [(o.date, round(o.montant, 2)) for o in p.operations] == [
        (date(2026, 9, 2), -12.4), (date(2026, 9, 3), -64.9), (date(2026, 9, 5), 2450.0),
        (date(2026, 9, 8), -1103.25), (date(2026, 9, 15), -780.0), (date(2026, 9, 20), 35.0)]
    assert p.operations[1].libelle == "PRLV SEPA ENERGIE PLUS REF 2026-09 CONTRAT 4411"   # libellé sur 2 lignes
    assert p.operations[0].valeur == "02/09/2026"
    assert p.controle()[0] is True                       # 1 000 + crédits − débits = nouveau solde
    assert p.periodes == [(date(2026, 9, 1), date(2026, 9, 30))]
    assert "| 05/09/2026 | VIR SALAIRE ACME |  | 2450,00 | 05/09/2026 |" in doc.pages[0].texte


def test_releve_bourso_mal_lu_renvoye_a_l_ia(tmp_path):
    # un centime d'écart avec le solde imprimé : colonnes douteuses, la lecture directe s'abstient
    doc = lire_pdf(ecrire_releve_bourso(tmp_path / "ecart.pdf", solde_fin="1 524,46"))
    assert doc.structure is None


def test_releve_bourso_jusqu_au_tri(config, tmp_path):
    cfg = config.model_copy(deep=True)
    cfg.identite.noms = ["Test Exemple"]
    cfg.identite.adresses = []
    orch = Orchestrateur(cfg, Coffre(None))
    docs = orch.charger_documents(ecrire_releve_bourso(tmp_path / "bourso.pdf"))
    assert docs[0].operations is not None and len(docs[0].operations) == 6
    transactions, transferts, alertes = orch.separer_transferts(docs)
    assert sorted(round(t.montant, 2) for t in transactions) == [-1103.25, -780.0, -64.9, -12.4, 35.0, 2450.0]
    assert orch.periode_couverte(docs)[0] == 1.0
