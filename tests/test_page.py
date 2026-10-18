"""Page HTML du rapport : données, version anonyme / personnelle, cas limites, export (sans IA)."""
import json

import yaml
from typer.testing import CliRunner

from mas.cli import app
from mas.modeles import Classement, GroupeRecurrent
from mas.page import construire_page, donnees_rapport, ecrire_pages

VALEURS = {"PERSONNE_1": "Aline VERDIER", "REF_1": "RUM-0042"}


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
    assert "[PERSONNE_1]" in texte and "Aline" not in texte
    assert d["periode"] == {"debut": "2026-01", "fin": "2026-04", "nb_mois": 4}
    assert {r["nature"] for r in d["recurrents"]} == {"obligatoire", "abonnement_optionnel"}


def test_version_anonyme_affiche_des_masques():
    page = construire_page(_donnees())
    assert 'class="masque"' in page and "Personne 1" in page and "Aline" not in page
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
    assert '<mark class="demasque"' in page and "Aline VERDIER" in page
    assert 'class="masque"' not in page and "Version personnelle" in page


def test_deficit_et_revenus_absents():
    deficit = construire_page(_donnees(revenus=2000, depenses=2509.49))
    assert "tu dépenses de plus" in deficit and 'class="repere"' in deficit and "509 €" in deficit
    sans_revenus = construire_page(_donnees(revenus=0, depenses=2509.49))
    assert "non détectés" in sans_revenus


def test_ecrire_pages_puis_exporter_depuis_le_json(tmp_path, monkeypatch):
    md = tmp_path / "rapport.md"
    md.write_text("# Analyse budgétaire\n", encoding="utf-8")
    perso, anonyme, chemin_json = ecrire_pages(md, _donnees(), VALEURS)
    assert "Aline VERDIER" in perso.read_text(encoding="utf-8")
    assert "Aline" not in anonyme.read_text(encoding="utf-8")
    assert "Aline" not in chemin_json.read_text(encoding="utf-8")

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
