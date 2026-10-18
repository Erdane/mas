"""Interface en ligne de commande : `mas --help`."""

from __future__ import annotations

import atexit
import logging
import time
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.logging import RichHandler
from rich.markdown import Markdown
from rich.table import Table

from .config import charger_config

app = typer.Typer(help="Anonymise des PDF en local puis les fait analyser par des agents LLM.",
                  no_args_is_help=True)
console = Console()
OptionConfig = typer.Option(None, "--config", "-c", help="Chemin de config.yaml")


@app.callback()
def _avant_chaque_commande() -> None:
    # Clés d'API (ANTHROPIC_API_KEY…) lues dans le .env du dossier courant, comme config.yaml ;
    # une variable déjà définie dans le terminal reste prioritaire.
    load_dotenv(Path(".env"), override=False)


class UneFoisParMessage(logging.Filter):
    """Laisse passer chaque message une seule fois par exécution et compte les répétitions."""

    def __init__(self) -> None:
        super().__init__()
        self.vus: dict[tuple[str, int, str], int] = {}

    def filter(self, record: logging.LogRecord) -> bool:
        cle = (record.name, record.levelno, record.getMessage())
        self.vus[cle] = self.vus.get(cle, 0) + 1
        return self.vus[cle] == 1

    def repetitions(self) -> list[tuple[str, int]]:
        """(message, nombre de fois où il a été masqué) pour chaque message répété."""
        return [(message, n - 1) for (_, _, message), n in self.vus.items() if n > 1]


def _resume_repetitions(filtre: UneFoisParMessage) -> None:
    repetitions = filtre.repetitions()
    if not repetitions:
        return
    total = sum(n for _, n in repetitions)
    console.print(f"[dim]{total} message(s) répété(s) masqué(s), affichés une seule fois :[/dim]")
    for message, n in repetitions:
        console.print(f"[dim]  ×{n}  {message[:110]}[/dim]", highlight=False)


def _logs(verbeux: bool, progression: bool = False) -> None:
    filtre = UneFoisParMessage()
    gestionnaire = RichHandler(console=console, show_path=False)
    gestionnaire.addFilter(filtre)
    logging.basicConfig(
        level=logging.INFO if verbeux else logging.WARNING,
        format="%(message)s", handlers=[gestionnaire],
    )
    logging.getLogger("mas").setLevel(logging.INFO)
    # Avancement page par page de l'analyse : seulement pour `analyser` (trop bavard pendant GEPA)
    logging.getLogger("mas.progression").setLevel(logging.INFO if progression else logging.WARNING)
    # « Loaded recognizer… », « Created NLP engine… » : détail interne de Presidio, sans intérêt ici
    logging.getLogger("presidio-analyzer").setLevel(logging.WARNING)
    atexit.register(_resume_repetitions, filtre)


def _resume_analyse(conso, duree_anonymisation: float, duree_analyse: float, reponses_cache: int) -> None:
    from .suivi import duree_lisible, montant_lisible, nombre_lisible

    table = Table(title="Résumé du traitement", show_header=False, title_justify="left")
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Anonymisation (sur ton PC)", duree_lisible(duree_anonymisation))
    table.add_row("Analyse par l'IA", duree_lisible(duree_analyse))
    for c in conso:
        table.add_row("Appels à l'IA", f"{c.appels} ({c.modele})")
        table.add_row("Tokens", f"{nombre_lisible(c.tokens_entree)} en entrée · "
                                f"{nombre_lisible(c.tokens_sortie)} en sortie")
        table.add_row("Coût estimé", montant_lisible(c.cout_usd) if c.cout_usd is not None
                      else "tarif inconnu pour ce modèle")
    if not conso:
        table.add_row("Appels à l'IA", "aucun appel facturé")
    if reponses_cache:
        table.add_row("Réponses du cache", f"{reponses_cache} (déjà calculées, non facturées)")
    console.print(table)
    console.print("[dim]Coût estimé d'après les tarifs publics du fournisseur ; sa console fait foi.[/dim]")


def _config_personnelle(chemin: Path | None):
    """Sans config.yaml, mas ne connaît ni ton identité ni ton modèle : on s'arrête plutôt que de
    traiter tes relevés avec des réglages par défaut."""
    if chemin is None and not Path("config.yaml").exists():
        console.print("[red]Pas de config.yaml dans ce dossier.[/red] Lance [bold]mas init[/bold] ici "
                      "(ou indique ta configuration avec -c chemin/config.yaml).")
        raise typer.Exit(1)
    return charger_config(chemin)


def _modele_exemple(nom: str) -> Path | None:
    """Fichier d'exemple : dans le dossier courant, sinon celui livré avec mas."""
    paquet = Path(__file__).resolve().parent
    for chemin in (Path(nom), paquet / "exemples" / nom, paquet.parents[1] / nom):
        if chemin.is_file():
            return chemin
    return None


def _resume(docs) -> None:
    table = Table(title="Anonymisation locale")
    table.add_column("Document")
    table.add_column("Pages", justify="right")
    table.add_column("Remplacements", justify="right")
    for d in docs:
        table.add_row(d.nom, str(len(d.pages)), str(d.nb_remplacements))
    console.print(table)


@app.command()
def init(config: Path = typer.Option(Path("config.yaml"), "--config", "-c", help="config.yaml à créer")):
    """Prépare le dossier : config.yaml et .env (sans écraser), releves/, rapports/, modèle spaCy."""
    import os
    import shutil
    import subprocess
    import sys

    for cible, nom in ((config, "config.example.yaml"), (Path(".env"), ".env.example")):
        if cible.exists():
            console.print(f"[dim]{cible} existe déjà : je n'y touche pas.[/dim]")
            continue
        modele = _modele_exemple(nom)
        if modele is None:
            console.print(f"[yellow]{nom} introuvable : crée {cible} à la main.[/yellow]")
            continue
        shutil.copyfile(modele, cible)
        try:
            os.chmod(cible, 0o600)          # ton identité et tes clés : lisibles par toi seul
        except OSError:
            pass
        console.print(f"[green]{cible} créé[/green] à partir de {nom}")
    for dossier in ("releves", "rapports"):
        Path(dossier).mkdir(exist_ok=True)
    console.print("Dossiers [bold]releves/[/bold] (tes PDF) et [bold]rapports/[/bold] prêts ; git les ignore.")

    import spacy.util

    modele_spacy = charger_config(config if config.exists() else None).anonymisation.modele_spacy
    if spacy.util.is_package(modele_spacy):
        console.print(f"Modèle spaCy {modele_spacy} : déjà installé.")
    elif subprocess.run([sys.executable, "-m", "spacy", "download", modele_spacy]).returncode != 0:
        console.print(f"[yellow]Téléchargement de {modele_spacy} impossible : réessaie avec "
                      f"python -m spacy download {modele_spacy}[/yellow]")
    console.print(
        "\n[bold]Il te reste :[/bold]\n"
        f"  1. {config} : renseigne « identite » (noms, adresse, IBAN…) et choisis le modèle dans « llm » ;\n"
        "  2. .env : colle ta clé d'API ;\n"
        "  3. dépose tes relevés PDF dans releves/, puis lance : mas analyser releves/"
    )


@app.command("check-repo")
def check_repo(
    indexes: bool = typer.Option(False, "--staged", help="Seulement les fichiers prêts à être commités"),
    config: Path = OptionConfig,
):
    """Vérifie qu'aucun fichier personnel ni aucune de tes données ne partirait sur GitHub."""
    import subprocess

    from .depot import verifier

    try:
        problemes, avertissements = verifier(Path.cwd(), charger_config(config), indexes)
    except (subprocess.CalledProcessError, FileNotFoundError):
        console.print("[red]Ce dossier n'est pas un dépôt git (ou git est absent).[/red]")
        raise typer.Exit(2)
    for a in avertissements:
        console.print(f"[yellow]{a}[/yellow]")
    if not problemes:
        console.print("[green]Rien de personnel dans les fichiers que git publierait.[/green]")
        return
    table = Table(title="À retirer avant de publier (les valeurs ne sont pas affichées)")
    table.add_column("Fichier")
    table.add_column("Ligne", justify="right")
    table.add_column("Ce qui a été trouvé")
    for p in problemes:
        table.add_row(p.fichier, str(p.ligne or "—"), p.motif)
    console.print(table)
    console.print("[red]Corrige ces fichiers, ou retire-les avec git rm --cached, avant de commiter.[/red]")
    raise typer.Exit(1)


@app.command()
def anonymiser(
    entree: Path = typer.Argument(..., help="PDF, ZIP de PDF ou dossier"),
    sortie: Path = typer.Option(Path("sortie_anonyme"), help="Dossier des textes anonymisés"),
    config: Path = OptionConfig,
):
    """Anonymise uniquement (rien n'est envoyé). Permet de relire avant l'analyse."""
    cfg = _config_personnelle(config)
    from .orchestrateur import FuiteBloquante, Orchestrateur

    _logs(False)
    try:
        docs = Orchestrateur(cfg).charger_documents(entree)
    except FuiteBloquante as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    sortie.mkdir(parents=True, exist_ok=True)
    for d in docs:
        (sortie / f"{Path(d.nom).stem}.txt").write_text(
            "\n\n--- page ---\n\n".join(d.pages), encoding="utf-8"
        )
    _resume(docs)
    console.print(f"Textes anonymisés écrits dans [bold]{sortie}[/bold]. Relis-les avant d'analyser.")


@app.command()
def analyser(
    entree: Path = typer.Argument(..., help="PDF, ZIP de PDF ou dossier"),
    sortie: Path = typer.Option(Path("rapports/rapport.md"), help="Rapport final (avec les vrais noms)"),
    oui: bool = typer.Option(False, "--oui", "-y", help="Ne pas demander confirmation avant l'envoi"),
    config: Path = OptionConfig,
):
    """Anonymise, vérifie, puis fait analyser par les agents LLM."""
    cfg = _config_personnelle(config)
    from .orchestrateur import FuiteBloquante, Orchestrateur

    _logs(True, progression=True)
    orchestrateur = Orchestrateur(cfg)
    debut = time.perf_counter()
    try:
        docs = orchestrateur.charger_documents(entree)
    except FuiteBloquante as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    duree_anonymisation = time.perf_counter() - debut
    _resume(docs)

    extrait = docs[0].pages[0][:800] if docs and docs[0].pages else ""
    console.print("[dim]Extrait de ce qui sera envoyé :[/dim]")
    console.print(extrait, highlight=False)
    nb_pages = sum(len(d.pages) for d in docs)
    if not oui and not typer.confirm(
        f"\nEnvoyer {nb_pages} page(s) pseudonymisée(s) à {cfg.llm.modele} ?"
    ):
        raise typer.Exit(0)

    import dspy
    from dspy.utils.exceptions import LMError

    from .page import donnees_rapport, ecrire_pages
    from .suivi import consommation

    console.print(f"\n[bold]Analyse en cours[/bold] ({nb_pages} page(s), {cfg.llm.modele}) : "
                  "chaque étape s'affiche ci-dessous.")
    debut = time.perf_counter()
    # Ne compte que les appels réellement facturés (pas les réponses servies par le cache DSPy)
    with dspy.track_usage() as compteur:
        try:
            resultat = orchestrateur.analyser(docs)
        except LMError as e:
            console.print(f"[red]L'appel à l'IA a échoué : {e}[/red]\n"
                          "Vérifie la clé dans .env, le crédit de ton compte et le nom du modèle "
                          "dans config.yaml.")
            raise typer.Exit(1)
    duree_analyse = time.perf_counter() - debut
    conso = consommation(compteur.usage_data)
    appels_factures = sum(c.appels for c in conso)
    # L'historique du LM garde aussi les réponses servies par le cache : la différence les compte
    reponses_cache = max(0, len(getattr(orchestrateur.lm, "history", [])) - appels_factures)
    sortie_anonyme = sortie.with_name(sortie.stem + "_anonyme.md")
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text(resultat.rapport, encoding="utf-8")
    sortie_anonyme.write_text(resultat.rapport_anonyme, encoding="utf-8")
    couts = [c.cout_usd for c in conso]
    traitement = {
        "modele": cfg.llm.modele,
        "duree_anonymisation": round(duree_anonymisation, 1),
        "duree_analyse": round(duree_analyse, 1),
        "appels": appels_factures,
        "reponses_cache": reponses_cache,
        "tokens_entree": sum(c.tokens_entree for c in conso),
        "tokens_sortie": sum(c.tokens_sortie for c in conso),
        "cout_usd": None if None in couts else sum(couts),     # None : tarif inconnu d'un modèle
    }
    alertes = list(resultat.analyse.alertes_extraction)
    donnees = donnees_rapport(resultat.budget, resultat.analyse.classements, resultat.commentaire,
                              alertes, traitement)
    html, html_anonyme, _ = ecrire_pages(sortie, donnees, orchestrateur.coffre.valeurs)
    for message in donnees["controles"]:
        console.print(f"[yellow]⚠ {message}[/yellow]")
    if len(alertes) > len(donnees["controles"]):
        console.print(f"[yellow]{len(alertes) - len(donnees['controles'])} page(s) avec des "
                      "incohérences d'extraction non résolues : vérifie le rapport.[/yellow]")
    console.print(Markdown(resultat.rapport))
    console.print(f"\nRapport écrit dans [bold]{sortie}[/bold] et [bold]{html}[/bold] "
                  f"(version anonyme : {sortie_anonyme}, {html_anonyme})\n")
    _resume_analyse(conso, duree_anonymisation, duree_analyse, reponses_cache)


@app.command()
def exporter(
    rapport: Path = typer.Argument(..., help="Rapport à reconvertir (ex. rapport.md)"),
    config: Path = OptionConfig,
):
    """Régénère les pages HTML d'un rapport existant (sans rappeler l'IA)."""
    import json

    base = rapport.with_name(rapport.stem.removesuffix("_anonyme") + rapport.suffix)
    donnees_json = base.with_suffix(".json")
    if donnees_json.exists():
        from .anonymisation import Coffre
        from .page import ecrire_pages

        donnees = json.loads(donnees_json.read_text(encoding="utf-8"))
        valeurs = Coffre(charger_config(config).coffre.chemin).valeurs
        html, html_anonyme, _ = ecrire_pages(base, donnees, valeurs, ecrire_donnees=False)
        console.print(f"Pages régénérées : [bold]{html}[/bold] et [bold]{html_anonyme}[/bold]")
        return

    # Rapport produit avant la page interactive : pas de données, on met en page le Markdown
    from .export import ecrire_html

    if not rapport.exists():
        console.print(f"[red]Fichier introuvable : {rapport}[/red]")
        raise typer.Exit(1)
    html = ecrire_html(rapport, rapport.read_text(encoding="utf-8"), anonyme="_anonyme" in rapport.stem)
    console.print(f"HTML écrit dans [bold]{html}[/bold] (mise en page simple : pas de {donnees_json.name})")


@app.command()
def generer(
    n: int = typer.Option(10, help="Nombre de relevés"),
    sortie: Path = typer.Option(Path("donnees/synthetiques"), help="Dossier de sortie"),
    graine: int = typer.Option(0, help="Graine de départ"),
):
    """Génère des relevés synthétiques (PDF + vérité terrain JSON)."""
    from .synthetique import generer_jeu

    chemins = generer_jeu(sortie, n, graine)
    console.print(f"{len(chemins)} relevés générés dans [bold]{sortie}[/bold]")


@app.command()
def optimiser(
    regenerer: bool = typer.Option(False, help="Régénérer les relevés synthétiques"),
    config: Path = OptionConfig,
):
    """Optimise les agents avec GEPA sur des données synthétiques."""
    from .optimisation.gepa import optimiser as lancer

    _logs(True)
    resultat = lancer(charger_config(config), regenerer=regenerer)
    console.print(
        f"Score validation : {resultat['score_initial']:.2f} → [bold green]"
        f"{resultat['score_final']:.2f}[/bold green]\nProgramme sauvegardé : {resultat['programme']}"
    )


@app.command()
def evaluer(config: Path = OptionConfig):
    """Évalue le programme courant (optimisé s'il existe) sur le jeu de validation."""
    from .agents import configurer_lm
    from .optimisation import construire_jeux
    from .optimisation.gepa import evaluer as lancer
    from .orchestrateur import Orchestrateur

    _logs(True)
    cfg = charger_config(config)
    configurer_lm(cfg.llm)
    _, val = construire_jeux(cfg)
    programme = Orchestrateur(cfg).programme()
    console.print(f"Score : [bold]{lancer(programme, val, cfg.optimisation.threads):.2f}[/bold]")


@app.command()
def coffre(config: Path = OptionConfig):
    """Affiche la table des pseudonymes (en local uniquement)."""
    from .anonymisation import Coffre

    c = Coffre(charger_config(config).coffre.chemin)
    table = Table(title="Coffre de pseudonymisation")
    table.add_column("Pseudonyme")
    table.add_column("Valeur réelle")
    for jeton, valeur in sorted(c.valeurs.items()):
        table.add_row(f"[{jeton}]", valeur)
    console.print(table)


if __name__ == "__main__":
    app()
