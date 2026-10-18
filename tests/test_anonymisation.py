import re

from mas.anonymisation import Anonymiseur, Coffre
from mas.anonymisation.validateurs import iban_valide, luhn_valide, nir_valide, rib_valide
from mas.verification import Verificateur


def test_validateurs():
    assert iban_valide("FR76 3000 6000 0112 3456 7890 189")
    assert not iban_valide("FR76 3000 6000 0112 3456 7890 188")
    assert luhn_valide("4111 1111 1111 1111")
    assert not luhn_valide("4111 1111 1111 1112")
    assert rib_valide("30006", "00001", "12345678901", "89")
    assert nir_valide("1 85 05 78 006 084 91")


def test_pseudonymes_coherents(config):
    coffre = Coffre(None)
    a = Anonymiseur(config.anonymisation, coffre, [("Jean Dupont", "PERSON")])
    texte = (
        "M. Jean DUPONT, 8 rue des Tilleuls\n81000 Albi\n"
        "| 03/01 | VIR SEPA PERMANENT M DUPONT JEAN LOYER | 700,00 | |\n"
        "| 05/01 | PRLV SEPA EDF CLIENTS PARTICULIERS | 80,00 | |\n"
        "| 07/01 | VIR INST A ODILE LECLERC RESTO | 25,00 | |\n"
        "Tél : 06 12 34 56 78 - jean.dupont@mail.fr - IBAN FR76 3000 6000 0112 3456 7890 189"
    )
    r = a.anonymiser(texte)
    for secret in ["DUPONT", "Tilleuls", "ODILE", "LECLERC", "06 12", "jean.dupont", "FR76"]:
        assert secret.lower() not in r.texte.lower(), (secret, r.texte)
    # Les marchands, montants et mots-clés restent lisibles
    for visible in ["EDF", "LOYER", "RESTO", "700,00", "VIR SEPA PERMANENT"]:
        assert visible in r.texte, visible
    # "Jean DUPONT" et "DUPONT JEAN" reçoivent le même pseudonyme
    assert len(set(re.findall(r"\[PERSONNE_1\]", r.texte))) == 1
    assert r.texte.count("[PERSONNE_1]") == 2
    # La dé-pseudonymisation locale restitue les vraies valeurs
    assert "ODILE LECLERC" in coffre.depseudonymiser(r.texte)


def test_verificateur_detecte_les_fuites(config):
    v = Verificateur(config.verification, [("Jean Dupont", "PERSON")])
    fuites = v.verifier("Virement de JEAN  DUPONT, carte 4111 1111 1111 1111", [])
    types = {f.entite for f in fuites}
    assert {"PERSON", "CREDIT_CARD"} <= types
    assert v.verifier("PRLV SEPA EDF 45,20 [PERSONNE_1]", []) == []


def test_aucune_fuite_sur_les_releves_synthetiques(jeu_anonymise):
    for d in jeu_anonymise:
        texte = re.sub(r"\s", "", " ".join(d["pages"])).lower()
        for pii in d["pii"]:
            assert re.sub(r"\s", "", pii).lower() not in texte, (d["nom"], pii)
        for r in d["recurrents"]:
            assert r["motif"] in " ".join(d["pages"]), (d["nom"], r["motif"])


def test_coffre_chiffre(tmp_path, monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setenv("MAS_CLE_COFFRE", Fernet.generate_key().decode())
    chemin = tmp_path / "coffre.bin"
    c = Coffre(chemin)
    jeton = c.pseudonyme("PERSON", "Jean Dupont")
    c.sauvegarder()
    assert b"Dupont" not in chemin.read_bytes()
    assert Coffre(chemin).depseudonymiser(jeton) == "Jean Dupont"


def test_dates_et_livrets_ne_sont_pas_masques(config):
    a = Anonymiseur(config.anonymisation, Coffre(None))
    for texte in ["| 08.04 08.04 13.04 13.04 13.04 |", "01.08.26 01.08", "Livret A", "LDD Développement Durable et Solidaire"]:
        assert a.anonymiser(texte).texte == texte, texte
    assert "[TELEPHONE_" in a.anonymiser("Tél : 06 12 34 56 78").texte


def test_faux_positifs_du_coffre_ignores_par_le_verificateur():
    from mas.anonymisation.reconnaisseurs import MOTS_NON_NOMS
    from mas.anonymisation.reconnaisseurs import valeur_plausible as _valeur_plausible
    communs = {m.upper() for m in MOTS_NON_NOMS}
    assert not _valeur_plausible("08.04 08.04 13", communs)       # suite de dates d'une ancienne analyse
    assert not _valeur_plausible("04 13.04 13.04", communs)
    assert not _valeur_plausible("Livret A", communs)
    assert _valeur_plausible("Jean Dupont", communs)
    assert _valeur_plausible("06.12.34.56.78", communs) and _valeur_plausible("06 12 34 56 78", communs)
