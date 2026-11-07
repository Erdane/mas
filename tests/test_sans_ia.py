"""`mas analyser --no-ai` : règles de catégorisation, aucun appel à l'IA, rapport daté, ouverture."""
from datetime import datetime

import dspy
import pytest
import yaml
from typer.testing import CliRunner

from mas import cli
from mas.anonymisation import Coffre
from mas.cli import app, chemin_rapport, ouvrir_dans_le_navigateur
from mas.modeles import Transaction, TransactionCategorisee
from mas.orchestrateur import Orchestrateur
from mas.sans_ia import AnalyseSansIA, _revenus_reguliers, categorie_du_libelle, commercants_a_classer, constats


@pytest.mark.parametrize("libelle, montant, attendu", [
    ("CB CARREFOUR MARKET 12/03", -54.2, "alimentation"),
    ("LIDL1234 LYON", -20.0, "alimentation"),
    ("CARTE02/05/26NETFLIX", -13.49, "abonnement"),
    ("PRLV SEPA EDF CLIENTS PARTICULIERS", -80.0, "energie"),
    ("PRLV SEPA TOTALENERGIES", -80.0, "energie"),
    ("CB TOTALENERGIES RELAIS", -60.0, "transport"),
    ("CB UBER EATS", -18.0, "restauration"),
    ("CB UBER TRIP", -12.0, "transport"),
    ("PRLV CARREFOUR BANQUE", -90.0, "credit"),
    ("ECHEANCE PRET IMMOBILIER", -900.0, "logement"),
    ("ECHEANCE PRET AUTO", -200.0, "credit"),
    ("VIR ASSURANCE VIE", -100.0, "epargne"),
    ("PRLV ASSURANCE HABITATION", -30.0, "assurance"),
    ("VIR SEPA PERMANENT M [PERSONNE_2] LOYER", -700.0, "logement"),
    ("BOULANGERIE DU COIN", -4.0, "alimentation"),
    ("BOULANGER ELECTROMENAGER", -300.0, "shopping"),
    ("CB PRET A MANGER", -9.0, "restauration"),
    ("CARTE INTERMARCHE SUPER", -30.0, "alimentation"),
    ("CB BRICOMARCHE", -20.0, "shopping"),
    ("VIR ACTION LOGEMENT", -300.0, "logement"),
    ("RETRAIT DAB 12/03", -40.0, "retrait"),
    ("VIR CAISSE RETRAITE", 1200.0, "revenu"),
    ("VIR CAF", 200.0, "revenu"),
    ("CB CAF DE LA GARE", -3.5, "autre"),       # au débit, CAF ne veut pas dire allocations
    ("VIR CREDIT AGRICOLE", -100.0, "autre"),   # le nom d'une banque, pas un crédit
    ("CB COMMERCE INCONNU", -10.0, "autre"),
    ("VIR SEPA [PERSONNE_2]", -50.0, "virement_personnel"),
])
def test_regles(libelle, montant, attendu):
    assert categorie_du_libelle(libelle, montant) == attendu


def test_le_vrai_nom_sert_au_commercant_masque_pas_au_virement():
    assert categorie_du_libelle("CARTE 12/03 [PERSONNE_4]", -30.0, "CARTE 12/03 Leclerc") == "alimentation"
    assert categorie_du_libelle("VIR SEPA [PERSONNE_2]", -50.0, "VIR SEPA M Leclerc") == "virement_personnel"


def _op(jour, libelle, montant, categorie="autre"):
    return TransactionCategorisee(date=jour, libelle=libelle, montant=montant, categorie=categorie)


def test_un_gros_credit_regulier_est_un_revenu():
    operations = [
        _op("2026-01-28", "VIR SOCIETE EXEMPLE", 2500.0),
        _op("2026-02-27", "VIR SOCIETE EXEMPLE", 2500.0),
        _op("2026-02-10", "VIR REMBOURSEMENT UNIQUE", 800.0),           # une seule fois
        _op("2026-01-05", "VIR PETIT", 50.0), _op("2026-02-05", "VIR PETIT", 50.0),    # trop petit
        _op("2026-01-06", "VIR [PERSONNE_1]", 400.0, "virement_personnel"),
        _op("2026-02-06", "VIR [PERSONNE_1]", 400.0, "virement_personnel"),            # un proche
    ]
    assert [t.categorie for t in _revenus_reguliers(operations)] == [
        "revenu", "revenu", "autre", "autre", "autre", "virement_personnel", "virement_personnel"]


def test_ce_que_tu_sais_d_un_commercant_l_emporte_sur_les_mots_cles():
    operations = [Transaction(date="2026-01-03", libelle="VIR PLACEMENT EXEMPLE", montant=-200.0),
                  Transaction(date="2026-01-04", libelle="CB CARREFOUR", montant=-30.0)]
    analyse = AnalyseSansIA(categories={"Placement Exemple": "epargne"}).analyser_transactions(operations)
    assert [t.categorie for t in analyse.transactions] == ["epargne", "alimentation"]


class LMInterdit(dspy.LM):
    def __init__(self):
        super().__init__("interdit/aucun-appel")

    def __call__(self, *args, **kwargs):
        raise AssertionError("--no-ai a appelé l'IA")


def test_aucun_appel_a_l_ia(config, releves, tmp_path):
    orchestrateur = Orchestrateur(config, coffre=Coffre(tmp_path / "coffre.bin"))
    docs = orchestrateur.charger_documents(releves[0])
    with dspy.context(lm=LMInterdit()):
        resultat = orchestrateur.analyser_sans_ia(docs)
    assert resultat.analyse.transactions
    assert resultat.budget["revenus_mensuels"] > 0
    assert "Synthèse indisponible" not in resultat.commentaire      # l'IA aurait échoué ici
    assert "rentrent" in resultat.commentaire


def test_constats_signalent_ce_qui_reste_a_classer():
    budget = {"revenus_mensuels": 2000.0, "depenses_mensuelles": 2100.0, "total_obligatoire": 900.0,
              "reste_apres_obligatoire": 1100.0,
              "par_categorie": {"autre": 525.0, "logement": 800.0, "alimentation": 400.0}}
    texte = constats(budget)
    assert "il manque **100,00 €**" in texte.replace("\u202f", " ")
    assert "25 % des dépenses" in texte
    assert "Logement" in texte


def test_commercants_a_classer_du_plus_lourd_au_plus_leger():
    operations = [
        _op("2026-01-03", "CARTE 03/01 PETIT COMMERCE", -10.0),
        _op("2026-02-03", "CARTE 03/02 PETIT COMMERCE", -15.0),
        _op("2026-01-09", "CARTE 09/01 [PERSONNE_4]", -60.0),
        _op("2026-01-10", "CB CARREFOUR", -80.0, "alimentation"),      # déjà classé
        _op("2026-01-11", "AVOIR INCONNU", 500.0),                     # un crédit n'est pas un commerçant à classer
    ]
    assert commercants_a_classer(operations) == [("CARTE 09/01 [PERSONNE_4]", 60.0, 1),
                                                 ("CARTE 03/01 PETIT COMMERCE", 25.0, 2)]
    texte = constats({"revenus_mensuels": 0.0, "depenses_mensuelles": 85.0, "total_obligatoire": 0.0,
                      "reste_apres_obligatoire": 0.0, "par_categorie": {"autre": 85.0}},
                     commercants_a_classer(operations))
    assert "- CARTE 09/01 [PERSONNE_4] : 60,00 € en 1 opération\n" in texte.replace("\u202f", " ")
    assert "25,00 € en 2 opérations" in texte.replace("\u202f", " ")


def test_chemin_du_rapport_jamais_ecrase(tmp_path):
    quand = datetime(2026, 11, 1, 14, 30, 5)
    premier = chemin_rapport(tmp_path, quand=quand)
    assert premier.name == "rapport_2026-11-01_1430.md"
    assert chemin_rapport(tmp_path, sans_ia=True, quand=quand).name == "rapport_2026-11-01_1430_no-ai.md"
    premier.write_text("déjà là")
    assert chemin_rapport(tmp_path, quand=quand).name == "rapport_2026-11-01_143005.md"


def test_ouverture_sous_wsl(monkeypatch, tmp_path):
    appels = []

    class Reponse:
        stdout = "C:\\rapports\\rapport.html\n"

    monkeypatch.setattr("shutil.which", lambda nom: f"/bin/{nom}")
    monkeypatch.setattr("subprocess.run", lambda commande, **_: appels.append(commande) or Reponse())
    ouvrir_dans_le_navigateur(tmp_path / "rapport.html")
    assert appels[0][:2] == ["wslpath", "-w"]
    assert appels[1] == ["explorer.exe", "C:\\rapports\\rapport.html"]


def test_ouverture_hors_wsl(monkeypatch, tmp_path):
    ouverts = []
    monkeypatch.setattr("shutil.which", lambda nom: None)
    monkeypatch.setattr("webbrowser.open", ouverts.append)
    ouvrir_dans_le_navigateur(tmp_path / "rapport.html")
    assert ouverts == [(tmp_path / "rapport.html").resolve().as_uri()]


@pytest.fixture
def config_essai(config, tmp_path, monkeypatch):
    donnees = config.model_dump()
    donnees["coffre"]["chemin"] = str(tmp_path / "coffre.bin")
    chemin = tmp_path / "config.yaml"
    chemin.write_text(yaml.safe_dump(donnees, allow_unicode=True), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return chemin


def test_commande_no_ai(config_essai, releves, tmp_path, monkeypatch):
    ouverts = []
    monkeypatch.setattr(cli, "ouvrir_dans_le_navigateur", ouverts.append)
    resultat = CliRunner().invoke(app, ["analyser", str(releves[0]), "--no-ai", "-c", str(config_essai)])
    assert resultat.exit_code == 0, resultat.output
    pages = sorted((tmp_path / "rapports").glob("rapport_*_no-ai.html"))
    assert len(pages) == 1
    assert (tmp_path / "rapports" / f"{pages[0].stem}_anonyme.html").exists()
    assert [p.name for p in ouverts] == [pages[0].name]
    assert "Analyse sans IA" in pages[0].read_text(encoding="utf-8")


def test_commande_no_open(config_essai, releves, monkeypatch):
    ouverts = []
    monkeypatch.setattr(cli, "ouvrir_dans_le_navigateur", ouverts.append)
    resultat = CliRunner().invoke(app, ["analyser", str(releves[0]), "--no-ai", "--no-open", "-c", str(config_essai)])
    assert resultat.exit_code == 0, resultat.output
    assert ouverts == []
