"""Page HTML du rapport : données, version anonyme / personnelle, cas limites, export (sans IA)."""
import json

import yaml
from typer.testing import CliRunner

from mas.cli import app
from mas.modeles import Classement, GroupeRecurrent
from mas.page import construire_page, donnees_rapport, ecrire_pages

VALEURS = {"PERSONNE_1": "Claire DUBOIS", "REF_1": "RUM-0042"}


def _groupe(cle, libelle, categorie, mensuel):
    return GroupeRecurrent(cle=cle, libelle=libelle, categorie=categorie, periodicite="mensuelle",
                           occurrences=4, montant_moyen=mensuel, montant_mensuel=mensuel,
                           montant_variable=False, dates=[])


def _budget(revenus=3091.84, depenses=2509.49):
    loyer = _groupe("loyer", "VIR SEPA PERMANENT M [PERSONNE_1] LOYER", "logement", 1037.29)
    sport = _groupe("sport", "PRLV SEPA BASIC FIT <script>alert(1)</script>", "abonnement", 29.84)
    return {
        "nb_mois": 4, "periode": "2026-01 → 2026-04",
        "revenus_mensuels": revenus, "depenses_mensuelles": depenses,
        "par_categorie": {"logement": 1037.29, "alimentation": 487.41, "abonnement": 29.84},
        "par_nature": {"obligatoire": [loyer], "abonnement_optionnel": [sport]},
        "total_obligatoire": 1037.29, "total_optionnel": 29.84,
        "reste_apres_obligatoire": revenus - 1037.29,
    }


CLASSEMENTS = [
    Classement(cle="loyer", nature="obligatoire", justification="Loyer versé à [PERSONNE_1]."),
    Classement(cle="sport", nature="abonnement_optionnel", justification="Résiliable."),
]
SYNTHESE = "**Constat budgétaire**\n\nTu gardes 582,35 € par mois.\n\n1. **Résilier Basic Fit** : 29,84 € par mois."


def _donnees(**kw):
    return donnees_rapport(_budget(**kw), CLASSEMENTS, SYNTHESE, alertes=1,
                           traitement={"modele": "anthropic/claude-haiku-4-5-20251001", "duree_analyse": 81,
                                       "duree_anonymisation": 7, "appels": 11, "tokens_entree": 14622,
                                       "tokens_sortie": 10839, "cout_usd": 0.069, "reponses_cache": 0})


def test_donnees_serialisables_et_sans_vraies_valeurs():
    d = _donnees()
    texte = json.dumps(d, ensure_ascii=False)
    assert "[PERSONNE_1]" in texte and "Claire" not in texte
    assert d["periode"] == {"debut": "2026-01", "fin": "2026-04", "nb_mois": 4}
    assert {r["nature"] for r in d["recurrents"]} == {"obligatoire", "abonnement_optionnel"}


def test_version_anonyme_affiche_des_masques():
    page = construire_page(_donnees())
    assert 'class="masque"' in page and "Personne 1" in page and "Claire" not in page
    assert "Version anonyme" in page
    assert "il te reste" in page and "582 €" in page            # 3 091,84 − 2 509,49
    assert "De janvier à avril 2026, 4 mois de relevés" in page
    assert "<script>alert" not in page and "&lt;script&gt;" in page   # libellé neutralisé
    assert "http://" not in page and "https://" not in page          # aucune ressource externe
    assert '<p class="intertitre">Constat budgétaire</p>' in page
    assert "582,35 €" in page and "Basic Fit</strong> :" in page   # typographie française
    assert "1 page contient" in page                                  # alerte d'extraction
    assert "11 appels" in page and "coût estimé 0,069" in page


def test_version_personnelle_signale_les_valeurs_remises_en_local():
    page = construire_page(_donnees(), VALEURS)
    assert '<mark class="demasque"' in page and "Claire DUBOIS" in page
    assert 'class="masque"' not in page and "Version personnelle" in page


def test_la_frise_dit_que_c_est_une_moyenne_et_sur_quelle_periode():
    # Elle ne doit pas passer pour le mois en cours : une moyenne de toute la période, période écrite d'après les relevés
    page = construire_page(_donnees())
    assert "En moyenne, tu dépenses <strong>2" in page and "Moyennes mensuelles de janvier à avril 2026, sur" in page
    assert ">Ton mois moyen</h2>" in page and "Ton mois type" not in page
    longue = _donnees()
    longue["periode"] = {"debut": "2025-03", "fin": "2026-10", "nb_mois": 20}
    assert "Moyennes mensuelles de mars 2025 à octobre 2026, sur" in construire_page(longue)
    longue["periode"] = {"debut": "?", "fin": "?", "nb_mois": 0}
    assert "Moyennes mensuelles, sur" in construire_page(longue)


def test_deficit_et_revenus_absents():
    deficit = construire_page(_donnees(revenus=2000, depenses=2509.49))
    assert "tu dépenses de plus" in deficit and 'class="repere"' in deficit and "509 €" in deficit
    sans_revenus = construire_page(_donnees(revenus=0, depenses=2509.49))
    assert "non détectés" in sans_revenus


def test_ecrire_pages_puis_exporter_depuis_le_json(tmp_path, monkeypatch):
    md = tmp_path / "rapport.md"
    md.write_text("# Analyse budgétaire\n", encoding="utf-8")
    perso, anonyme, chemin_json = ecrire_pages(md, _donnees(), VALEURS)
    assert "Claire DUBOIS" in perso.read_text(encoding="utf-8")
    assert "Claire" not in anonyme.read_text(encoding="utf-8")
    assert "Claire" not in chemin_json.read_text(encoding="utf-8")

    # `mas exporter` régénère les deux pages à partir du JSON (coffre éphémère : pas de vraies valeurs)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump({"coffre": {"chemin": str(tmp_path / "coffre.bin")}}), encoding="utf-8")
    perso.unlink()
    resultat = CliRunner().invoke(app, ["exporter", "rapport_anonyme.md"])
    assert resultat.exit_code == 0, resultat.output
    regeneree = perso.read_text(encoding="utf-8")
    assert "Version personnelle" in regeneree and "Personne 1" in regeneree   # pseudonyme inconnu du coffre


def test_tableau_mois_par_mois():
    budget = _budget()
    budget["par_mois"] = {
        "mois": ["2025-12", "2026-01", "2026-02"], "partiels": ["2025-12"],
        "lignes": [{"categorie": "logement", "montants": [0.0, 1037.29, 1037.29]},
                   {"categorie": "alimentation", "montants": [120.0, 512.4, -15.0]}],
        "totaux": [120.0, 1549.69, 1022.29],
    }
    page = construire_page(donnees_rapport(budget, CLASSEMENTS, SYNTHESE))
    section = page.split('<section class="par-mois"', 1)[1].split("</section>", 1)[0]
    assert "Mois par mois" in section and "déc.<span class=\"annee\">2025</span>" in section
    assert "janv.<span class=\"annee\">2026</span>" in section and "févr.</th>" in section  # année une fois
    assert section.count('<span class="incomplet">incomplet</span>') == 1 and "Mois incomplet" in section
    assert "color-mix(in srgb, var(--cat) 55%" in section                  # case la plus forte
    assert '<td class="num vide">—</td>' in section and "−15\xa0€" in section  # mois sans dépense, remboursement
    assert ">Logement</th>" in section and "1\u202f550\xa0€" in section             # libellé lisible, total du mois
    assert '<td class="num moyenne">2\u202f509\xa0€</td>' in section               # moyenne = dépenses mensuelles
    assert page.index('class="par-mois"') < page.index('class="recurrents"')


def test_pas_de_tableau_mois_par_mois_sur_un_seul_mois():
    budget = _budget()
    budget["par_mois"] = {"mois": ["2026-01"], "partiels": [], "totaux": [1037.29],
                          "lignes": [{"categorie": "logement", "montants": [1037.29]}]}
    assert 'class="par-mois"' not in construire_page(donnees_rapport(budget, CLASSEMENTS, SYNTHESE))
    assert 'class="par-mois"' not in construire_page(_donnees())             # ancien rapport.json


def test_notes_loyer_probable_et_remboursements():
    budget = _budget()
    budget["loyers"] = [{"beneficiaire": "PERSONNE_1", "montant_mensuel": 850.0, "mois": 6}]
    budget["proches"] = {"envoye": 100.0, "recu": 110.0, "rembourse": 80.0, "depense": 20.0, "revenu": 30.0}
    donnees = donnees_rapport(budget, CLASSEMENTS, SYNTHESE)
    anonyme = construire_page(donnees)
    assert "c'est sans doute un loyer" in anonyme and "Personne 1" in anonyme and "Claire" not in anonyme
    assert "dont 80\u00a0€ de remboursements" in anonyme
    assert "Claire DUBOIS" in construire_page(donnees, VALEURS)


def test_virements_avec_des_proches_par_personne():
    budget = _budget()
    budget["proches"] = {"envoye": 2300.0, "recu": 0.0, "rembourse": 0.0, "depense": 2300.0, "revenu": 0.0}
    budget["proches_detail"] = [{
        "personne": "PERSONNE_1", "virements": 2, "envoye": 9200.0, "recu": 0.0, "depense": 9200.0, "revenu": 0.0,
        "nature": "ponctuel", "plus_gros": {"date": "2026-03-20", "montant": 9000.0},
        "operations": [{"date": "2026-02-02", "libelle": "VIR INST A [PERSONNE_1]", "montant": -200.0},
                       {"date": "2026-03-20", "libelle": "VIR SEPA EMIS VERS [PERSONNE_1] <b>", "montant": -9000.0}],
    }, {
        "personne": "boursorama", "virements": 1, "envoye": 0.0, "recu": 50.0, "depense": 0.0, "revenu": 50.0,
        "nature": "recus", "plus_gros": None,
        "operations": [{"date": "2026-01-05", "libelle": "VIR RECU BOURSORAMA", "montant": 50.0}],
    }]
    donnees = donnees_rapport(budget, CLASSEMENTS, SYNTHESE)
    assert "Claire" not in json.dumps(donnees, ensure_ascii=False)
    anonyme = construire_page(donnees)
    assert "Virements avec des proches, personne par personne" in anonyme and "Personne 1" in anonyme
    assert "Claire" not in anonyme and "&lt;b&gt;" in anonyme and "<b>" not in anonyme
    assert "9\u202f000,00\u00a0€" in anonyme and "le 20 mars 2026" in anonyme and "2\u202f300\u00a0€ par mois" in anonyme
    assert "boursorama" in anonyme and "comptes_personnels" in anonyme
    assert anonyme.index('class="proches"') < anonyme.index('class="recurrents"')
    assert "Claire DUBOIS" in construire_page(donnees, VALEURS)
    assert 'class="proches"' not in construire_page(_donnees())             # ancien rapport.json


def test_depense_annuelle_comptee_une_fois_par_an():
    budget = _budget()
    assurance = GroupeRecurrent(cle="axa", libelle="PRLV SEPA AXA FRANCE IARD", categorie="assurance",
                                periodicite="annuelle", occurrences=1, montant_moyen=987.40,
                                montant_mensuel=82.28, montant_variable=False, dates=[])
    budget["par_nature"]["obligatoire"].append(assurance)
    donnees = donnees_rapport(budget, CLASSEMENTS, SYNTHESE)
    ligne = construire_page(donnees).split("PRLV SEPA AXA FRANCE IARD")[1].split("</tr>")[0]
    assert "une fois par an, payé 1 fois" in ligne and "ramené au mois" in ligne
    assert "82,28" in ligne and "987" in ligne
    from mas.page import _par_an
    axa = next(r for r in donnees["recurrents"] if r["libelle"].startswith("PRLV SEPA AXA"))
    assert _par_an(axa) == 987.40                                              # pas 12 × 82,28 = 987,36


def test_section_a_verifier():
    budget = _budget()
    budget["a_verifier"] = [{"date": "2026-04-14", "libelle": "Carte 1000001 [PERSONNE_1] le 13/04/26", "montant": -250.0,
                             "categorie": "autre", "raison": "Commerçant inconnu : donne sa catégorie dans analyse.categories."}]
    donnees = donnees_rapport(budget, CLASSEMENTS, SYNTHESE)
    anonyme = construire_page(donnees)
    assert "À vérifier" in anonyme and "14 avril 2026" in anonyme and "Commerçant inconnu" in anonyme
    assert "Claire" not in anonyme and "Claire DUBOIS" in construire_page(donnees, VALEURS)
    assert 'class="a-verifier"' not in construire_page(_donnees())          # rien à vérifier : pas de section


def _par_mois_avec_revenus(budget):
    budget["par_mois"] = {
        "mois": ["2025-12", "2026-01", "2026-02", "2026-03"], "partiels": ["2025-12"],
        "revenus": [500.0, 3000.0, 2500.0, 3500.0],
        "lignes": [{"categorie": "logement", "montants": [100.0, 1037.29, 1037.29, 1037.29]},
                   {"categorie": "alimentation", "montants": [0.0, 962.71, 2462.71, 1462.71]}],
        "totaux": [100.0, 2000.0, 3500.0, 2500.0],
    }
    return budget


def test_ecart_revenus_depenses_avec_la_moyenne():
    page = construire_page(donnees_rapport(_par_mois_avec_revenus(_budget()), CLASSEMENTS, SYNTHESE))
    section = page.split('<section class="ecart"', 1)[1].split("</section>", 1)[0]
    assert section.count("<svg") == 2                               # bureau et téléphone
    # écarts +1 000, −1 000, +1 000 ; décembre, incomplet, est laissé de côté
    assert "moyenne +333\xa0€" in section and "Moyenne sur 3 mois" in section
    assert section.count('class="depassement"') == 2 and "décembre" not in section
    assert "Les mois incomplets sont laissés de côté" in section
    assert page.index('class="ecart"') < page.index('class="par-mois"')


def test_pas_d_ecart_sans_revenus_mois_par_mois():
    budget = _par_mois_avec_revenus(_budget())
    budget["par_mois"].pop("revenus")
    assert 'class="ecart"' not in construire_page(donnees_rapport(budget, CLASSEMENTS, SYNTHESE))


OPERATIONS = [
    {"date": "2026-01-20", "libelle": "VIR SEPA [PERSONNE_1] REMBOURSEMENT", "montant": 12.0, "categorie": "alimentation"},
    {"date": "2026-01-03", "libelle": "CB CARREFOUR 02/01 CB*1234", "montant": -52.3, "categorie": "alimentation"},
    {"date": "2026-02-05", "libelle": "PRLV SEPA LOYER [PERSONNE_1] FR42ZZZ457385 SEPA AB12 RCUR 9", "montant": -1037.29,
     "categorie": "logement"},
    {"date": "2026-02-27", "libelle": "VIR SALAIRE", "montant": 3091.84, "categorie": "revenu"},
]


def test_page_de_detail_par_categorie_puis_par_mois(tmp_path):
    d = donnees_rapport(_par_mois_avec_revenus(_budget()), CLASSEMENTS, SYNTHESE, operations=OPERATIONS)
    md = tmp_path / "rapport.md"
    md.write_text("# Analyse budgétaire\n", encoding="utf-8")
    perso, anonyme, chemin_json = ecrire_pages(md, d, VALEURS)
    detail_anonyme = (tmp_path / "rapport_anonyme_detail.html").read_text(encoding="utf-8")
    detail_perso = (tmp_path / "rapport_detail.html").read_text(encoding="utf-8")

    # le rapport mène au détail : la catégorie, et chaque case du tableau mois par mois
    page = anonyme.read_text(encoding="utf-8")
    assert 'class="vers-detail" href="rapport_anonyme_detail.html#cat-logement"' in page
    assert 'href="rapport_anonyme_detail.html#cat-logement-2026-02"' in page
    assert "Touche une catégorie" in page
    assert 'href="rapport_detail.html#cat-alimentation"' in perso.read_text(encoding="utf-8")

    # le détail : une section par catégorie, un bloc par mois, le plus récent en haut
    assert 'id="cat-alimentation-2026-01"' in detail_anonyme and 'id="cat-logement-2026-02"' in detail_anonyme
    assert detail_anonyme.index('id="cat-logement"') < detail_anonyme.index('id="cat-alimentation"')
    assert "40,30\xa0€" in detail_anonyme                            # 52,30 dépensés, 12 remboursés
    assert "+12,00\xa0€" in detail_anonyme and "remboursement</span>" in detail_anonyme
    assert "CB*1234" not in detail_anonyme and "FR42ZZZ" not in detail_anonyme   # références techniques retirées
    assert "VIR SALAIRE" not in detail_anonyme                       # un revenu n'est pas une dépense
    assert 'href="rapport_anonyme.html#t-cat"' in detail_anonyme
    assert 'class="masque"' in detail_anonyme and "Claire" not in detail_anonyme
    assert "Claire DUBOIS" in detail_perso and "Version personnelle" in detail_perso

    donnees = json.loads(chemin_json.read_text(encoding="utf-8"))
    assert [o["date"] for o in donnees["operations"]][:2] == ["2026-01-03", "2026-01-20"]
    assert "Claire" not in chemin_json.read_text(encoding="utf-8")


def test_sans_operations_ni_page_de_detail_ni_liens(tmp_path):
    md = tmp_path / "rapport.md"
    md.write_text("# Analyse budgétaire\n", encoding="utf-8")
    _, anonyme, _ = ecrire_pages(md, _donnees(), VALEURS)
    assert not (tmp_path / "rapport_detail.html").exists()
    assert 'class="vers-detail"' not in anonyme.read_text(encoding="utf-8")


def test_mois_par_mois_part_a_payer_quoi_qu_il_arrive():
    budget = _budget()
    budget["par_mois"] = {
        "mois": ["2026-01", "2026-02"], "partiels": [],
        "lignes": [{"categorie": "logement", "montants": [1037.29, 1137.29], "obligatoire": [1037.29, 1037.29]},
                   {"categorie": "alimentation", "montants": [512.4, 400.0], "obligatoire": [0.0, 0.0]}],
        "totaux": [1549.69, 1537.29],
    }
    section = construire_page(donnees_rapport(budget, CLASSEMENTS, SYNTHESE)).split('<section class="par-mois"', 1)[1]
    section = section.split("</section>", 1)[0]
    # janvier : tout le loyer est obligatoire ; février : 1 037 € obligatoires sur 1 137 €, le reste à part
    assert "var(--s1) 51%, transparent) 100%" in section                      # janvier, un peu moins intense
    assert "var(--s1) 55%, transparent) 91%, color-mix(in srgb, var(--cat) 55%, transparent) 91%" in section
    assert 'title="1 037\xa0€ à payer quoi qu&#x27;il arrive, 100\xa0€ d&#x27;autres dépenses"' in section or \
           "à payer quoi qu" in section
    assert section.count('class="num oblig"') == 2                              # les courses restent d'une couleur
    assert "Tes autres dépenses" in section and 'class="pastille s1"' in section


def test_pas_de_legende_sans_depense_obligatoire():
    budget = _budget()
    budget["par_mois"] = {"mois": ["2026-01", "2026-02"], "partiels": [],
                          "lignes": [{"categorie": "alimentation", "montants": [512.4, 400.0]}], "totaux": [512.4, 400.0]}
    section = construire_page(donnees_rapport(budget, CLASSEMENTS, SYNTHESE)).split('<section class="par-mois"', 1)[1]
    assert "Tes autres dépenses" not in section.split("</section>", 1)[0]


def test_epargne_d_un_proche_hors_depenses_avec_ce_qui_reste_chez_toi():
    budget = _budget()                                   # 4 mois
    budget["transferts"] = {"epargne_proche": {"sortis": 75.0, "rentres": 100.0}}
    page = construire_page(donnees_rapport(budget, CLASSEMENTS, SYNTHESE))
    assert "rendus à un proche qui garde son épargne sur ton compte" in page
    assert "400\u00a0€ reçus et 300\u00a0€ rendus sur la période, soit 100\u00a0€ encore chez toi" in page
    budget["transferts"]["epargne_proche"]["sortis"] = 100.0
    assert "encore chez toi" not in construire_page(donnees_rapport(budget, CLASSEMENTS, SYNTHESE))
