"""Le menu commun aux pages d'un même rapport : ton budget, tes fiches de paie, et la page qui croise les deux.

Les trois pages sont des fichiers voisins (`rapport_X.html`, `rapport_X_paie.html`, `rapport_X_croise.html`) ; le
menu se pose juste sous l'en-tête de chacune, et se remplace si on le régénère.
"""
from __future__ import annotations

import html
import re

PAGES = {"budget": "Ton budget", "paie": "Tes fiches de paie", "croise": "Salaire et budget"}
CSS = """
.rapports{margin:-6px 0 22px}
.rapports ul{list-style:none;margin:0;padding:0;display:flex;flex-wrap:wrap;gap:8px}
.rapports a{display:inline-block;padding:6px 14px;border:1px solid var(--filet);border-radius:999px;color:var(--encre-2);
  text-decoration:none;font-size:14px;font-weight:600}
.rapports a:hover{border-color:var(--lagon);color:var(--encre)}
.rapports a[aria-current="page"]{background:var(--lagon);border-color:var(--lagon);color:var(--feuille)}
"""


def navigation(actif: str, liens: dict[str, str]) -> str:
    """`liens` : {page: nom du fichier voisin}, pour les pages qui existent."""
    if len(liens) < 2:
        return ""
    items = "".join(
        f'<li><a href="{html.escape(liens[cle])}"' + (' aria-current="page"' if cle == actif else "") + f">{nom}</a></li>"
        for cle, nom in PAGES.items() if cle in liens)
    return f'<nav class="rapports" aria-label="Les pages du rapport"><ul>{items}</ul></nav>'


def ajouter_navigation(page: str, menu: str) -> str:
    """Pose (ou remplace) le menu au début de la feuille d'une page déjà écrite, et son style s'il manque."""
    page = re.sub(r'<nav class="rapports".*?</nav>', "", page, flags=re.S)
    if not menu:
        return page
    m = re.search(r'<main class="feuille">(?:<div class="ruban"[^>]*></div>)?', page)
    if not m:
        return page
    page = page[:m.end()] + menu + page[m.end():]
    if ".rapports{" not in page:
        page = page.replace("</style>", CSS + "</style>", 1)
    return page
