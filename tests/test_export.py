"""Export HTML du rapport et chargement du .env (sans clé API ni réseau)."""
import os

from typer.testing import CliRunner

from mas.cli import app
from mas.export import markdown_vers_html

RAPPORT = """# Analyse budgétaire

Constat : **excédent** de 844,50 € par mois. <script>alert("piège")</script>
[lien piégé](javascript:alert(1))

| Indicateur | Montant |
|---|---:|
| Revenus | 2 355,26 € |
"""


def test_html_autonome_lisible_et_sans_html_injecte():
    page = markdown_vers_html(RAPPORT)
    assert page.startswith("<!doctype html>") and '<html lang="fr">' in page
    assert "<h1>Analyse budgétaire</h1>" in page and "<strong>excédent</strong>" in page
    assert '<div class="tableau"><table>' in page and 'style="text-align:right"' in page
    assert "<script>" not in page and "&lt;script&gt;" in page    # HTML brut neutralisé
    assert 'href="javascript:' not in page
    assert "http://" not in page and "https://" not in page       # aucune ressource externe
    assert "données personnelles" in page                          # bandeau de la version réelle
    assert "Version anonyme" in markdown_vers_html(RAPPORT, anonyme=True)


def test_commande_exporter_et_chargement_du_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("MAS_TEST_VARIABLE=depuis-le-env\n", encoding="utf-8")
    (tmp_path / "rapport_anonyme.md").write_text(RAPPORT, encoding="utf-8")
    try:
        resultat = CliRunner().invoke(app, ["exporter", "rapport_anonyme.md"])
        assert resultat.exit_code == 0, resultat.output
        page = (tmp_path / "rapport_anonyme.html").read_text(encoding="utf-8")
        assert "Version anonyme" in page                           # détectée d'après le nom
        assert os.environ["MAS_TEST_VARIABLE"] == "depuis-le-env"
        assert CliRunner().invoke(app, ["exporter", "absent.md"]).exit_code == 1
    finally:
        os.environ.pop("MAS_TEST_VARIABLE", None)
