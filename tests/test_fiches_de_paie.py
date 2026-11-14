"""Les fiches de paie, sur des données inventées : classeur fictif et mots de bulletin fabriqués (paie_factice.py)."""
import json

import pytest

from paie_factice import bulletin_recent, ecrire_classeur, ligne, mois_fictif, mot, page
from mas.anonymisation import Coffre
from mas.config import ConfigPaie, Identite
from mas.paie import analyses as A
from mas.paie.anonymisation import anonymiser_pages, anonymiseurs
from mas.paie.annonces import verifier
from mas.paie.chargement import analyser, charger
from mas.paie.controles import comparer, ecarts_internes
from mas.paie.croise import construire_page as page_croisee
from mas.paie.croise import croiser
from mas.paie.excel import lire_classeur, verifier_classeur
from mas.paie.export import donnees_paie
from mas.paie.modeles import Bulletin, Ligne
from mas.paie.natures import nature_de
from mas.paie.page import construire_page
from mas.paie.pdf import analyser_lignes, calibrer, lire_bulletin
from mas.paie.prevision import prevoir
from mas.paie.sortie import ecrire_pages, relier


# --- les natures -------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("libelle, nature", [
    ("SALAIRE DE BASE", "base"), ("REMUNERATION BRUTE", "base"), ("Salaire de base rappel", "rappel"),
    ("Prime d'assiduite mois anter", "rappel"), ("PRIME D'ASSIDUITE", "mensuelle"), ("CET PRIME", "cet"),
    ("Gratification fin d'année", "treizieme"), ("Prime de performance", "variable"), ("INTERESSEMENT", "interessement"),
    ("PRIME DE PARTAGE DE LA VALEUR", "exceptionnelle"), ("FRAIS TRANSPORT MOIS ANTER", "frais"),
    ("Indemnite teletravail", "frais"), ("Retenue pour ABS", "absence"), ("GRATIFICATION DE STAGE", "stage"),
    ("Sejour stage", "frais"), ("LIGNE INCONNUE", "autre"),
])
def test_nature_des_libelles(libelle, nature):
    assert nature_de(libelle) == nature


def test_une_correction_de_config_par_mot_du_libelle():
    assert nature_de("XYZ REGION NORD", {"XYZ": "mensuelle"}) == "mensuelle"
    assert nature_de("Prime de vacances", {"PRIME DE VACANCES": "treizieme", "PRIME": "mensuelle"}) == "treizieme"


# --- le classeur -------------------------------------------------------------------------------------------------

@pytest.fixture
def classeur(tmp_path):
    chemin = tmp_path / "paie.xlsx"
    ecrire_classeur(chemin)
    return chemin


def test_lecture_du_classeur(classeur):
    bs = lire_classeur(classeur, renommer=str.upper)
    assert [b.mois for b in bs][:2] == ["2024-01", "2024-02"] and len(bs) == 24
    juin = next(b for b in bs if b.mois == "2024-06")
    attendu = mois_fictif(2024, 6)
    assert juin.net_avant_impot == attendu["net_avant"] and juin.net_paye == attendu["net_apres"] and juin.ecart == 0
    assert juin.somme("treizieme") == 1000.0 and juin.lignes[0].libelle == "SALAIRE DE BASE"     # libellés renommés


def test_les_formules_du_classeur(tmp_path):
    chemin = tmp_path / "paie.xlsx"
    ecrire_classeur(chemin, mois_2025=8)
    textes = " ".join(r["texte"] for r in verifier_classeur(chemin, lire_classeur(chemin)))
    assert "étiqueté 2025, sur la feuille 2024" in textes and "sur les 8 mois remplis" in textes


def test_un_signe_inverse_se_voit_sans_bulletin(tmp_path):
    chemin = tmp_path / "paie.xlsx"
    ecrire_classeur(chemin, signe_inverse=True)
    [e] = ecarts_internes(lire_classeur(chemin))
    assert e["mois"] == "2025-02" and e["ecart"] == 80.0 and "mauvais signe" in e["piste"]


# --- le bulletin PDF ----------------------------------------------------------------------------------------------

def test_bulletin_au_format_recent():
    pages = bulletin_recent()
    assert calibrer(pages) is not None
    r = analyser_lignes(pages, calibrer(pages))
    assert r["periode"] == "2026-03" and r["cotisations"] == 438.5
    assert [l[1] for l in r["lignes"]] == ["SALAIRE DE BASE", "PRIME D'ASSIDUITE", "CET PRIME"]   # pas l'encart « POUR … »
    assert r["apres_net"] == [("BEB", "FRAIS TRANSPORT MOIS ANTER", -20.0)]          # la régularisation du net social est ignorée
    assert r["impot"] == 80.5 and r["taux_pas"] == 5.0 and r["net_paye"] == 1461.0 and r["net_avant_impot"] == 1541.5
    b = lire_bulletin(pages, "essai.pdf")
    assert b.ecart == 0 and b.net_paye == 1461.0


def test_bulletin_ancien_sans_brut_ni_net_social():
    p1 = page(
        [mot("PERIODE:", 23, 61, 29), mot("01", 75, 85, 29), mot("01", 90, 99, 29), mot("2022", 104, 123, 29)],
        ligne(307, "001", "SALAIRE DE BASE", ("1800,00", 503)),
        ligne(358, "8U1", "COTISATION MUTUELLE", ("1800,00", 327), ("0,54", 368), ("9,72", 435), ("18,00", 571)),
        ligne(630, "", "TOTAL COTISATIONS ET CONTRIBUTIONS", ("400,00", 436), ("0,00", 504)),
        ligne(656, "P58", "MT PAS TX NN PERSO", ("1450,00", 327), ("5,30", 368), ("76,85", 435)),
    )
    p2 = page(
        [mot("POUR", 23, 50, 200), mot("INFO", 55, 80, 200), mot("21,67", 466, 486, 200)],    # l'en-tête répété
        ligne(315, "609", "INDEMNITE REGION", ("11,43", 503)),
        [mot("1411,43", 432, 490, 802), mot("0,00", 180, 196, 802), mot("1334,58", 549, 581, 802)],
    )
    b = lire_bulletin([p1, p2], "ancien.pdf")
    assert b.mois == "2022-01" and b.cotisations == 400.0 and b.taux_neutre
    assert [l.libelle for l in b.lignes] == ["SALAIRE DE BASE", "INDEMNITE REGION"]
    assert b.net_paye == 1334.58 and b.net_avant_impot == 1411.43


# --- l'anonymisation ----------------------------------------------------------------------------------------------

def test_le_bulletin_est_anonymise_avant_d_etre_lu(config):
    cfg = config.model_copy(update={"identite": Identite(noms=["Jean Dupont"], adresses=["12 rue des Lilas"])})
    coffre = Coffre(None)
    an, ve = anonymiseurs(cfg, coffre)
    pages, n = anonymiser_pages(bulletin_recent(avec_identite=True), an, ve, "essai.pdf")
    texte = " ".join(w["text"] for p in pages for l in p["lignes"] for w in l)
    assert n >= 3 and "DUPONT" not in texte and "LILAS" not in texte and "082" not in texte
    assert "[PERSONNE_" in texte
    b = lire_bulletin(pages, "essai.pdf")                     # les lignes de paie sont intactes, à leur place
    assert [l.libelle for l in b.lignes][:2] == ["SALAIRE DE BASE", "PRIME D'ASSIDUITE"] and b.net_paye == 1461.0


# --- les comparaisons ----------------------------------------------------------------------------------------------

def bulletin(mois, lignes, cotis, net, impot=0.0, source="excel"):
    return Bulletin(mois=mois, lignes=[Ligne(l, m, nature_de(l)) for l, m in lignes], cotisations=cotis,
                    net_avant_impot=net, impot=impot, source=source)


def test_classeur_contre_bulletin():
    x = [bulletin("2026-01", [("Base", 2000), ("Frais trans", 20)], 400, 1580),
         bulletin("2026-02", [("Base", 2000), ("Frais trans", 30)], 400, 1630),
         bulletin("2026-03", [("Base", 2000)], 400, 1600)]
    p = [bulletin("2026-01", [("SALAIRE DE BASE", 2000), ("FRAIS TRANS", -20)], 400, 1580, source="pdf"),
         bulletin("2026-02", [("SALAIRE DE BASE", 2000), ("FRAIS TRANS A", 10), ("FRAIS TRANS B", 20)], 400, 1630, source="pdf"),
         bulletin("2026-03", [("SALAIRE DE BASE", 2000), ("CET", -50)], 400, 1550, source="pdf")]
    res = {r["mois"]: r for r in comparer(x, p)}
    assert "−20,00 € sur le bulletin" in res["2026-01"]["constats"][0] and not res["2026-01"]["grave"]
    assert "2026-02" not in res                                   # le même argent en deux lignes : rien à corriger
    assert res["2026-03"]["grave"] and any("« CET » (−50,00 €) est sur le bulletin" in c for c in res["2026-03"]["constats"])


# --- les analyses ----------------------------------------------------------------------------------------------------

@pytest.fixture
def config_paie(config, classeur, tmp_path):
    return config.model_copy(update={"paie": ConfigPaie(dossier=str(tmp_path / "vide"), classeur=str(classeur))})


@pytest.fixture
def donnees(config_paie):
    return charger(config_paie, Coffre(None))


def test_augmentation_avec_rappel(donnees):
    [a] = A.augmentations(donnees.emploi)
    assert a["mois"] == "2025-04" and a["effet"] == "2025-01" and a["mois_rappeles"] == 3 and a["pct"] == 2.0


def test_regles_et_treizieme(donnees):
    regles = {r["taux"]: r for r in A.regles_pourcentage(donnees.emploi)}
    assert set(regles) == {3.0, 5.0} and not regles[3.0]["absents"]
    t = A.treizieme(donnees.emploi)
    assert t["calendrier"] == {6: 0.5, 11: 0.4, 12: 0.1} and all(a["conforme"] for a in t["annees"])


def test_calendrier_et_mois_creux(donnees):
    cal = A.calendrier(donnees.emploi)
    assert {(h["mois"], h["nature"]) for h in cal["habitudes"]} >= {(4, "variable"), (6, "treizieme"), (11, "treizieme")}
    assert 1 in cal["mois_creux"] and 4 not in cal["mois_creux"] and cal["net_ordinaire"] > 0


def test_le_taux_neutre_et_un_changement_de_taux():
    bs = []
    for i, taux in enumerate([7.5, 13.8, 7.5, 5.9, 5.9, 5.9, 6.8, 6.8]):
        b = bulletin(f"2023-{i + 1:02d}", [("Base", 2000)], 400, 1600, impot=round(taux * 16, 2), source="pdf")
        b.taux_pas, b.net_imposable = taux, 1600.0
        bs.append(b)
    imp = A.impots(bs)
    assert imp["fin_grille"] == "2023-03"             # le dernier mois avant le taux personnel
    assert [(c["mois"], c["avant"], c["apres"]) for c in imp["changements"]] == [("2023-07", 5.9, 6.8)]


def test_pouvoir_d_achat(donnees):
    ipc = {"2024-01": 100.0, "2024-12": 102.0, "2025-12": 103.0}
    pa = A.pouvoir_achat(donnees.emploi, ipc, A.augmentations(donnees.emploi))
    assert pa["nominal"] == 2.0 and pa["prix"] == 3.0 and pa["base_qui_suit"] == 2060.0


def test_prevision(donnees):
    p = prevoir(donnees.emploi, hausse_janvier=1.0, hausse_avril=2.0)
    mois = {m["mois"]: m for m in p["mois"]}
    assert list(mois)[0] == "2026-01" and list(mois)[-1] == "2026-12"
    assert mois["2026-01"]["base"] == round(2040 * 1.01, 2)
    assert dict(mois["2026-04"]["extras"])["variable"] == 1500.0 and mois["2026-04"]["par_point"] > 0


def test_annonces(donnees):
    res = verifier(donnees.emploi, [{"mois": "2025-01", "augmentation": 2}, {"annee": 2025, "ligne": "variable", "montant": 1500},
                                    {"annee": 2025, "ligne": "variable", "montant": 1800}, {"annee": 2026, "ligne": "variable", "montant": 1}])
    assert [r["statut"] for r in res] == ["conforme", "conforme", "ecart", "attente"] and "rappel" in res[0]["constat"]


# --- les pages ----------------------------------------------------------------------------------------------------

@pytest.fixture
def analyse(config_paie, monkeypatch):
    monkeypatch.setattr("mas.paie.chargement.indices", lambda *a, **k: ({}, "indisponible"))      # pas de réseau
    return analyser(config_paie, Coffre(None))


def budget_factice(mois_debut=2025, nb=12):
    mois = [f"{mois_debut}-{m:02d}" for m in range(1, nb + 1)]
    return {"periode": {"debut": mois[0], "fin": mois[-1], "nb_mois": nb},
            "par_mois": {"mois": mois, "totaux": [1700.0 + (300 if m.endswith("-04") else 0) for m in mois], "partiels": []},
            "operations": [{"date": f"{m}-28", "libelle": "VIR SALAIRE EMPLOYEUR", "montant": mois_fictif(2025, int(m[5:]))["net_apres"],
                            "categorie": "revenu"} for m in mois if m != "2025-07"]}


def test_la_page_des_bulletins_et_ses_donnees(analyse):
    page_html = construire_page(analyse)
    assert "Tes fiches de paie" in page_html and "None" not in page_html and "« " not in page_html.split("<script")[0]
    paie = donnees_paie(analyse)
    assert paie["format"] == "mas-paie/1" and len(paie["bulletins"]) == 24 and paie["prevision"]
    json.dumps(paie)


def test_salaire_et_budget(analyse):
    c = croiser(budget_factice(), donnees_paie(analyse))
    assert c["debut"] == "2025-01" and c["fin"] == "2025-12" and len(c["mois"]) == 12
    assert c["primes"]["n"] == 4 and c["ordinaires"]["n"] == 8                  # avril, juin, novembre, décembre
    assert c["ordinaires"]["depenses"] == 1700 and c["primes"]["depenses"] == 1775
    r = c["rapprochement"]
    assert [m["mois"] for m in r["mois"] if m["recu"] is None] == ["2025-07"]
    assert len(c["venir"]) == 12 and c["venir"][0]["mois"] == "2026-01"
    page_html = page_croisee(c)
    assert "Ton salaire et ton budget" in page_html and "11 mois sur 12" in page_html and "None" not in page_html


def test_les_pages_sont_reliees(config_paie, tmp_path, monkeypatch):
    monkeypatch.setattr("mas.paie.chargement.indices", lambda *a, **k: ({}, "indisponible"))
    rapports = tmp_path / "rapports"
    rapports.mkdir()
    budget_json = rapports / "rapport_2026-01-01_1200.json"
    budget_json.write_text(json.dumps(budget_factice()))
    (rapports / "rapport_2026-01-01_1200.html").write_text('<style></style><main class="feuille"><div class="ruban"></div><h1>Budget</h1></main>')
    res = ecrire_pages(config_paie, Coffre(None), budget_json, rapports)
    assert set(res["pages"]) == {"budget", "paie", "croise"}
    budget_html = (rapports / "rapport_2026-01-01_1200.html").read_text()
    assert 'href="rapport_2026-01-01_1200_paie.html"' in budget_html and 'aria-current="page">Ton budget' in budget_html
    assert 'href="rapport_2026-01-01_1200.html"' in (rapports / "rapport_2026-01-01_1200_croise.html").read_text()
    relier(budget_json.with_suffix(""))                          # relier deux fois ne double pas le menu
    assert (rapports / "rapport_2026-01-01_1200.html").read_text().count('<nav class="rapports"') == 1
