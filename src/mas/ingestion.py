"""Ingestion : PDF ou ZIP de PDF -> texte page par page.

Les tableaux sont rendus sous forme de lignes `| col | col |` en gardant les
cellules vides : c'est ce qui permet de distinguer une colonne Débit d'une
colonne Crédit une fois le PDF transformé en texte.
"""

from __future__ import annotations

import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import pdfplumber

from .lecteur_deduit import LecteurDeduit
from .releve import LecteurReleve, ReleveStructure

TAILLE_MAX_ZIP = 500 * 1024 * 1024  # protection contre les "zip bombs"


@dataclass
class Page:
    numero: int
    texte: str
    ocr: bool = False


@dataclass
class Document:
    nom: str
    pages: list[Page] = field(default_factory=list)
    # Opérations lues directement dans le tableau (voir releve.py) ; None : extraction par l'IA
    structure: ReleveStructure | None = None
    raison: str = ""        # pourquoi le tableau n'a pas été reconnu (montré à l'utilisateur)

    @property
    def texte(self) -> str:
        return "\n\n".join(p.texte for p in self.pages)


def _rendre_tableau(tableau: list[list[str | None]]) -> str:
    lignes = []
    for ligne in tableau:
        cellules = [(c or "").replace("\n", " ").strip() for c in ligne]
        if any(cellules):
            lignes.append("| " + " | ".join(cellules) + " |")
    return "\n".join(lignes)


def _dans_une_boite(obj: dict, boites: list[tuple[float, float, float, float]]) -> bool:
    cx = (obj["x0"] + obj["x1"]) / 2
    cy = (obj["top"] + obj["bottom"]) / 2
    return any(x0 <= cx <= x1 and top <= cy <= bottom for x0, top, x1, bottom in boites)


def _ocr_page(chemin_pdf: Path, index: int) -> str:
    """OCR d'une page (PDF scanné). Nécessite l'extra [ocr] et tesseract installé."""
    try:
        import fitz  # PyMuPDF
        import pytesseract
        from PIL import Image
    except ImportError:
        return ""
    with fitz.open(chemin_pdf) as doc:
        pix = doc[index].get_pixmap(dpi=300)
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    try:
        return pytesseract.image_to_string(image, lang="fra")
    except pytesseract.TesseractError:
        return pytesseract.image_to_string(image)


def lire_pdf(chemin: str | Path) -> Document:
    """Extrait le texte d'un PDF page par page (une page en mémoire à la fois)."""
    chemin = Path(chemin)
    doc = Document(nom=chemin.name)
    lecteur = LecteurReleve()
    deduit = LecteurDeduit()      # autres mises en page : colonnes déduites des opérations, vérifiées au centime
    with pdfplumber.open(chemin) as pdf:
        for i, page in enumerate(pdf.pages):
            lecteur.lire_page(page, i)
            deduit.ajouter_page(page, i)
            tableaux = page.find_tables()
            boites = [t.bbox for t in tableaux]
            if boites:
                hors_tableaux = page.filter(
                    lambda o: "x0" not in o or not _dans_une_boite(o, boites)
                )
                texte = hors_tableaux.extract_text() or ""
                rendus = [_rendre_tableau(t.extract()) for t in tableaux]
                texte = "\n".join([texte.strip(), *rendus]).strip()
            else:
                texte = (page.extract_text(layout=True) or "").strip()
                # Le mode layout garde les colonnes mais ajoute beaucoup d'espaces
                texte = "\n".join(l.rstrip() for l in texte.splitlines() if l.strip())

            ocr = False
            if len(texte) < 20:  # page vide : probablement un scan
                texte_ocr = _ocr_page(chemin, i)
                if texte_ocr.strip():
                    texte, ocr = texte_ocr.strip(), True
            doc.pages.append(Page(numero=i + 1, texte=texte, ocr=ocr))
            page.flush_cache()
    deduit.ocr = any(p.ocr for p in doc.pages)
    doc.structure = lecteur.resultat() or deduit.resultat()
    doc.raison = "" if doc.structure else deduit.raison
    if doc.structure is not None:
        # Tableau reconnu : une ligne par opération, colonnes Débit et Crédit séparées, plutôt
        # que la ligne unique fourre-tout que pdfplumber produit sur certains relevés (BRED…)
        for index, texte in doc.structure.pages_rendues.items():
            doc.pages[index].texte = texte
    return doc


def _extraire_zip(chemin: Path, destination: Path) -> list[Path]:
    pdfs = []
    with zipfile.ZipFile(chemin) as z:
        if sum(i.file_size for i in z.infolist()) > TAILLE_MAX_ZIP:
            raise ValueError("Archive trop volumineuse une fois décompressée.")
        for info in z.infolist():
            if info.is_dir() or not info.filename.lower().endswith(".pdf"):
                continue
            nom = Path(info.filename).name  # aplatit l'arborescence (anti zip-slip)
            if nom.startswith(".") or nom.startswith("__"):
                continue
            cible = destination / nom
            compteur = 1
            while cible.exists():
                cible = destination / f"{cible.stem}_{compteur}.pdf"
                compteur += 1
            cible.write_bytes(z.read(info))
            pdfs.append(cible)
    return pdfs


def iter_documents(entree: str | Path) -> Iterator[Document]:
    """Accepte un PDF, un ZIP de PDF ou un dossier de PDF."""
    entree = Path(entree)
    if entree.is_dir():
        for pdf in sorted(entree.glob("*.pdf")):
            yield lire_pdf(pdf)
    elif entree.suffix.lower() == ".zip":
        with tempfile.TemporaryDirectory(prefix="mas_") as tmp:
            for pdf in sorted(_extraire_zip(entree, Path(tmp))):
                yield lire_pdf(pdf)
    elif entree.suffix.lower() == ".pdf":
        yield lire_pdf(entree)
    else:
        raise ValueError(f"Format non pris en charge : {entree.suffix} (PDF, ZIP ou dossier)")
