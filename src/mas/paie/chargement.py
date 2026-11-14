"""Le chargement des bulletins : les PDF du dossier (`paie.dossier`), anonymisés avant d'être lus, puis le classeur
(`paie.classeur`) pour les mois sans PDF. Pour un mois présent des deux côtés, le PDF fait foi
(`paie.source_preferee`), et les deux sont comparés."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from . import analyses as A
from .anonymisation import anonymiser_libelle, anonymiser_pages, anonymiseurs
from .annonces import verifier
from .controles import comparer, ecarts_internes
from .excel import lire_classeur, verifier_classeur
from .inflation import indices
from .modeles import Bulletin
from .pdf import Colonnes, extraire_pages, lire_bulletin
from .prevision import prevoir

log = logging.getLogger(__name__)
CACHE_PRIX = Path("~/.mas/ipc.json").expanduser()


@dataclass
class Donnees:
    bulletins: list[Bulletin]                 # un par mois, toutes sources confondues
    emploi: list[Bulletin]                    # les mois de l'emploi actuel
    avant: list[Bulletin]                     # avant (stage…)
    classeur: list[Bulletin]
    pdfs: list[Bulletin]
    pdf_ignores: list[str]
    differences: list[dict]                   # classeur ≠ bulletin
    ecarts: list[dict]                        # lignes ≠ net
    formules: list[dict]                      # ce que les formules du classeur calculent de travers
    remplacements: int                        # données personnelles masquées dans les PDF


def _chemin(v: str | None) -> Path | None:
    return Path(v).expanduser() if v else None


def a_des_bulletins(config) -> bool:
    dossier, classeur = _chemin(config.paie.dossier), _chemin(config.paie.classeur)
    return bool((dossier and dossier.is_dir() and any(dossier.rglob("*.pdf"))) or (classeur and classeur.is_file()))


def charger(config, coffre, progression=None) -> Donnees:
    p = config.paie
    anonymiseur, verificateur = anonymiseurs(config, coffre)
    colonnes = Colonnes(**p.colonnes) if p.colonnes else None
    pdfs, ignores, remplacements = {}, [], 0
    dossier = _chemin(p.dossier)
    fichiers = sorted(dossier.rglob("*.pdf")) if dossier and dossier.is_dir() else []
    for i, f in enumerate(fichiers):
        if progression:
            progression(i, len(fichiers), f.name)
        try:
            pages = extraire_pages(f)
        except Exception:                       # PDF abîmé ou protégé
            ignores.append(f.name)
            continue
        pages, n = anonymiser_pages(pages, anonymiseur, verificateur, f.name)
        remplacements += n
        b = lire_bulletin(pages, f.name, p.natures, colonnes)
        if b is None:
            ignores.append(f.name)
        elif b.mois not in pdfs:
            pdfs[b.mois] = b
    coffre.sauvegarder()
    classeur_chemin = _chemin(p.classeur)
    classeur = []
    if classeur_chemin and classeur_chemin.is_file():
        libelles: dict[str, str] = {}
        renommer = lambda lib: libelles.setdefault(lib, anonymiser_libelle(lib, anonymiseur))
        classeur = lire_classeur(classeur_chemin, p.natures, renommer)
        coffre.sauvegarder()
    par_mois = {b.mois: b for b in classeur}
    for b in pdfs.values():
        if p.source_preferee == "pdf" or b.mois not in par_mois:
            par_mois[b.mois] = b
    bulletins = [par_mois[m] for m in sorted(par_mois)]
    emploi, avant = A.emploi_actuel(bulletins)
    liste_pdfs = [pdfs[m] for m in sorted(pdfs)]
    return Donnees(bulletins=bulletins, emploi=emploi, avant=avant, classeur=classeur, pdfs=liste_pdfs,
                   pdf_ignores=ignores, differences=comparer(classeur, liste_pdfs), ecarts=ecarts_internes(bulletins),
                   formules=verifier_classeur(classeur_chemin, classeur) if classeur else [], remplacements=remplacements)


def analyser(config, coffre, rafraichir_prix: bool | None = None, progression=None) -> dict | None:
    """Tout ce que la page des bulletins montre. None s'il n'y a aucun bulletin."""
    d = charger(config, coffre, progression)
    if not d.emploi:
        return None
    augs = A.augmentations(d.emploi)
    ipc, source_ipc = indices(CACHE_PRIX, rafraichir_prix)
    p = config.paie
    return {
        "donnees": d, "augmentations": augs, "regles": A.regles_pourcentage(d.emploi), "treizieme": A.treizieme(d.emploi),
        "calendrier": A.calendrier(d.emploi), "impots": A.impots(d.emploi), "par_annee": A.par_annee(d.emploi),
        "pouvoir_achat": A.pouvoir_achat(d.emploi, ipc, augs), "cet": A.cet(d.emploi),
        "prevision": prevoir(d.emploi, p.hausse_janvier, p.hausse_avril),
        "annonces": verifier(d.emploi, p.annonces), "source_ipc": source_ipc,
    }
