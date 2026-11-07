"""Analyse sans IA (`mas analyser --no-ai`) : tout se calcule sur ton ordinateur, rien n'est envoyé.

Seules deux étapes changent : la catégorisation passe par des mots-clés et le classement par
NATURE_PAR_DEFAUT ; le commentaire devient des constats calculés. Les chiffres viennent du même
code que l'analyse avec l'IA. Un commerçant inconnu de ces listes reste dans « Autres » :
analyse.categories (config.yaml) permet de le classer.
"""

from __future__ import annotations

import re
from collections import defaultdict

from .agents.programme import AnalyseReleve, NATURE_PAR_DEFAUT, progression
from .agents.synthese import Synthetiseur, _eur
from .anonymisation.coffre import sans_accents
from .modeles import Classement, GroupeRecurrent, Transaction, TransactionCategorisee
from .page import CATEGORIES
from .recurrence import cle_libelle

# Du plus précis au plus général : la première règle qui correspond l'emporte (« UBER EATS » avant
# « UBER », « CARREFOUR BANQUE » avant « CARREFOUR », « ASSURANCE VIE » avant « ASSURANCE »…).
# Mots entiers, en majuscules sans accents : RETRAIT ne reconnaît pas RETRAITE. Un chiffre collé ne gêne
# pas : « LIDL1234 », « CARTE02/05/26NETFLIX » (Boursorama).
REGLES: list[tuple[str, str]] = [
    ("epargne", r"LIVRET|LDDS?|LEP|PEL|CEL|PEA|ASSURANCE VIE|EPARGNE|YOMONI|NALO|LINXEA"),
    ("credit", r"COFIDIS|CETELEM|SOFINCO|YOUNITED|FLOA|ONEY|FRANFINANCE|CARREFOUR BANQUE|CREDIT (?:AUTO|CONSO)"),
    ("logement", r"LOYER|QUITTANCE|FONCIA|NEXITY|ORPI|CITYA|SYNDIC|COPROPRIETE|COPRO|HLM|ACTION LOGEMENT"
                 r"|(?:PRET|CREDIT) IMMO(?:BILIER)?"),
    ("credit", r"PRET(?! A MANGER)"),
    ("impots_taxes", r"DGFIP|DRFIP|IMPOTS?|TRESOR PUBLIC|FINANCES PUBLIQUES|URSSAF|TAXES?|ANTAI|AMENDES?"),
    ("frais_bancaires", r"AGIOS|COMMISSIONS?|TENUE DE COMPTE|COTIS(?:ATION)? (?:CARTE|CB|VISA|MASTERCARD)"
                        r"|FRAIS (?:BANCAIRES|DE TENUE|DE GESTION|DE REJET|SUR)|INT(?:ERETS)? DEBITEURS"),
    ("retrait", r"RETRAIT|RETRAITDAB|DAB|GAB"),
    ("restauration", r"UBER ?EATS|DELIVEROO|JUST ?EAT|MC ?DONALD'?S?|MC ?DO|BURGER KING|KFC|QUICK|SUBWAY"
                     r"|DOMINO'?S|PIZZ\w*|RESTAURANTS?|RESTO|BRASSERIE|BISTROT?|CAFETERIA|CANTINE|STARBUCKS|PRET A MANGER"
                     r"|BRIOCHE DOREE|COLUMBUS|FIVE GUYS|BUFFALO GRILL|COURTEPAILLE|HIPPOPOTAMUS|FLUNCH|CROUS"
                     r"|LA CROISSANTERIE|SUSHI\w*|POKE\w*|BURGER\w*|KEBAB|TACOS|CREPERIE|TRATTORIA|BOUILLON"
                     r"|TRAITEUR|SNACK|GRILL|BAR|CAFE"),
    ("alimentation", r"CARREFOUR|LECLERC|AUCHAN|INTERMARCHE|LIDL|ALDI|MONOPRIX|FRANPRIX|CASINO|SUPER ?U|HYPER ?U"
                     r"|U EXPRESS|PICARD|GRAND FRAIS|BIOCOOP|NATURALIA|NETTO|CORA|COLRUYT|G20"
                     r"|SPAR|VIVAL|PROXI|COCCINELLE|LA VIE CLAIRE|BIO C BON|THIRIET|ATAC|SIMPLY|ECOMAX|SUPECO|MIE CALINE"
                     r"|SUPERMARCHE|SUPERETTE|MARKET|MARCHE|ALIMENTATION|EPICERIE|BOULANGERIE|FOURNIL|PATISSERIE"
                     r"|BOUCHERIE|POISSONNERIE|FROMAGERIE|PRIMEUR"),
    ("energie", r"EDF|ENGIE|GDF|ENI|ENERCOOP|EKWATEUR|VEOLIA|SUEZ|SAUR|LYONNAISE DES EAUX|EAUX?|ELECTRICITE|(?:PRLV|PRELEVEMENT).*TOTALENERGIES"),
    ("abonnement", r"NETFLIX|SPOTIFY|DEEZER|DISNEY ?PLUS|CANAL ?PLUS|CANAL\+|DAZN|YOUTUBE|AMAZON PRIME|PRIME VIDEO"
                   r"|APPLE\.COM|ICLOUD|GOOGLE ONE|OPENAI|CHATGPT|ADOBE|MICROSOFT 365"
                   r"|PARAMOUNT|CRUNCHYROLL|AUDIBLE|KINDLE|GITHUB|DROPBOX|NOTION|ANTHROPIC|PATREON|MEDIAPART"
                   r"|BASIC ?FIT|FITNESS PARK|ORANGE BLEUE|KEEP COOL"),
    ("telecom", r"ORANGE|SOSH|SFR|BOUYGUES|FREE(?! ?NOW)|FREEBOX|LEBARA|LYCAMOBILE|PRIXTEL|NRJ MOBILE"),
    ("assurance", r"MAIF|MACIF|MAAF|MATMUT|AXA|ALLIANZ|GROUPAMA|GMF|SOGESSUR|PACIFICA|MGEN|MUTIEG|MUTUELLE"
                  r"|ASSURANCES?|ASSUR"),
    ("sante", r"PHARMACIE|PHARMA|CPAM|AMELI|CAMIEG|DOCTOLIB|DOCTEUR|MEDECIN|DENTISTE|OPTICIEN|KINE|OSTEOPATHE"
              r"|LABORATOIRE|LABO|HOPITAL|CLINIQUE|INFIRMIER\w*|ORTHO\w*|RADIOLOGIE|DERMATO\w*|GYNECO\w*|PEDIATRE"
              r"|AUDIOPROTHESISTE|MEDICAL\w*"),
    ("transport", r"SNCF|OUIGO|TGV|RATP|NAVIGO|TRANSILIEN|KEOLIS|TRANSDEV|TISSEO|BLABLACAR|UBER|BOLT|FREE ?NOW"
                  r"|HEETCH|VINCI|APRR|ASF|COFIROUTE|SANEF|PEAGE|AUTOROUTES?|PARKING|INDIGO|TOTAL|TOTALENERGIES"
                  r"|ESSO|SHELL|STATION SERVICE|CARBURANT|NORAUTO|FEU VERT|MIDAS|AIR FRANCE|EASYJET|RYANAIR"
                  r"|TRANSAVIA|VUELING|AIR CARAIBES|AIR ANTILLES|CORSAIR|FRENCH BEE|EUROPCAR|HERTZ|SIXT|TRAINLINE|FLIXBUS"
                  r"|VELIB|LIME|DOTT|TAXIS?|TCL|TBM|IONITY|IZIVIA|TESLA|Q8|AVIA|STATION|GARAGE|CONTROLE TECHNIQUE"
                  r"|AUTOVISION|DEKRA|SPEEDY|EUROMASTER"),
    ("loisirs", r"CINEMA|UGC|PATHE|GAUMONT|MK2|THEATRE|MUSEE|TICKETMASTER|BOOKING|AIRBNB|EXPEDIA|HOTEL"
                r"|STEAM|PLAYSTATION|NINTENDO|XBOX|TWITCH|EPIC GAMES|FDJ|DISNEYLAND|PARC ASTERIX|LIBRAIRIE|BOWLING"
                r"|PISCINE|KARTING|ESCAPE|SPECTACLES?|BILLETTERIE|FESTIVAL|CONCERT|ZOO|AQUARIUM|CAMPING"),
    ("shopping", r"AMAZON|AMZN|FNAC|DARTY|BOULANGER|DECATHLON|IKEA|LEROY MERLIN|CASTORAMA|ZARA|H&M|UNIQLO|KIABI"
                 r"|SEPHORA|ZALANDO|VINTED|ALIEXPRESS|TEMU|SHEIN|CDISCOUNT|ETSY|LEBONCOIN|COIFFEUR|COIFFURE|NOCIBE"
                 r"|YVES ROCHER|MARIONNAUD|OCCITANE|LUSH|PRIMARK|BERSHKA|MANGO|PROMOD|ETAM|UNDIZ|LEVIS|CELIO|JULES"
                 r"|LA HALLE|NIKE|ADIDAS|FOOT LOCKER|COURIR|GO SPORT|INTERSPORT|SPORT 2000|GIFI|CENTRAKOR|ACTION"
                 r"|BOTANIC|TRUFFAUT|JARDILAND|MAISONS DU MONDE|CONFORAMA|ALINEA|LAPEYRE|BRICO ?DEPOT|BRICOMARCHE"
                 r"|BRICORAMA|MR BRICOLAGE|WELDOM|SAMSUNG|MICROMANIA|CULTURA|GIBERT"),
    ("virement_personnel", r"LYDIA|WERO|PUMPKIN"),
]
_REGLES = [(categorie, re.compile(rf"(?<![A-Z])(?:{motifs})(?![A-Z])")) for categorie, motifs in REGLES]
# Ces mots ne valent que pour un crédit : au débit, « CAF » est souvent un café.
_REVENU = re.compile(r"(?<![A-Z])(?:SALAIRE|PAIE|PAYE|REMUNERATION|INDEMNITES?|IJSS|CAF|ALLOCATIONS?|FRANCE TRAVAIL"
                     r"|POLE EMPLOI|PENSION|RETRAITE|CARSAT|AGIRC|ARRCO|PRIME|INTERESSEMENT|INTERETS)(?![A-Z])")
_VIR_PERSONNE = re.compile(r"(?<![A-Z])VIR(?:EMENT)?(?![A-Z]).*\[PERSONNE_\d+\]")

# Un employeur ne s'écrit pas toujours SALAIRE : un même crédit, au moins 2 mois, d'au moins ce montant
REVENU_REGULIER_MIN = 300.0


def _selon_les_regles(texte: str, montant: float) -> str | None:
    if montant > 0 and _REVENU.search(texte):
        return "revenu"
    return next((c for c, motif in _REGLES if motif.search(texte)), None)


def categorie_du_libelle(libelle: str, montant: float, en_clair: str = "") -> str:
    """Catégorie d'une opération. `en_clair` (le libellé avec ses vrais noms, en local) ne sert qu'en
    dernier : un commerçant masqué s'y retrouve, mais un virement à M. Leclerc n'est pas des courses."""
    texte = sans_accents(libelle).upper()
    return (_selon_les_regles(texte, montant)
            or ("virement_personnel" if _VIR_PERSONNE.search(texte) else None)
            or _selon_les_regles(sans_accents(en_clair).upper(), montant)
            or "autre")


def _revenus_reguliers(operations: list[TransactionCategorisee]) -> list[TransactionCategorisee]:
    def candidat(t: TransactionCategorisee) -> bool:
        return t.montant >= REVENU_REGULIER_MIN and t.categorie not in ("virement_personnel", "epargne")

    mois: dict[str, set[str]] = defaultdict(set)
    for t in filter(candidat, operations):
        mois[cle_libelle(t.libelle)].add(t.date[:7])
    return [t.model_copy(update={"categorie": "revenu"}) if candidat(t) and len(mois[cle_libelle(t.libelle)]) >= 2
            else t for t in operations]


class AnalyseSansIA(AnalyseReleve):
    """Même enchaînement que l'analyse avec l'IA, sans jamais appeler ses prédicteurs."""

    def __init__(self, *args, en_clair=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.en_clair = en_clair or (lambda libelle: "")

    def categoriser(self, transactions: list[Transaction]) -> list[TransactionCategorisee]:
        progression.info("[2/5] Catégorisation par mots-clés (sans IA) : %d opération(s)", len(transactions))
        return _revenus_reguliers([
            TransactionCategorisee(**t.model_dump(),
                                   categorie=categorie_du_libelle(t.libelle, t.montant, self.en_clair(t.libelle)))
            for t in transactions
        ])

    def classer(self, groupes: list[GroupeRecurrent]) -> list[Classement]:
        return [Classement(cle=g.cle, nature=NATURE_PAR_DEFAUT.get(g.categorie, "courant_variable"),
                           justification="Classement par défaut d'après la catégorie.")
                for g in groupes]


def commercants_a_classer(transactions: list[TransactionCategorisee], nombre: int = 10) -> list[tuple[str, float, int]]:
    """Les débits restés dans « Autres », par commerçant, les plus lourds d'abord : (libellé, total, opérations)."""
    groupes: dict[str, list[TransactionCategorisee]] = defaultdict(list)
    for t in transactions:
        if t.categorie == "autre" and t.montant < 0:
            groupes[cle_libelle(t.libelle)].append(t)
    lourds = sorted(groupes.values(), key=lambda g: sum(t.montant for t in g))[:nombre]
    return [(g[0].libelle, -sum(t.montant for t in g), len(g)) for g in lourds]


def constats(budget: dict, commercants: list[tuple[str, float, int]] | None = None) -> str:
    """Le commentaire de la page, calculé : ce que l'IA rédigerait, sans ses conseils."""
    revenus, depenses = budget["revenus_mensuels"], budget["depenses_mensuelles"]
    solde = revenus - depenses
    paragraphes = [f"En moyenne, **{_eur(revenus)}** rentrent et **{_eur(depenses)}** sortent chaque mois : "
                   + (f"il reste **{_eur(solde)}**." if solde >= 0 else f"il manque **{_eur(-solde)}**.")]
    postes = [(c, m) for c, m in budget["par_categorie"].items() if c != "autre"][:3]
    if postes:
        paragraphes.append("Les plus gros postes : "
                           + ", ".join(f"{CATEGORIES.get(c, c)} ({_eur(m)})" for c, m in postes) + ".")
    if budget["total_obligatoire"]:
        paragraphes.append(f"Une fois payées les dépenses obligatoires récurrentes ({_eur(budget['total_obligatoire'])}), "
                           f"il reste {_eur(budget['reste_apres_obligatoire'])} par mois.")
    a_classer = budget["par_categorie"].get("autre", 0.0)
    if a_classer and depenses:
        paragraphes.append(f"**{round(100 * a_classer / depenses)} % des dépenses** ({_eur(a_classer)} par mois) restent "
                           "à classer : les mots-clés ne reconnaissent pas ces commerçants, et une épargne non reconnue "
                           "compte ici comme une dépense. Donne-leur une catégorie dans analyse.categories "
                           "(config.yaml), ou lance l'analyse avec l'IA.")
        if commercants:
            paragraphes.append("Ceux qui pèsent le plus sur la période :\n\n" + "\n".join(
                f"- {libelle.replace('*', ' ')} : {_eur(total)} en {n} opération{'s' if n > 1 else ''}"
                for libelle, total, n in commercants))
    return "\n\n".join(paragraphes)


class SyntheseSansIA(Synthetiseur):
    def forward(self, transactions, *args, **kwargs):
        self.commercants = commercants_a_classer(transactions)
        return super().forward(transactions, *args, **kwargs)

    def commenter(self, budget: dict, resume: str) -> str:
        return constats(budget, self.commercants)
