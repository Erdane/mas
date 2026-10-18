"""Publication sur GitHub : vérification du dépôt, `mas init`, refus sans config.yaml (sans IA)."""
import subprocess

import yaml
from typer.testing import CliRunner

from mas.anonymisation import Coffre
from mas.cli import app
from mas.config import Config
from mas.depot import verifier


CLE_FACTICE = "sk-ant-" + "factice-0123456789abcdef"     # coupée : ce fichier ne déclenche pas l'alarme


def _git(dossier, *args):
    subprocess.run(["git", *args], cwd=dossier, check=True, capture_output=True)


def _depot(tmp_path):
    _git(tmp_path, "init", "-q")
    (tmp_path / ".gitignore").write_text("config.yaml\n.env\n", encoding="utf-8")
    (tmp_path / "config.yaml").write_text(               # coffre absent : jamais celui de ~/.mas
        f"identite: {{noms: [Aline Verdier]}}\ncoffre: {{chemin: '{tmp_path / 'absent.bin'}'}}\n", encoding="utf-8")
    (tmp_path / ".env").write_text(f"ANTHROPIC_API_KEY={CLE_FACTICE}\nLLM_MODEL=anthropic/claude-opus-5-5\n",
                                   encoding="utf-8")
    (tmp_path / "propre.py").write_text("print('rien de personnel')\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text("ligne 1\nVir à  aline VERDÍER\n", encoding="utf-8")
    (tmp_path / "donnees.py").write_text("IBAN = 'FR7630006000011234567890189'\n", encoding="utf-8")
    (tmp_path / "exemple.py").write_text(f"cle = '{CLE_FACTICE}'\nmodele = 'anthropic/claude-opus-5-5'\n",
                                         encoding="utf-8")
    return tmp_path


def _config(tmp_path, coffre=None):
    return Config.model_validate({
        "identite": {"noms": ["Aline Verdier"], "ibans": ["FR76 3000 6000 0112 3456 7890 189"]},
        "coffre": {"chemin": str(coffre or tmp_path / "pas_de_coffre.bin")},
    })


def test_donnees_trouvees_sans_afficher_les_valeurs(tmp_path):
    depot = _depot(tmp_path)
    (depot / "releves").mkdir()
    (depot / "releves" / "notes.txt").write_text("rien\n", encoding="utf-8")
    _git(depot, "add", "-f", "releves/notes.txt")                # forcé malgré tout

    problemes, _ = verifier(depot, _config(tmp_path))
    trouves = {(p.fichier, p.ligne, p.motif) for p in problemes}
    assert ("notes.md", 2, "identite.noms") in trouves             # casse, accents et espaces ignorés
    assert ("notes.md", 2, "identite.noms (un mot)") in trouves    # le nom de famille seul
    assert ("donnees.py", 1, "identite.ibans") in trouves          # IBAN écrit sans espaces
    assert ("exemple.py", 1, ".env ANTHROPIC_API_KEY") in trouves
    assert ("exemple.py", 1, "clé d'API") in trouves
    assert not any(p.motif == ".env LLM_MODEL" for p in problemes)   # un nom de modèle n'est pas un secret
    assert ("releves/notes.txt", None, "dossier de données personnelles") in trouves
    assert not {p.fichier for p in problemes} & {"propre.py", "config.yaml", ".env"}
    assert all("Verdier" not in p.motif and "FR76" not in p.motif for p in problemes)


def test_valeurs_du_coffre_et_fichiers_indexes_seulement(tmp_path):
    depot = _depot(tmp_path)
    chemin = tmp_path / "coffre" / "coffre.bin"
    coffre = Coffre(chemin)
    coffre.valeurs.update({"PERSONNE_3": "Lucie Martin", "PERSONNE_4": "Livret A", "PERSONNE_5": "Page"})
    coffre.sauvegarder()
    (depot / "test_x.py").write_text("libelle = 'VIR LUCIE MARTIN'\ncompte = 'LIVRET A'\n# Page 2\n",
                                     encoding="utf-8")
    _git(depot, "add", "test_x.py", "propre.py")

    problemes, avertissements = verifier(depot, _config(tmp_path, chemin), indexes=True)
    assert avertissements == []
    assert {(p.fichier, p.ligne, p.motif) for p in problemes} == {("test_x.py", 1, "coffre PERSONNE_3")}


def test_commande_check_repo(tmp_path, monkeypatch):
    depot = _depot(tmp_path)
    monkeypatch.chdir(depot)
    resultat = CliRunner().invoke(app, ["check-repo"])
    assert resultat.exit_code == 1 and "notes.md" in resultat.output and "Verdier" not in resultat.output
    for f in ("notes.md", "donnees.py", "exemple.py"):
        (depot / f).unlink()
    resultat = CliRunner().invoke(app, ["check-repo"])
    assert resultat.exit_code == 0, resultat.output


def test_init_prepare_le_dossier_sans_rien_ecraser(tmp_path, monkeypatch):
    import spacy.util

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(spacy.util, "is_package", lambda nom: True)
    resultat = CliRunner().invoke(app, ["init"])
    assert resultat.exit_code == 0, resultat.output
    assert "identite" in yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    assert "ANTHROPIC_API_KEY=" in (tmp_path / ".env").read_text(encoding="utf-8")
    assert (tmp_path / "releves").is_dir() and (tmp_path / "rapports").is_dir()

    (tmp_path / "config.yaml").write_text("llm: {modele: anthropic/claude-opus-5-5}\n", encoding="utf-8")
    assert CliRunner().invoke(app, ["init"]).exit_code == 0
    assert "opus" in (tmp_path / "config.yaml").read_text(encoding="utf-8")


def test_analyser_refuse_sans_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for commande in ("analyser", "anonymiser"):
        resultat = CliRunner().invoke(app, [commande, "releves"])
        assert resultat.exit_code == 1 and "mas init" in resultat.output
