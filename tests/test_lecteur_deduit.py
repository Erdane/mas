"""Lecture directe des mises en page inconnues : colonnes déduites, hypothèses vérifiées au centime."""
from datetime import date

import releves_factices as rf
from bourso_factice import ecrire_releve_bourso

from mas.anonymisation import Coffre
from mas.ingestion import lire_pdf
from mas.lecteur_deduit import date_en_tete, montants_finaux
from mas.orchestrateur import Orchestrateur, lectures_markdown
from mas.page import construire_page, donnees_rapport


def mots(*textes_x):
    return [{"text": t, "x0": x, "x1": x + 6 * len(t)} for t, x in textes_x]


def test_dates_en_tete_de_ligne():
    ref = date(2026, 9, 30)
    assert date_en_tete(mots(("05/09/2026", 40)), None)[0] == date(2026, 9, 5)
    assert date_en_tete(mots(("05/09/26", 40)), None)[0] == date(2026, 9, 5)
    assert date_en_tete(mots(("05.09", 40)), ref)[0] == date(2026, 9, 5)
    assert date_en_tete(mots(("5", 40), ("sept.", 50), ("2026", 80)), None)[:2] == (date(2026, 9, 5), 3)
    assert date_en_tete(mots(("12", 40), ("déc", 55)), ref)[0] == date(2025, 12, 12)   # année la plus proche
    assert date_en_tete(mots(("CARTE", 40)), ref) is None


def test_montants_en_fin_de_ligne():
    ligne = [{"text": t, "x0": x0, "x1": x1} for t, x0, x1 in [
        ("CB", 40, 50), ("12,50", 60, 80), ("USD", 82, 95), ("05/09", 300, 320), ("1", 440, 444), ("234,56", 446, 470)]]
    m = montants_finaux(ligne)
    assert [(x.valeur, x.signe) for x in m] == [(1234.56, None)]          # « 12,50 USD » reste dans le libellé
    signe = [{"text": t, "x0": x0, "x1": x1} for t, x0, x1 in [("-18,90", 400, 430), ("€", 432, 438)]]
    assert montants_finaux(signe)[0].signee == -18.9
    final = [{"text": "12,40-", "x0": 400, "x1": 430}]
    assert montants_finaux(final)[0].signee == -12.4


def _lu(chemin):
    doc = lire_pdf(chemin)
    return doc, doc.structure


def test_une_colonne_signee_avec_soldes(tmp_path):
    doc, s = _lu(rf.signe_et_soldes(tmp_path / "a.pdf"))
    assert s is not None and s.lecture == "colonnes déduites (une colonne de montants signés)"
    p = s.principal
    assert [round(o.montant, 2) for o in p.operations] == [-4.2, 1900.0, -29.99]
    assert p.controle()[0] is True and p.periodes == [(date(2026, 9, 1), date(2026, 9, 30))]


def test_debit_credit_et_solde_courant_dates_courtes(tmp_path):
    doc, s = _lu(rf.trois_colonnes_dates_courtes(tmp_path / "b.pdf"))
    assert s is not None and s.lecture == "colonnes déduites (débit, crédit, solde après chaque opération)"
    p = s.principal
    assert [(o.date, round(o.montant, 2)) for o in p.operations] == [
        (date(2026, 9, 3), -10.99), (date(2026, 9, 6), 25.0), (date(2026, 9, 12), -1032.5)]
    assert p.solde_debut[1] == 500.0 and p.solde_fin[1] == -518.49


def test_solde_courant_faux_renvoye_a_l_ia(tmp_path):
    doc, s = _lu(rf.trois_colonnes_dates_courtes(tmp_path / "c.pdf", faux_solde=True))
    assert s is None and "solde affiché après chaque opération" in doc.raison


def test_montant_signe_solde_courant_dates_en_lettres(tmp_path):
    doc, s = _lu(rf.signe_et_solde_dates_en_lettres(tmp_path / "d.pdf"))
    assert s is not None and s.lecture == "colonnes déduites (montants signés, solde après chaque opération)"
    p = s.principal
    assert [(o.date, o.libelle, round(o.montant, 2)) for o in p.operations] == [
        (date(2026, 9, 5), "Carte Librairie", -18.9), (date(2026, 9, 9), "Virement de Exemple Test", 300.0),
        (date(2026, 9, 21), "Transport mensuel", -75.0)]


def test_sans_solde_ni_total_l_ia_prend_le_relais_et_dit_pourquoi(tmp_path):
    doc, s = _lu(rf.sans_solde(tmp_path / "e.pdf"))
    assert s is None and doc.raison == "aucun solde ni total imprimé pour vérifier la lecture"


def test_bourso_lu_par_le_lecteur_deduit(tmp_path):
    doc, s = _lu(ecrire_releve_bourso(tmp_path / "f.pdf"))
    assert s.lecture == "colonnes déduites (deux colonnes, débit puis crédit)"
    assert s.principal.operations[0].libelle == "CARTE 01/09 BOULANGERIE DU PORT"   # la date du libellé reste


def test_l_utilisateur_voit_comment_chaque_releve_est_lu(config, tmp_path):
    ecrire_releve_bourso(tmp_path / "1.pdf")
    rf.sans_solde(tmp_path / "2.pdf")
    cfg = config.model_copy(deep=True)
    cfg.identite.noms, cfg.identite.adresses = ["Test Exemple"], []
    docs = Orchestrateur(cfg, Coffre(None)).charger_documents(tmp_path)
    lectures = Orchestrateur.lectures(docs)
    assert [(l["directe"], l["ok"]) for l in lectures] == [(True, True), (False, None)]
    assert lectures[0]["lecture"] == "directe : colonnes déduites (deux colonnes, débit puis crédit)"
    assert lectures[0]["periode"] == "du 01/09/2026 au 30/09/2026" and lectures[0]["controle"] == "juste au centime"
    assert lectures[1]["lecture"] == ("par l'IA : mise en page non reconnue "
                                      "(aucun solde ni total imprimé pour vérifier la lecture)")
    section = lectures_markdown(lectures)
    assert "## Comment tes relevés ont été lus" in section and "`mas structure`" in section
    budget = {"periode": "2026-09 → 2026-09", "nb_mois": 1, "par_nature": {}}
    page = construire_page(donnees_rapport(budget, [], "Synthèse.", lectures=lectures))
    assert "Comment tes relevés ont été lus" in page and "juste au centime" in page and "mas structure" in page
