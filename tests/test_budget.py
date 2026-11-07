"""Calcul du budget : mouvements entre comptes, remboursements, argent reçu, nombre de mois."""
from mas.agents.synthese import calculer_budget, proches_par_personne, resume_markdown, solder_proches
from mas.modeles import TransactionCategorisee as T
from mas.recurrence import reperer_loyers


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
    # proches : 200 envoyés puis 50 rendus par la même personne → 150 de dépense, rien en revenu
    assert b["depenses_mensuelles"] == 70 + 150 + 60          # shopping net 70, proches 150, courses 60
    assert b["revenus_mensuels"] == 2400
    assert b["proches"] == {"envoye": 200.0, "recu": 50.0, "rembourse": 50.0, "depense": 150.0, "revenu": 0.0}
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
    assert pm["lignes"] == [{"categorie": "virement_personnel", "montants": [150.0, 0.0]},
                            {"categorie": "shopping", "montants": [70.0, 0.0]},
                            {"categorie": "alimentation", "montants": [0.0, 60.0]}]
    assert pm["totaux"] == [220.0, 60.0]
    assert sum(pm["totaux"]) == b["depenses_mensuelles"] * b["nb_mois"]
    texte = resume_markdown(b, [])
    assert "### Dépenses par mois et par catégorie" in texte
    assert "| Catégorie | 2026-04 | 2026-05* | Moyenne |" in texte and "mois incomplet" in texte
    assert "| **Total** | **220,00 €** | **60,00 €** | **280,00 €** |" in texte


def test_repartition_par_mois_sans_releve_structure():
    b = calculer_budget(OPERATIONS, [], [], proches_a_part=True)
    pm = b["par_mois"]
    assert pm["mois"] == ["2026-04", "2026-05"] and pm["partiels"] == []
    assert [l["categorie"] for l in pm["lignes"]] == ["shopping", "alimentation"]
    assert "mois incomplet" not in resume_markdown(b, [])


def test_remboursements_entre_proches():
    ops = [
        _t("2026-04-02", -60.0, "virement_personnel", "VIR INST A [PERSONNE_2] RESTO"),
        _t("2026-04-20", 80.0, "virement_personnel", "VIR SEPA RECU DE [PERSONNE_2] REMBOURSEMENT"),  # 60 rendus + 20 donnés
        _t("2026-04-05", 100.0, "virement_personnel", "VIR RECU DE [PERSONNE_3] AVANCE"),             # avance d'un proche…
        _t("2026-05-03", -100.0, "virement_personnel", "VIR INST A [PERSONNE_3]"),                     # … rendue le mois suivant
        _t("2026-05-10", -40.0, "virement_personnel", "VIR INST A [PERSONNE_4] CADEAU"),
        _t("2026-05-12", 40.0, "virement_personnel", "VIR RECU DE [PERSONNE_5]"),  # autre personne : pas un remboursement
    ]
    totaux, par_mois = solder_proches(ops)
    assert totaux == {"envoye": 200.0, "recu": 220.0, "rembourse": 160.0, "depense": 40.0, "revenu": 60.0}
    assert dict(par_mois) == {"2026-04": 0.0, "2026-05": 40.0}   # 60 envoyés puis rendus le même mois

    b = calculer_budget(ops, [], [], nb_mois=2.0)
    assert b["depenses_mensuelles"] == 20.0 and b["revenus_mensuels"] == 0.0      # reçu en plus : pas un revenu
    assert calculer_budget(ops, [], [], nb_mois=2.0, recus_de_proches="revenu")["revenus_mensuels"] == 30.0
    texte = resume_markdown(b, [])
    assert "### Virements avec des proches" in texte and "| 100,00 € | 110,00 € | 80,00 € | 20,00 € | 30,00 € |" in texte

    # Personne par personne : la somme retombe sur le total, la plus grosse dépense d'abord
    detail = {p["personne"]: p for p in proches_par_personne(ops)}
    assert list(detail) == ["PERSONNE_4", "PERSONNE_3", "PERSONNE_2", "PERSONNE_5"]   # à égalité : le plus envoyé
    assert sum(p["depense"] for p in detail.values()) == totaux["depense"]
    assert {k: detail["PERSONNE_2"][k] for k in ("virements", "envoye", "recu", "depense", "revenu", "nature")} == {
        "virements": 2, "envoye": 60.0, "recu": 80.0, "depense": 0.0, "revenu": 20.0, "nature": "allers_retours"}
    assert detail["PERSONNE_4"]["nature"] == "ponctuel" and detail["PERSONNE_5"]["nature"] == "recus"
    assert detail["PERSONNE_4"]["plus_gros"] == {"date": "2026-05-10", "montant": 40.0}
    assert [o["date"] for o in detail["PERSONNE_3"]["operations"]] == ["2026-04-05", "2026-05-03"]
    assert "#### Par personne (total sur 2 mois)" in texte
    assert "| [PERSONNE_4] | 1 | 40,00 € | 0,00 € | 40,00 € | 40,00 € le 2026-05-10 | Ponctuel" in texte


def test_proches_reguliers_et_gros_virement_ponctuel():
    reguliers = [_t(f"2026-0{m}-15", -50.0, "virement_personnel", "VIR INST A [PERSONNE_8]") for m in range(1, 7)]
    gros = [_t("2026-05-20", -9000.0, "virement_personnel", "VIR SEPA EMIS VERS [PERSONNE_9]")]
    detail = proches_par_personne(reguliers + gros)
    assert [(p["personne"], p["nature"]) for p in detail] == [("PERSONNE_9", "ponctuel"), ("PERSONNE_8", "regulier")]
    b = calculer_budget(reguliers + gros, [], [], nb_mois=6.0, proches_a_part=True)
    assert "| [PERSONNE_9] | 1 | 9 000,00 € | 0,00 € | — |" in resume_markdown(b, [])   # mis à part


def test_loyer_sans_libelle_repere_par_sa_regularite():
    loyer = [_t(f"2026-0{m}-03", -850.0, "virement_personnel", "VIR SEPA [PERSONNE_7]") for m in range(1, 7)]
    autres = [
        *[_t(f"2026-0{m}-15", -320.0 - 60 * m, "virement_personnel", "VIR INST A [PERSONNE_8]") for m in range(1, 7)],  # variable
        *[_t(f"2026-0{m}-20", -50.0, "virement_personnel", "VIR INST A [PERSONNE_9]") for m in range(1, 7)],  # trop petit
        _t("2026-02-10", 120.0, "virement_personnel", "VIR RECU DE [PERSONNE_7] CAUTION"),  # crédit : reste un virement
    ]
    transactions, loyers = reperer_loyers(loyer + autres, montant_min=300.0)
    assert loyers == [{"beneficiaire": "PERSONNE_7", "montant_mensuel": 850.0, "mois": 6}]
    categories = {(t.libelle, t.montant): t.categorie for t in transactions}
    assert categories[("VIR SEPA [PERSONNE_7]", -850.0)] == "logement"
    assert categories[("VIR RECU DE [PERSONNE_7] CAUTION", 120.0)] == "virement_personnel"
    assert {t.categorie for t in transactions if "PERSONNE_8" in t.libelle or "PERSONNE_9" in t.libelle} == {"virement_personnel"}

    # Deux mois seulement : pas assez pour conclure
    assert reperer_loyers(loyer[:2], montant_min=300.0)[1] == []
    texte = resume_markdown(calculer_budget(transactions, [], [], nb_mois=6.0, loyers=loyers), [])
    assert "**Loyer probable :** 850,00 € par mois versés à [PERSONNE_7] pendant 6 mois" in texte


def test_a_verifier():
    from mas.agents.synthese import a_verifier

    ops = [_t("2026-04-14", -250.0, "autre", "Carte 1000001 boutique inconnue le 13/04/26"),
           _t("2026-01-19", -160.0, "shopping", "Carte 1000002 [PERSONNE_5] le 19/01/26"),
           _t("2026-07-12", -600.0, "virement_personnel", "Virement SEPA émis 1000003 [PERSONNE_3]"),
           _t("2026-02-01", -45.0, "autre", "Carte 1000004"),                         # trop petit
           _t("2026-03-01", -400.0, "virement_personnel", "VIR INST A [PERSONNE_2]")]   # sous 500 €
    transferts = [{"type": "exceptionnel", "date": "2026-05-11", "libelle": "VIRSEPA[PERSONNE_4]", "montant": -14000.0},
                  {"type": "exceptionnel", "date": "2026-05-11", "libelle": "VIRDeblocagePret", "montant": 15000.0},
                  {"type": "epargne", "date": "2026-05-12", "libelle": "VIR LIVRET A", "montant": -5000.0}]
    lignes = a_verifier(ops, transferts)
    assert [l["montant"] for l in lignes] == [15000.0, -14000.0, -600.0, -250.0, -160.0]
    assert "Prêt débloqué" in lignes[0]["raison"] and "Commerçant inconnu" in lignes[3]["raison"]
    assert "nom masqué" in lignes[4]["raison"]
    texte = resume_markdown(calculer_budget(ops, [], [], transferts, nb_mois=6.0), [])
    assert "### À vérifier" in texte and "Gros virement à un particulier" in texte


def test_revenus_de_chaque_mois_pour_l_ecart_de_la_page():
    ops = [T(date="2026-01-28", libelle="SALAIRE", montant=2500, categorie="revenu"),
           T(date="2026-01-05", libelle="CB MARCHE", montant=-40, categorie="alimentation"),
           T(date="2026-02-27", libelle="SALAIRE", montant=2600, categorie="revenu"),
           T(date="2026-02-03", libelle="CB MARCHE", montant=-60, categorie="alimentation")]
    par_mois = calculer_budget(ops, [], [])["par_mois"]
    assert par_mois["mois"] == ["2026-01", "2026-02"]
    assert par_mois["revenus"] == [2500.0, 2600.0] and par_mois["totaux"] == [40.0, 60.0]
    assert "revenus" not in resume_markdown(calculer_budget(ops, [], []), [])   # rien de plus pour l'IA
