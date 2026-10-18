"""Export du rapport Markdown en HTML autonome : un seul fichier, styles intégrés, aucune ressource
externe (l'ouvrir ne fait aucune requête réseau), thème clair/sombre et mise en page imprimable."""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

from markdown_it import MarkdownIt

# HTML brut désactivé : le commentaire vient d'un LLM et les libellés d'un relevé bancaire,
# on ne laisse passer aucune balise (markdown-it refuse aussi les liens javascript:).
_MD = MarkdownIt("commonmark", {"html": False}).enable("table")

CSS = """
:root{--fond:#f4f3ef;--papier:#fff;--texte:#1f2328;--doux:#5b6470;--ligne:#e2e0da;--zebre:#faf9f6;
--accent:#0f766e;--prive-fond:#fff1e0;--prive-texte:#8a4b00;--anonyme-fond:#e6f4f1;--anonyme-texte:#0b5e57}
@media (prefers-color-scheme:dark){:root{color-scheme:dark;--fond:#121417;--papier:#1b1e23;--texte:#e7e7e7;
--doux:#9ba4ae;--ligne:#2d3138;--zebre:#20242a;--accent:#5eead4;--prive-fond:#3b2a13;--prive-texte:#fbbf77;
--anonyme-fond:#123a36;--anonyme-texte:#7ee0d2}}
*{box-sizing:border-box}
body{margin:0;padding:2rem 1rem;background:var(--fond);color:var(--texte);
font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif}
main{max-width:900px;margin:0 auto;background:var(--papier);border:1px solid var(--ligne);border-radius:14px;
padding:2.5rem clamp(1rem,4vw,3rem)}
.bandeau{display:inline-block;margin:0 0 1.25rem;padding:.3rem .8rem;border-radius:999px;font-size:.85rem;
font-weight:600;background:var(--prive-fond);color:var(--prive-texte)}
.bandeau.anonyme{background:var(--anonyme-fond);color:var(--anonyme-texte)}
h1{font-size:2rem;line-height:1.2;margin:0 0 1.5rem;letter-spacing:-.01em}
h2{font-size:1.35rem;margin:2.75rem 0 1rem;padding-bottom:.4rem;border-bottom:2px solid var(--ligne)}
h3{font-size:1.08rem;margin:2.25rem 0 .75rem;color:var(--accent)}
p,li{max-width:72ch}
ol,ul{padding-left:1.4rem}
li{margin:.35rem 0}
strong{font-weight:650}
.tableau{overflow-x:auto;margin:.75rem 0 1.25rem;border:1px solid var(--ligne);border-radius:10px}
table{border-collapse:collapse;width:100%;font-size:.94rem;font-variant-numeric:tabular-nums}
th,td{padding:.55rem .8rem;text-align:left;vertical-align:top;border-bottom:1px solid var(--ligne)}
tbody tr:last-child td{border-bottom:0}
th{font-size:.78rem;text-transform:uppercase;letter-spacing:.05em;color:var(--doux);font-weight:600}
tbody tr:nth-child(even){background:var(--zebre)}
th[style*=right],td[style*=right]{white-space:nowrap}
footer{margin-top:3rem;padding-top:1rem;border-top:1px solid var(--ligne);color:var(--doux);font-size:.85rem}
@media print{body{background:#fff;color:#000;padding:0}main{border:0;max-width:none;padding:0}
tr{break-inside:avoid}h2,h3{break-after:avoid}.tableau{overflow:visible}}
"""


def markdown_vers_html(markdown: str, *, titre: str = "Analyse budgétaire", anonyme: bool = False,
                       genere_le: datetime | None = None) -> str:
    corps = _MD.render(markdown)
    corps = corps.replace("<table>", '<div class="tableau"><table>').replace("</table>", "</table></div>")
    if anonyme:
        bandeau = '<p class="bandeau anonyme">Version anonyme : ce qu\'a vu l\'IA</p>'
    else:
        bandeau = '<p class="bandeau">🔒 Contient vos données personnelles : à garder pour vous</p>'
    quand = (genere_le or datetime.now()).strftime("%d/%m/%Y à %H:%M")
    return (
        '<!doctype html>\n<html lang="fr">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(titre)}</title>\n<style>{CSS}</style>\n</head>\n<body>\n<main>\n"
        f"{bandeau}\n{corps}"
        f"<footer>Généré localement par Mas le {quand}.</footer>\n</main>\n</body>\n</html>\n"
    )


def ecrire_html(chemin_md: Path, markdown: str, *, anonyme: bool) -> Path:
    """Écrit la version HTML à côté du Markdown (rapport.md -> rapport.html)."""
    chemin = chemin_md.with_suffix(".html")
    chemin.write_text(markdown_vers_html(markdown, anonyme=anonyme), encoding="utf-8")
    return chemin
