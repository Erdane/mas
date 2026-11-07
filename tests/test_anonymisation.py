"""Anonymisation et vérification. Tous les exemples sont fictifs : noms courants, villes, numéros et
références inventés (IBAN, carte et NIR sont les exemples publics habituels)."""
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
        "M. Jean DUPONT, 8 rue des Lilas\n69001 Lyon\n"
        "| 03/01 | VIR SEPA PERMANENT M DUPONT JEAN LOYER | 700,00 | |\n"
        "| 05/01 | PRLV SEPA EDF CLIENTS PARTICULIERS | 80,00 | |\n"
        "| 07/01 | VIR INST A SOPHIE BERNARD RESTO | 25,00 | |\n"
        "Tél : 06 12 34 56 78 - jean.dupont@example.com - IBAN FR76 3000 6000 0112 3456 7890 189"
    )
    r = a.anonymiser(texte)
    for secret in ["DUPONT", "Lilas", "SOPHIE", "BERNARD", "06 12", "jean.dupont", "FR76"]:
        assert secret.lower() not in r.texte.lower(), (secret, r.texte)
    # Les marchands, montants et mots-clés restent lisibles
    for visible in ["EDF", "LOYER", "RESTO", "700,00", "VIR SEPA PERMANENT"]:
        assert visible in r.texte, visible
    # "Jean DUPONT" et "DUPONT JEAN" reçoivent le même pseudonyme
    assert len(set(re.findall(r"\[PERSONNE_1\]", r.texte))) == 1
    assert r.texte.count("[PERSONNE_1]") == 2
    # La dé-pseudonymisation locale restitue les vraies valeurs
    assert "SOPHIE BERNARD" in coffre.depseudonymiser(r.texte)


def test_verificateur_detecte_les_fuites(config):
    v = Verificateur(config.verification, [("Jean Dupont", "PERSON")])
    fuites = v.verifier("Virement de JEAN  DUPONT, carte 4111 1111 1111 1111", [])
    types = {f.entite for f in fuites}
    assert {"PERSON", "CREDIT_CARD"} <= types
    assert v.verifier("PRLV SEPA EDF 45,20 [PERSONNE_1]", []) == []


def test_nom_colle_par_la_banque(config):
    # Libellé compacté, sans espaces : le nom déclaré est collé aux mots voisins
    texte = "| 22/01 | VIRINSTJEANDUPONT VirementdepuisMaBanque | 3000,00 | |"
    v = Verificateur(config.verification, [("Jean Dupont", "PERSON"), ("Dupont Jean", "PERSON")])
    assert {f.entite for f in v.verifier(texte, [])} == {"PERSON"}
    a = Anonymiseur(config.anonymisation, Coffre(None), [("Jean Dupont", "PERSON"), ("Dupont Jean", "PERSON")])
    r = a.anonymiser(texte + "\n| 23/01 | VIRDUPONTJEAN | 10,00 | |")
    assert "dupont" not in r.texte.lower() and "VirementdepuisMaBanque" in r.texte, r.texte
    assert v.verifier(r.texte, []) == []
    # Un nom court n'est pas cherché collé : il se retrouverait dans des mots ordinaires
    assert Verificateur(config.verification, [("Léa Roy", "PERSON")]).verifier("CB ROYALEAROMES", []) == []


def test_nom_de_famille_seul(config):
    texte = ("| 30/01 | Virement automatique 1234567 DUPONT ech 150126 | 70,00 | |\n"
             "| 02/02 | CB jean.dupont@example.com | 5,00 | |")
    v = Verificateur(config.verification, [("Jean Dupont", "PERSON")])
    assert v.verifier("Virement automatique 1234567 DUPONT ech 150126", [])       # fuite repérée
    r = Anonymiseur(config.anonymisation, Coffre(None), [("Jean Dupont", "PERSON")]).anonymiser(texte)
    assert "dupont" not in r.texte.lower() and "Virement automatique 1234567" in r.texte, r.texte
    assert "[EMAIL" in r.texte                                                     # l'e-mail reste un e-mail
    assert v.verifier(r.texte, []) == []
    assert v.verifier("CB DUPONTEL SARL", []) == []                                # mot entier seulement


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


def test_noms_en_minuscules_ou_colles_et_lieux_de_retrait(config):
    a = Anonymiseur(config.anonymisation, Coffre(None))
    cas = {
        # libellé : (secrets qui doivent disparaître, mots qui doivent rester)
        "VIRSEPALucasMorel Virementde M RŁf:SCT0001": (["lucas", "morel"], ["VIRSEPA"]),   # « RŁf » : tel que lu dans le PDF
        "VIRINSTM.DURANDPAUL": (["durand", "paul"], []),
        "VIRDeblocagePret00012345678": ([], ["DeblocagePret"]),
        "Virement instantané émis 1a2b3c4 claire moreau exmpfrppxxx 15/01/2026": (["claire", "moreau"], ["15/01/2026"]),
        "Virement SEPA émis 1234567 thomas": (["thomas"], []),
        "Virement automatique 7654321 lucas 150126": (["lucas"], ["150126"]),
        "Virement SEPA reçu 2345678 mlle julie lambert 012026000001": (["julie", "lambert"], []),
        "Virement instantané reçu T000001 m antoine leroy 0a1b2c3d4e5f6789": (["antoine", "leroy"], []),
        # un organisme connu (liste des mots qui ne sont pas des noms) reste lisible
        "Virement SEPA reçu 3456789 engie france appointement": ([], ["engie france appointement"]),
        "Virement instantané émis 4567890 residence les acacias loyer": ([], ["residence", "loyer"]),
        "Carte 1111111 mr pierre roux le 04/02/26": (["pierre", "roux"], ["Carte 1111111"]),
        "Carte 2222222 emma fontaine le 19/01/26": (["emma", "fontaine"], []),
        "Carte 3333333 carrefour le 30/01/26": ([], ["carrefour"]),
        "RETRAITDAB24/05/26LYONCB*1234": (["lyon"], ["RETRAITDAB24/05/26", "CB*1234"]),
        "Retrait d'espèces à un DAB 5555555 bp quai exemple / carte 400000xxxxxx00": (["exemple"], ["Retrait d'espèces"]),
    }
    for libelle, (secrets, visibles) in cas.items():
        texte = a.anonymiser(libelle).texte
        for s in secrets:
            assert s not in texte.lower(), (libelle, texte)
        for v in visibles:
            assert v in texte, (libelle, texte)
    assert "[LIEU_" in a.anonymiser("RETRAITDAB14/02/26BORDEAUX CB*1234").texte


def test_nom_d_un_tiers_suivi_du_tien(config):
    # Certaines banques ajoutent ton nom à la fin d'un virement instantané : le nom du tiers reste masqué
    a = Anonymiseur(config.anonymisation, Coffre(None), [("Jean Dupont", "PERSON"), ("Dupont Jean", "PERSON")])
    texte = a.anonymiser("Virement instantané émis 5d6e7f8 marc lefevre jean dupont 21/03/2026 17:43:50 cet").texte
    assert "marc" not in texte and "lefevre" not in texte and "dupont" not in texte.lower(), texte
    assert texte.count("[PERSONNE_") == 2 and "21/03/2026" in texte
