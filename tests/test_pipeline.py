import dspy

from faux_llm import FauxLLM
from mas.agents import AnalyseReleve, Synthetiseur
from mas.modeles import TransactionCategorisee
from mas.optimisation.metrique import evaluer_prediction, metrique_gepa
from mas.recurrence import cle_libelle, detecter_recurrences


def _exemples(jeu):
    return [
        dspy.Example(pages=d["pages"], transactions=d["transactions"],
                     recurrents=d["recurrents"], pii=d["pii"]).with_inputs("pages")
        for d in jeu
    ]


def test_cle_libelle():
    assert cle_libelle("PRLV SEPA EDF CLIENTS PARTICULIERS RUM [REF_1]") == "EDF CLIENTS PARTICULIERS"
    assert cle_libelle("CB NETFLIX.COM 05/03") == cle_libelle("CB NETFLIX.COM 07/04")
    assert "PERSONNE_2" in cle_libelle("VIR SEPA PERMANENT M [PERSONNE_2] LOYER")


def test_recurrences_sur_verite_terrain(jeu_anonymise):
    for d in jeu_anonymise:
        tx = [TransactionCategorisee(**t) for t in d["transactions"]]
        libelles = " ".join(g.libelle for g in detecter_recurrences(tx))
        for r in d["recurrents"]:
            assert r["motif"] in libelles, r["motif"]


def test_programme_complet_avec_faux_llm(jeu_anonymise):
    lm = FauxLLM()
    with dspy.context(lm=lm):
        programme = AnalyseReleve()
        ex = _exemples(jeu_anonymise)[0]
        pred = programme(pages=ex.pages)
        # la boucle contrôleur -> extracteur a corrigé l'oubli volontaire
        assert not pred.alertes_extraction
        ev = evaluer_prediction(ex, pred)
        assert ev.scores["extraction"] == 1.0
        assert ev.scores["categorisation"] > 0.9
        assert ev.scores["nature"] > 0.9
        assert ev.scores["recurrence"] > 0.8
        assert not ev.fuite
        retour = metrique_gepa(ex, pred, pred_name="categoriseur")
        assert 0 < retour.score <= 1 and "Score global" in retour.feedback

        rapport = Synthetiseur()(pred.transactions, pred.recurrents, pred.classements).rapport
        assert "Dépenses obligatoires" in rapport


def test_metrique_penalise_les_fuites(jeu_anonymise):
    ex = _exemples(jeu_anonymise)[0]
    fausse = dspy.Prediction(
        transactions=[TransactionCategorisee(date="2026-01-01", libelle=f"VIR A {ex.pii[0]}",
                                             montant=-10, categorie="autre")],
        recurrents=[], classements=[],
    )
    r = metrique_gepa(ex, fausse)
    assert r.score == 0 and "ÉCHEC CRITIQUE" in r.feedback


def test_boucle_gepa_avec_faux_llm(jeu_anonymise):
    exemples = _exemples(jeu_anonymise)
    lm = FauxLLM()
    dspy.configure(lm=lm)
    gepa = dspy.GEPA(metric=metrique_gepa, max_metric_calls=12, reflection_lm=FauxLLM(),
                     num_threads=1, track_stats=True)
    optimise = gepa.compile(AnalyseReleve(), trainset=exemples[:2], valset=exemples[2:])
    assert {n for n, _ in optimise.named_predictors()} >= {"categoriseur", "classeur.predict"}


def test_analyse_dans_le_compteur_de_tokens(config, jeu_anonymise, monkeypatch):
    """Régression : un LM configuré à l'intérieur de dspy.track_usage() (comme le fait
    `mas analyser`) n'était pas vu par les agents : « No LM is loaded » sur chaque page."""
    import mas.orchestrateur as module_orchestrateur
    from mas.anonymisation import Coffre

    faux = FauxLLM()

    def configurer_faux(_config_llm):
        dspy.configure(lm=faux)            # comme le vrai configurer_lm
        return faux

    monkeypatch.setattr(module_orchestrateur, "configurer_lm", configurer_faux)
    orchestrateur = module_orchestrateur.Orchestrateur(config, Coffre(None))
    docs = [module_orchestrateur.DocumentAnonymise("releve.pdf", jeu_anonymise[0]["pages"])]
    with dspy.track_usage():
        resultat = orchestrateur.analyser(docs)
    assert resultat.analyse.transactions and not resultat.analyse.alertes_extraction
    assert faux.appels > 0 and orchestrateur.lm is faux


def test_cle_libelle_sans_references_ni_dates_collees():
    # Un loyer dont chaque virement porte un identifiant différent reste une seule dépense
    assert cle_libelle("Virement instantané émis a1b2c3d residence [PERSONNE_3] loyer [PERSONNE_1]") \
        == cle_libelle("Virement instantané émis 1234567 residence [PERSONNE_3] loyer [PERSONNE_1]")
    # Boursorama colle la date au commerçant ; la BP écrit « Carte <n°> <commerçant> le <date> »
    assert cle_libelle("CARTE02/05/26WWW.STREAMING.COM CB*1234") == cle_libelle("Carte 1234567 www.streaming.com le 02/01/26 / ref cb.xxxxx5678")
    assert cle_libelle("CARTE30/08/26BOULANGERIE319 2CB*1234") == "BOULANGERIE"


def test_depense_annuelle_et_categories_imposees():
    from mas.agents.programme import appliquer_categories
    from mas.recurrence import reperer_annuels

    courses = [TransactionCategorisee(date=f"2026-{m:02d}-05", libelle="CB LIDL", montant=-40.0, categorie="alimentation")
               for m in range(1, 9)]
    axa = [TransactionCategorisee(date="2026-05-29", libelle="PRLV SEPA ASSURANCE AUTO EXEMPLE", montant=-1200.00, categorie="assurance"),
           TransactionCategorisee(date="2026-07-30", libelle="VIR SEPA ASSURANCE AUTO EXEMPLE REMBOURSEMENT", montant=200.0, categorie="assurance")]
    groupes = reperer_annuels(courses + axa, [])
    assert [(g.periodicite, g.montant_moyen, g.montant_mensuel) for g in groupes] == [("annuelle", 1000.0, 83.33)]
    assert reperer_annuels(courses[:3] + axa, []) == []          # moins de six mois : on ne peut pas savoir

    ops = [TransactionCategorisee(date="2026-06-01", libelle="Carte 1000005 [PERSONNE_7] le 26/05/26", montant=-450.0, categorie="shopping"),
           TransactionCategorisee(date="2026-03-05", libelle="Carte 1000006 autoservice le 04/03/26", montant=-500.0, categorie="shopping")]
    en_clair = lambda l: l.replace("[PERSONNE_7]", "garage martin")
    imposees = appliquer_categories(ops, {"Garage Martin": "transport", "AUTOSERVICE": "transport"}, en_clair)
    assert [t.categorie for t in imposees] == ["transport", "transport"]
    assert [t.libelle for t in imposees] == [t.libelle for t in ops]      # les vrais noms ne sont pas écrits


def test_loyer_paye_a_date_variable():
    dates = ["2026-01-01", "2026-01-29", "2026-02-25", "2026-03-27", "2026-05-05", "2026-06-15", "2026-07-04",
             "2026-08-01", "2026-08-31", "2026-09-28"]
    loyers = [TransactionCategorisee(date=d, libelle=f"VIR INST EMIS {i}A{i}F9C RESIDENCE [PERSONNE_3] LOYER",
                                     montant=-650.0 - i, categorie="logement") for i, d in enumerate(dates)]
    courses = [TransactionCategorisee(date=f"2026-{m:02d}-{j:02d}", libelle="CB LIDL", montant=-35.0 - j, categorie="alimentation")
               for m in range(1, 10) for j in (2, 11, 15, 27)]           # jours irréguliers
    groupes = {g.cle: g for g in detecter_recurrences(loyers + courses)}
    assert groupes["RESIDENCE PERSONNE_3 LOYER"].periodicite == "mensuelle"
    assert "LIDL" not in groupes                                     # des courses, plusieurs fois par mois : pas un loyer
