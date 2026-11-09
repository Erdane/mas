"""Lecture structurée des relevés et tri des mouvements entre comptes (sans IA)."""
import json
from datetime import date

import pytest
from bred_factice import ecrire_releve_bred

from mas.anonymisation import Coffre
from mas.ingestion import lire_pdf
from mas.orchestrateur import DocumentAnonymise, OperationAnonyme, Orchestrateur


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
    assert sepa.libelle.endswith("JEAN DUPONT EXMPFRPPXXX") and sepa.debit == 500.0   # libellé sur 2 lignes
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
    orch = _orchestrateur(config, virements_a_ton_nom="depense", comptes_personnels=["EXMPFRPP"])
    _, transferts, _ = orch.separer_transferts(orch.charger_documents(releve_bred))
    assert ("tes_comptes", -500.0) in [(x["type"], x["montant"]) for x in transferts]


def _releve(operations, periodes=()):
    return DocumentAnonymise("releve", [], periodes=list(periodes),
                             operations=[OperationAnonyme(d, libelle, montant, 0) for d, libelle, montant in operations])


MARS = [(date(2026, 3, 1), date(2026, 3, 31))]


def test_virement_entre_deux_banques_mis_a_part(config):
    orch = _orchestrateur(config)
    banque_a = _releve([("2026-03-10", "VIR SEPA EMIS VERS BOURSORAMA", -500.0),
                        ("2026-03-12", "CARTE MONOPRIX", -40.0)], MARS)
    # Pas de période lue sur ce relevé : il couvre de sa première à sa dernière opération
    banque_b = _releve([("2026-03-02", "PRLV FREE MOBILE", -19.99),
                        ("2026-03-12", "VIR SEPA RECU DE M J [PERSONNE_1]", 500.0),
                        ("2026-03-28", "CARTE SNCF", -60.0)])
    transactions, transferts, _ = orch.separer_transferts([banque_a, banque_b])
    assert sorted((t["type"], t["montant"]) for t in transferts) == [
        ("entre_tes_comptes", -500.0), ("entre_tes_comptes", 500.0)]
    assert sorted(t.montant for t in transactions) == [-60.0, -40.0, -19.99]


def test_pas_d_appariement_entre_deux_personnes_ni_deux_mois_d_un_meme_compte(config):
    orch = _orchestrateur(config)
    # Tu rembourses l'un, un autre te rembourse le même montant le lendemain : deux proches
    a = _releve([("2026-03-10", "VIR INST A [PERSONNE_2] RESTO", -30.0)], MARS)
    b = _releve([("2026-03-11", "VIR RECU DE [PERSONNE_3]", 30.0)], MARS)
    assert orch.separer_transferts([a, b])[1] == []
    # Deux relevés successifs du même compte : un virement envoyé fin mars, un autre reçu début avril
    mars = _releve([("2026-03-30", "VIR SEPA EMIS VERS BOURSORAMA", -200.0)], MARS)
    avril = _releve([("2026-04-02", "VIR SEPA RECU", 200.0)], [(date(2026, 4, 1), date(2026, 4, 30))])
    assert orch.separer_transferts([mars, avril])[1] == []


def test_ton_nom_ecrit_autrement_d_une_banque_a_l_autre(config):
    orch = _orchestrateur(config)
    # Virement automatique le 30 juin, reçu le 2 juillet : relevé BRED du 7 juin au 6 juillet, relevé
    # Boursorama sans période imprimée dont la première opération tombe le 2 juillet
    bred = DocumentAnonymise("bred", [], periodes=[(date(2026, 6, 7), date(2026, 7, 6))], operations=[
        OperationAnonyme("2026-06-30", "Virement automatique 1234567 [PERSONNE_2] ech", -70.0, 0, nom_partiel=True)])
    bourso = DocumentAnonymise("bourso", [], operations=[
        OperationAnonyme("2026-07-02", "VIRSEPAMR [PERSONNE_1] Ref123", 70.0, 0, nom_partiel=True),
        OperationAnonyme("2026-07-22", "CARTE22/07/26LIDL", -12.0, 0)])
    assert sorted(t["montant"] for t in orch.separer_transferts([bred, bourso])[1]) == [-70.0, 70.0]
    # Sans ton nom des deux côtés : deux personnes différentes, rien n'est apparié
    bred.operations[0].nom_partiel = bourso.operations[0].nom_partiel = False
    assert orch.separer_transferts([bred, bourso])[1] == []


def test_un_ami_ne_prend_pas_la_place_de_ton_virement(config):
    orch = _orchestrateur(config)
    bred = DocumentAnonymise("bred", [], periodes=MARS, operations=[
        OperationAnonyme("2026-03-17", "VIR INST A [PERSONNE_7] RESTO", -50.0, 0),          # un ami, la veille
        OperationAnonyme("2026-03-18", "Virement émis [PERSONNE_4]", -50.0, 0, a_ton_nom=True)])
    bourso = DocumentAnonymise("bourso", [], operations=[
        OperationAnonyme("2026-03-19", "VIRINSTMR [PERSONNE_1]", 50.0, 0, nom_partiel=True)])
    transactions, transferts, _ = orch.separer_transferts([bred, bourso])
    assert sorted((t["type"], t["montant"]) for t in transferts) == [
        ("entre_tes_comptes", -50.0), ("entre_tes_comptes", 50.0)]
    assert [t.libelle for t in transactions] == ["VIR INST A [PERSONNE_7] RESTO"]


def test_livret_apparie_dans_son_propre_releve(config):
    orch = _orchestrateur(config)
    # BRED : le livret verse 2 500 € au compte courant, qui les envoie aussitôt vers Boursorama
    bred = DocumentAnonymise("bred", [], periodes=MARS, operations=[
        OperationAnonyme("2026-03-10", "Virement 7000001", 2500.0, 0),
        OperationAnonyme("2026-03-10", "Virement SEPA émis [PERSONNE_4]", -2500.0, 0, a_ton_nom=True),
        OperationAnonyme("2026-03-10", "Virement 7000001", -2500.0, 1)])
    bourso = DocumentAnonymise("bourso", [], operations=[
        OperationAnonyme("2026-03-11", "VIRSEPAMR [PERSONNE_1]", 2500.0, 0, nom_partiel=True)])
    types = sorted((t["type"], t["montant"]) for t in orch.separer_transferts([bourso, bred])[1])
    assert types == [("entre_tes_comptes", -2500.0), ("entre_tes_comptes", 2500.0), ("epargne", 2500.0)]


def test_deux_banques_sur_les_memes_mois_ne_doublent_pas_la_periode(config):
    a = _releve([("2026-03-10", "CARTE MONOPRIX", -40.0)], MARS)
    b = _releve([("2026-03-11", "CARTE SNCF", -60.0)], MARS)
    assert Orchestrateur.periode_couverte([a, b]) == (1.0, "2026-03 → 2026-03")


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
                             "lignes": [{"categorie": "energie", "montants": [81.3, 0.0], "obligatoire": [0.0, 0.0]},
                                        {"categorie": "alimentation", "montants": [45.1, 0.0], "obligatoire": [0.0, 0.0]}],
                             "totaux": [126.4, 0.0], "revenus": [2400.0, 0.0]}
    assert "Mois par mois" in page and "incomplet" in page


def test_achat_exceptionnel_et_pret_debloque_mis_a_part(config):
    orch = _orchestrateur(config)
    releve = _releve([("2026-05-08", "VIRINST[PERSONNE_5] Virementde[PERSONNE_6]", -500.0),
                      ("2026-05-11", "VIRDeblocagePret00012345678 [PERSONNE_1]", 15000.0),
                      ("2026-05-11", "VIRSEPA[PERSONNE_5] Virementde[PERSONNE_6] Ref1", -3000.0),
                      ("2026-05-11", "VIRSEPA[PERSONNE_5] Virementde[PERSONNE_6] Ref2", -14000.0),
                      ("2026-05-20", "Prélèvement SEPA 7000002 direction generale des finances publiques", -2500.0),
                      ("2026-05-25", "Carte 7000004 boutique-informatique.com le 25/05/26", -850.0)])
    transactions, transferts, _ = orch.separer_transferts([releve])
    assert sorted(t["montant"] for t in transferts if t["type"] == "exceptionnel") == [-14000.0, -3000.0, -500.0, 15000.0]
    assert sorted(t.montant for t in transactions) == [-2500.0, -850.0]       # impôts et achat ordinaire : comptés
    assert _orchestrateur(config, achat_exceptionnel_min=0).separer_transferts([releve])[1] == []


def test_loyer_avec_ton_nom_en_reference(config):
    orch = _orchestrateur(config)
    assert orch._a_ton_nom("Virement instantané émis a1b2c3d residence les acacias loyer JEAN DUPONT") is False
    assert orch._a_ton_nom("Virement SEPA émis 7000003 JEAN DUPONT") is True
