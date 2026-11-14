"""Tes fiches de paie : bulletins PDF (anonymisés avant d'être lus) et, en complément, un classeur Excel.

- chargement.py : lecture, anonymisation, comparaison PDF et classeur ;
- analyses.py, prevision.py, annonces.py, controles.py : ce que la page montre ;
- page.py : la page des bulletins ; croise.py : la page qui croise salaire et budget ;
- export.py : les données en JSON ; rapprochement.py : bulletin contre virement reçu.

Calcul local, sans IA. Seul l'indice des prix est téléchargé (INSEE), le même pour tout le monde.
"""
