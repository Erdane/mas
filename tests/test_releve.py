"""Lecture structurée des relevés et tri des mouvements entre comptes (sans IA)."""
import json
from datetime import date

import pytest
from bred_factice import ecrire_releve_bred

from mas.anonymisation import Coffre
from mas.ingestion import lire_pdf
from mas.orchestrateur import Orchestrateur


@pytest.fixture(scope="module")
def releve_bred(tmp_path_factory):
    return ecrire_releve_bred(tmp_path_factory.mktemp("bred") / "releve_bred.pdf")


def _orchestrateur(config, **analyse):
    cfg = config.model_copy(deep=True)
    cfg.identite.noms = ["Jean Dupont"]
    cfg.identite.adresses = []
    for cle, valeur in analyse.items():
        setattr(cfg.analyse, cle, valeur)
    return Orchestrateur(cfg, Coffre(None))


def test_releves_de_test_lus_a_l_identique(releves):
    for pdf in releves:
        doc = lire_pdf(pdf)
        verite = json.loads(pdf.with_suffix(".json").read_text(encoding="utf-8"))
        principal = doc.structure.principal
        lus = sorted((o.date.isoformat(), round(o.montant, 2)) for o in principal.operations)
        attendus = sorted((t["date"], round(t["montant"], 2)) for t in verite["transactions"])
        assert lus == attendus
        assert principal.controle()[0] is True              # solde initial + crédits − débits = final


def test_releve_bred_comptes_totaux_et_lignes(releve_bred):
    doc = lire_pdf(releve_bred)
    s = doc.structure
    assert [len(c.operations) for c in s.comptes] == [6, 1, 1]          # principal, LDD, Livret A
    assert all(c.controle()[0] is True for c in s.comptes)             # « Total des mouvements » OK
    principal = s.principal
    assert principal.periodes == [(date(2026, 4, 7), date(2026, 5, 5))]
    sepa = principal.operations[2]
    assert sepa.libelle.endswith("JEAN DUPONT BOUSFRPPXXX") and sepa.debit == 500.0   # libellé sur 2 lignes
    assert principal.operations[4].credit == 2400.0 and principal.operations[4].date == date(2026, 4, 28)
    # une ligne par opération, débit et crédit dans leurs colonnes
    assert "| 09.04 | Carte 1234567 monoprix le 08/04/26 | 45,10 |  | 09.04.26 |" in doc.pages[0].texte


def test_anonymisation_garde_dates_et_livrets(config, releve_bred):
    docs = _orchestrateur(config).charger_documents(releve_bred)
    texte = docs[0].pages[0] + docs[0].pages[1]
    assert "| 09.04 |" in texte and "TELEPHONE" not in texte           # les dates ne sont plus masquées
    assert "Livret A" in texte and "Solidaire" in texte                # ni les noms de livrets
    assert "DUPONT" not in texte.upper()                               # le titulaire, si
    ops = docs[0].operations
    assert len(ops) == 8 and sum(o.a_ton_nom for o in ops) == 1
    assert all("DUPONT" not in o.libelle.upper() for o in ops)


def test_mouvements_entre_comptes_mis_a_part(config, releve_bred):
    orch = _orchestrateur(config)
    docs = orch.charger_documents(releve_bred)
    transactions, transferts, alertes = orch.separer_transferts(docs)
    assert sorted((t["type"], t["montant"]) for t in transferts) == [
        ("a_ton_nom", -500.0), ("epargne", -300.0), ("epargne", 150.0)]
    assert sorted(t.montant for t in transactions) == [-81.3, -45.1, 2400.0]
    assert alertes == []
    assert orch.periode_couverte(docs) == (1.0, "2026-04 → 2026-05")
    assert orch.couverture_mois(docs) == {"2026-04": 0.8, "2026-05": 0.16}   # du 7 avril au 5 mai


def test_reglages_a_ton_nom_et_comptes_declares(config, releve_bred):
    orch = _orchestrateur(config, virements_a_ton_nom="depense")
    t, transferts, _ = orch.separer_transferts(orch.charger_documents(releve_bred))
    assert -500.0 in [x.montant for x in t] and {x["type"] for x in transferts} == {"epargne"}
    orch = _orchestrateur(config, virements_a_ton_nom="depense", comptes_personnels=["BOUSFRPP"])
    _, transferts, _ = orch.separer_transferts(orch.charger_documents(releve_bred))
    assert ("tes_comptes", -500.0) in [(x["type"], x["montant"]) for x in transferts]


def test_analyse_complete_du_releve_bred(config, releve_bred, monkeypatch):
    import dspy
    from faux_llm import FauxLLM

    import mas.orchestrateur as module_orchestrateur
    from mas.page import construire_page, donnees_rapport

    faux = FauxLLM()

    def configurer_faux(_config_llm):
        dspy.configure(lm=faux)
        return faux

    monkeypatch.setattr(module_orchestrateur, "configurer_lm", configurer_faux)
    orch = _orchestrateur(config)
    docs = orch.charger_documents(releve_bred)
    resultat = orch.analyser(docs)
    b = resultat.budget
    assert b["nb_mois"] == 1.0 and b["periode"] == "2026-04 → 2026-05"
    assert round(b["depenses_mensuelles"], 2) == 126.40                # carte + EDF, sans les 800 € déplacés
    assert b["revenus_mensuels"] == 2400.0
    assert b["transferts"]["epargne"] == {"sortis": 300.0, "rentres": 150.0}
    assert b["transferts"]["a_ton_nom"]["sortis"] == 500.0
    page = construire_page(donnees_rapport(b, resultat.analyse.classements, resultat.commentaire,
                                           list(resultat.analyse.alertes_extraction)))
    assert "Pas compté dans tes dépenses" in page and "vers des comptes à ton nom" in page
    assert "virements_a_ton_nom: depense" in page
    assert b["par_mois"] == {"mois": ["2026-04", "2026-05"], "partiels": ["2026-05"],
                             "lignes": [{"categorie": "energie", "montants": [81.3, 0.0]},
                                        {"categorie": "alimentation", "montants": [45.1, 0.0]}],
                             "totaux": [126.4, 0.0]}
    assert "Mois par mois" in page and "incomplet" in page
