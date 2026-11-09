"""Livrets : leur type d'après le titre du relevé, le bilan versé / repris / intérêts, et son affichage (sans IA).
Valeurs inventées : comptes, montants et dates ne correspondent à aucun relevé réel."""
from mas.orchestrateur import DocumentAnonymise, OperationAnonyme, bilan_livrets, livrets_markdown
from mas.page import construire_page, donnees_rapport
from mas.releve import type_de_compte


def test_type_du_livret_sans_numero_ni_nom():
    assert type_de_compte("LIVRET A N° 00000000000 M. JEAN DUPONT") == "Livret A"
    assert type_de_compte("LDD N° 999") == "LDDS"
    assert type_de_compte("LEP N° 42") == "LEP"
    assert type_de_compte("Livret d'Épargne Pop.") == "LEP"
    assert type_de_compte("COMPTE SUR LIVRET") == "Livret"
    assert type_de_compte("LIVRET AGRICOLE") == "Livret"          # « A » doit être un mot à lui seul
    assert type_de_compte("COMPTE EPARGNE LOGEMENT") == "CEL"
    assert type_de_compte("PLAN EPARGNE EN ACTIONS") == "PEA"


def _releve(ops, comptes):
    return DocumentAnonymise("r", [], operations=[OperationAnonyme(d, l, m, c) for d, l, m, c in ops], comptes=comptes)


COURANT = {"type": "Compte courant", "solde_debut": None, "solde_fin": None}


def test_bilan_par_livret_sur_plusieurs_releves():
    mars = _releve([("2030-03-04", "VIR VERS LEP", -250.0, 0), ("2030-03-04", "VIR DEPUIS COMPTE", 250.0, 1),
                    ("2030-03-02", "INTERETS 2029", 31.25, 1), ("2030-03-21", "VIR VERS COMPTE", -700.0, 1),
                    ("2030-03-14", "VIR DEPUIS COMPTE", 60.0, 2)],
                   [COURANT, {"type": "LEP", "solde_debut": ["2030-03-01", 1500.0], "solde_fin": ["2030-03-31", 1081.25]},
                    {"type": "CEL", "solde_debut": None, "solde_fin": None}])
    avril = _releve([("2030-04-09", "VIR DEPUIS COMPTE", 150.0, 1)],
                    [COURANT, {"type": "LEP", "solde_debut": ["2030-04-01", 1081.25], "solde_fin": ["2030-04-30", 1231.25]}])
    lep, cel = bilan_livrets([mars, avril])
    assert (lep["verse"], lep["retire"], lep["interets"]) == (400.0, 700.0, 31.25)
    assert lep["bilan"] == -268.75                                          # 400 − 700 + 31,25 : une perte
    assert lep["solde_debut"] == {"date": "2030-03-01", "montant": 1500.0}
    assert lep["solde_fin"] == {"date": "2030-04-30", "montant": 1231.25}
    assert lep["ecart_soldes"] is None                                      # 1 231,25 − 1 500 = −268,75 : juste
    assert lep["mois"] == [{"mois": "2030-03", "verse": 250.0, "retire": 700.0},
                           {"mois": "2030-04", "verse": 150.0, "retire": 0.0}]
    assert cel["bilan"] == 60.0 and cel["solde_debut"] is None


def test_le_livret_a_passe_en_premier():
    r = _releve([("2030-05-06", "VIR DEPUIS COMPTE", 900.0, 1), ("2030-05-06", "VIR DEPUIS COMPTE", 20.0, 2)],
                [COURANT, {"type": "LEP", "solde_debut": None, "solde_fin": None},
                 {"type": "Livret A", "solde_debut": None, "solde_fin": None}])
    assert [b["nom"] for b in bilan_livrets([r])] == ["Livret A", "LEP"]   # même s'il a moins bougé


def test_ecart_avec_les_soldes_imprimes_signale():
    r = _releve([("2030-06-03", "VIR DEPUIS COMPTE", 40.0, 1)],
                [COURANT, {"type": "LEP", "solde_debut": ["2030-06-01", 800.0], "solde_fin": ["2030-06-30", 910.0]}])
    assert bilan_livrets([r])[0]["ecart_soldes"] == 70.0


def test_sections_texte_et_page():
    livrets = [{"nom": "LEP", "verse": 400.0, "retire": 700.0, "interets": 31.25, "bilan": -268.75,
                "solde_debut": {"date": "2030-03-01", "montant": 1500.0}, "solde_fin": {"date": "2030-04-30", "montant": 1231.25},
                "ecart_soldes": None, "mois": [{"mois": "2030-03", "verse": 250.0, "retire": 700.0}]}]
    texte = livrets_markdown(livrets).replace(" ", " ")
    assert "## Tes livrets" in texte and "| LEP |" in texte and "**−268,75 €**" in texte
    assert "tu en as repris 268,75 € de plus que tu n'y as mis" in texte and "le 1 mars 2030" in texte
    budget = {"nb_mois": 2, "periode": "2030-03 → 2030-04", "revenus_mensuels": 2000, "depenses_mensuelles": 1500,
              "par_categorie": {}, "par_nature": {}, "total_obligatoire": 0, "total_optionnel": 0,
              "reste_apres_obligatoire": 2000}
    page = construire_page(donnees_rapport(budget, [], "", livrets=livrets))
    section = page.split('<section class="livrets"', 1)[1].split("</section>", 1)[0]
    assert "Tes livrets" in section and 'class="lv-bilan perte"' in section and "Intérêts" in section
    assert "mars 2030" in section                                           # le mois par mois
    assert 'class="livrets"' not in construire_page(donnees_rapport(budget, [], ""))   # sans livret : rien
