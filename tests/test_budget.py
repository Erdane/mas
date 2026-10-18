"""Calcul du budget : mouvements entre comptes, remboursements, argent reçu, nombre de mois."""
from mas.agents.synthese import calculer_budget, resume_markdown
from mas.modeles import TransactionCategorisee as T


def _t(date, montant, categorie, libelle="x"):
    return T(date=date, libelle=libelle, montant=montant, categorie=categorie)


OPERATIONS = [
    _t("2026-04-28", 2400.0, "revenu"),
    _t("2026-04-09", -100.0, "shopping"), _t("2026-04-20", 30.0, "shopping"),        # remboursement
    _t("2026-04-12", -200.0, "virement_personnel"), _t("2026-04-15", 50.0, "virement_personnel"),
    _t("2026-04-16", -80.0, "epargne"),                                              # épargne vue par l'IA
    _t("2026-05-02", -60.0, "alimentation"),
]
TRANSFERTS = [{"type": "epargne", "montant": -300.0}, {"type": "epargne", "montant": 150.0},
              {"type": "a_ton_nom", "montant": -500.0}]


def test_transferts_hors_depenses_et_mois_des_releves():
    b = calculer_budget(OPERATIONS, [], [], TRANSFERTS, nb_mois=1.0, periode="2026-04 → 2026-05")
    assert b["depenses_mensuelles"] == 70 + 200 + 60          # shopping net 70, proches 200, courses 60
    assert b["revenus_mensuels"] == 2400 + 50                 # salaire + argent reçu d'un proche
    assert b["transferts"] == {"epargne": {"sortis": 380.0, "rentres": 150.0},
                               "a_ton_nom": {"sortis": 500.0, "rentres": 0.0}}
    assert b["periode"] == "2026-04 → 2026-05" and b["nb_mois"] == 1.0
    texte = resume_markdown(b, [])
    assert "Hors dépenses" in texte and "Comptes à ton nom (à confirmer)" in texte and "(1 mois)" in texte


def test_proches_a_part_et_mois_par_defaut():
    b = calculer_budget(OPERATIONS, [], [], proches_a_part=True)
    assert b["nb_mois"] == 2 and b["periode"] == "2026-04 → 2026-05"
    assert b["depenses_mensuelles"] == (70 + 60) / 2
    assert b["transferts"]["proches"] == {"sortis": 100.0, "rentres": 25.0}


def test_repartition_par_mois():
    b = calculer_budget(OPERATIONS, [], [], TRANSFERTS, nb_mois=1.0,
                        couverture={"2026-04": 1.0, "2026-05": 0.2})
    pm = b["par_mois"]
    assert pm["mois"] == ["2026-04", "2026-05"] and pm["partiels"] == ["2026-05"]
    # même ordre que les catégories ; remboursement déduit, argent reçu et épargne exclus
    assert pm["lignes"] == [{"categorie": "virement_personnel", "montants": [200.0, 0.0]},
                            {"categorie": "shopping", "montants": [70.0, 0.0]},
                            {"categorie": "alimentation", "montants": [0.0, 60.0]}]
    assert pm["totaux"] == [270.0, 60.0]
    assert sum(pm["totaux"]) == b["depenses_mensuelles"] * b["nb_mois"]
    texte = resume_markdown(b, [])
    assert "### Dépenses par mois et par catégorie" in texte
    assert "| Catégorie | 2026-04 | 2026-05* | Moyenne |" in texte and "mois incomplet" in texte
    assert "| **Total** | **270,00 €** | **60,00 €** | **330,00 €** |" in texte


def test_repartition_par_mois_sans_releve_structure():
    b = calculer_budget(OPERATIONS, [], [], proches_a_part=True)
    pm = b["par_mois"]
    assert pm["mois"] == ["2026-04", "2026-05"] and pm["partiels"] == []
    assert [l["categorie"] for l in pm["lignes"]] == ["shopping", "alimentation"]
    assert "mois incomplet" not in resume_markdown(b, [])
