"""Le budget d'aujourd'hui : charges fixes à leur montant actuel, le reste sur les douze derniers mois (sans IA).
Données inventées."""
import pytest

from mas.agents.synthese import calculer_budget, resume_markdown
from mas.aujourdhui import a_montrer, budget_aujourdhui
from mas.modeles import Classement, GroupeRecurrent, TransactionCategorisee
from mas.page import construire_page, donnees_rapport

MOIS = [f"{a}-{m:02d}" for a, m in [(2025, 9), (2025, 10), (2025, 11), (2025, 12)] + [(2026, m) for m in range(1, 11)]]


def _t(date, libelle, montant, categorie):
    return TransactionCategorisee(date=date, libelle=libelle, montant=montant, categorie=categorie)


def _groupe(cle, libelle, categorie, periodicite, paiements, variable=False):
    montants = [m for _, m in paiements]
    jours = {"mensuelle": 30.44, "annuelle": 365.25}[periodicite]
    moyenne = sum(montants) / len(montants)
    return GroupeRecurrent(cle=cle, libelle=libelle, categorie=categorie, periodicite=periodicite,
                           occurrences=len(paiements), montant_moyen=round(moyenne, 2),
                           montant_mensuel=round(moyenne * 30.44 / jours, 2), montant_variable=variable,
                           dates=[d for d, _ in paiements])


def _scenario(loyers=None, avec_changements=True, variable=False):
    """14 mois : salaire, loyer, courses ; avec_changements : un crédit auto depuis juin 2026, un forfait mobile
    arrêté en février 2026, une assurance annuelle et un solde d'impôt en quatre fois."""
    loyers = loyers or {m: 800.0 for m in MOIS}
    transactions, groupes, classements = [], [], []
    for m in MOIS:
        transactions.append(_t(f"{m}-28", "VIR SALAIRE EMPLOYEUR", 2500.0, "revenu"))
        transactions.append(_t(f"{m}-15", "CARTE MARCHE DU QUARTIER", -400.0, "alimentation"))
    paiements = [(f"{m}-05", loyers[m]) for m in MOIS]
    transactions += [_t(d, "PRLV SEPA AGENCE LOYER", -x, "logement") for d, x in paiements]
    groupes.append(_groupe("AGENCE LOYER", "PRLV SEPA AGENCE LOYER", "logement", "mensuelle", paiements, variable))
    classements.append(Classement(cle="AGENCE LOYER", nature="obligatoire", justification="Loyer."))
    if avec_changements:
        credit = [(f"2026-{m:02d}-10", 300.0) for m in range(6, 11)]
        mobile = [(f"{m}-12", 20.0) for m in MOIS[:6]]
        assurance = [("2026-03-20", 360.0)]
        impots = [(f"2025-{m:02d}-15", 100.0) for m in (9, 10, 11, 12)]
        for cle, lib, cat, per, p, nature in [
            ("CREDIT AUTO", "PRLV SEPA CREDIT AUTO", "credit", "mensuelle", credit, "obligatoire"),
            ("FORFAIT MOBILE", "PRLV SEPA FORFAIT MOBILE", "telecom", "mensuelle", mobile, "abonnement_optionnel"),
            ("ASSURANCE AUTO", "PRLV SEPA ASSURANCE AUTO", "assurance", "annuelle", assurance, "obligatoire"),
            ("IMPOTS SOLDE", "PRLV SEPA IMPOTS SOLDE", "impots_taxes", "mensuelle", impots, "obligatoire"),
        ]:
            transactions += [_t(d, lib, -x, cat) for d, x in p]
            groupes.append(_groupe(cle, lib, cat, per, p))
            classements.append(Classement(cle=cle, nature=nature, justification="Essai."))
    return transactions, groupes, classements


def _budget(*args, **kw):
    transactions, groupes, classements = _scenario(*args, **kw)
    return calculer_budget(transactions, groupes, classements, nb_mois=14, periode="2025-09 → 2026-10"), classements


def test_les_charges_fixes_a_leur_montant_actuel():
    budget, _ = _budget()
    a = budget["aujourdhui"]
    assert a["fenetre"] == {"debut": "2025-11", "fin": "2026-10", "nb_mois": 12}
    # Loyer 800, crédit en entier (300, et non 5/14 de 300), assurance 360 / 12, impôt : 2 × 100 payés
    # sur les douze derniers mois / 12 ; le forfait mobile arrêté ne compte plus
    assert a["obligatoire"] == pytest.approx(800 + 300 + 30 + 200 / 12, abs=0.01)
    assert a["optionnel"] == 0
    assert a["courantes"] == pytest.approx(400)
    assert a["revenus"] == pytest.approx(2500)
    assert a["depenses"] == pytest.approx(a["obligatoire"] + 400, abs=0.01)
    # La moyenne de toute la période dilue le crédit : elle est plus basse
    assert budget["depenses_mensuelles"] < a["depenses"] - 100 and a_montrer(a, budget["depenses_mensuelles"])
    sortes = [(c["sorte"], c["libelle"], c["quand"], c["montant"]) for c in a["changements"]]
    assert sortes == [("nouvelle", "PRLV SEPA CREDIT AUTO", "2026-06", 300.0),
                      ("arretee", "PRLV SEPA FORFAIT MOBILE", "2026-02", 20.0)]


def test_une_mensualite_restee_en_depense_courante_compte_a_plein():
    # Un libellé que mas ne sait pas lire comme un crédit : classé « courant », mais au même montant chaque mois
    transactions, groupes, classements = _scenario(avec_changements=False)
    p = [(f"2026-{m:02d}-08", 438.0) for m in range(6, 11)]
    transactions += [_t(d, "PRLV SEPA [PERSONNE_9] AB12", -x, "autre") for d, x in p]
    groupes.append(_groupe("PERSONNE_9 AB12", "PRLV SEPA [PERSONNE_9] AB12", "autre", "mensuelle", p))
    classements.append(Classement(cle="PERSONNE_9 AB12", nature="courant_variable", justification="Inconnu."))
    a = calculer_budget(transactions, groupes, classements, nb_mois=14, periode="2025-09 → 2026-10")["aujourdhui"]
    assert a["courantes"] == pytest.approx(400 + 438) and a["obligatoire"] == pytest.approx(800)
    assert [(c["sorte"], c["nature"], c["montant"]) for c in a["changements"]] == [("nouvelle", "courant_variable", 438.0)]


def test_la_frise_moyenne_compte_ce_qui_a_vraiment_ete_paye():
    # Le crédit (5 mois sur 14), le forfait arrêté, l'impôt en 4 fois : dilués dans la moyenne, sans fausser
    # les dépenses courantes, qui restent les 400 € de courses
    budget, classements = _budget()
    d = donnees_rapport(budget, classements, "Synthèse.")
    assert d["obligatoire_moyen"] == pytest.approx((800 * 14 + 300 * 5 + 360 + 4 * 100) / 14, abs=0.01)
    assert d["optionnel_moyen"] == pytest.approx(20 * 6 / 14, abs=0.01)
    assert d["depenses"] - d["obligatoire_moyen"] - d["optionnel_moyen"] == pytest.approx(400, abs=0.02)
    page = construire_page(d)
    debut = page.index('aria-labelledby="t-recap"')
    assert "Courantes <strong>400\u00a0€</strong>" in page[debut:page.index('aria-labelledby="t-aujourdhui"')]


def test_rien_de_change_rien_a_montrer():
    budget, classements = _budget(avec_changements=False)
    a = budget["aujourdhui"]
    assert a["depenses"] == pytest.approx(1200) and a["changements"] == []
    assert not a_montrer(a, budget["depenses_mensuelles"])
    page = construire_page(donnees_rapport(budget, classements, "Synthèse."))
    assert "En moyenne, tu dépenses" in page and "Ton budget aujourd" not in page
    assert "Ton budget aujourd'hui" not in resume_markdown(budget, classements)


def test_un_loyer_qui_augmente_compte_a_son_nouveau_montant():
    loyers = {m: (780.0 if m < "2026-07" else 820.0) for m in MOIS}
    budget, _ = _budget(loyers=loyers, avec_changements=False)
    a = budget["aujourdhui"]
    assert a["obligatoire"] == pytest.approx(820)
    [c] = a["changements"]
    assert c["sorte"] == "modifiee" and c["montant"] == 820 and c["avant"] == pytest.approx(791.43, abs=0.01)


def test_un_montant_qui_varie_compte_pour_sa_moyenne_recente():
    variable = {m: 60.0 + (i % 3) * 30 for i, m in enumerate(MOIS)}      # 60, 90, 120…
    budget, _ = _budget(loyers=variable, avec_changements=False, variable=True)
    recents = [variable[m] for m in MOIS[2:]]
    assert budget["aujourdhui"]["obligatoire"] == pytest.approx(sum(recents) / len(recents), abs=0.01)


def test_moins_de_trois_mois_complets_pas_de_budget_d_aujourd_hui():
    par_mois = {"mois": ["2026-08", "2026-09", "2026-10"], "partiels": ["2026-08"], "totaux": [1, 2, 3],
                "revenus": [1, 2, 3], "lignes": []}
    assert budget_aujourdhui([], [], [], par_mois) is None


def test_moins_d_un_an_de_releves_rien_n_est_nouveau_parce_qu_il_commence_avec_eux():
    transactions, groupes, classements = _scenario()
    debut = "2026-01"
    transactions = [t for t in transactions if t.date[:7] >= debut]
    groupes = [g.model_copy(update={"dates": [d for d in g.dates if d[:7] >= debut]}) for g in groupes]
    groupes = [g for g in groupes if g.dates]
    budget = calculer_budget(transactions, groupes, classements, nb_mois=10, periode="2026-01 → 2026-10")
    sortes = {c["libelle"]: c["sorte"] for c in budget["aujourdhui"]["changements"]}
    assert "PRLV SEPA AGENCE LOYER" not in sortes and sortes["PRLV SEPA CREDIT AUTO"] == "nouvelle"


def test_la_page_et_le_texte_montrent_les_deux_frises():
    budget, classements = _budget()
    page = construire_page(donnees_rapport(budget, classements, "Synthèse."))
    assert page.index("En moyenne, tu dépenses") < page.index("Aujourd'hui, tu dépenses")
    assert ">Ton budget aujourd'hui</h2>" in page and 'aria-labelledby="t-recap-aujourdhui"' in page
    assert "Dépenses régulières à leur montant actuel ; le reste en moyenne de novembre 2025 à octobre 2026" in page
    assert "nouvelle depuis juin 2026" in page and "arrêtée (dernier paiement en février 2026)" in page
    assert page.count("Pas compté dans tes dépenses") <= 1      # les virements entre comptes : sous la moyenne seulement
    texte = resume_markdown(budget, classements)
    assert "### Ton budget aujourd'hui" in texte and "| Charges fixes actuelles |" in texte
    assert "nouvelle depuis juin 2026 : PRLV SEPA CREDIT AUTO" in texte
