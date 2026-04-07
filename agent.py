#!/usr/bin/env python3
"""
Sylph - Agent automatise de recherche d'alternance
Recherche et candidature automatique sur 6 plateformes

Recherche automatique d'offres, filtrage anti-arnaque,
candidature automatique et notification Telegram.

Usage:
    python3 agent.py --once          # Une seule recherche + candidatures
    python3 agent.py --search-only   # Recherche sans postuler
    python3 agent.py --quarantine    # Voir les offres en quarantaine
    python3 agent.py                 # Mode continu (toutes les heures)
"""

import yaml
import argparse
import json
import os
import random
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Forcer le fuseau horaire Paris (le serveur est en UTC)
os.environ['TZ'] = 'Europe/Paris'
try:
    time.tzset()
except AttributeError:
    pass  # Windows n'a pas tzset

PARIS_TZ = ZoneInfo("Europe/Paris")

from utils.logger import setup_logger, ApplicationLogger
from utils.requester import create_requester
from utils.stealth import create_stealth_browser
from utils.telegram import create_notifier, create_bot
from utils.captcha import create_solver
from utils.ai import create_ai_client
from filters.scam_detector import create_detector, ScamLevel
from filters.ai_analyzer import create_analyzer
from platforms import IndeedPlatform, HelloWorkPlatform, FranceTravailPlatform, LinkedInPlatform, WTTJPlatform, APECPlatform
from apply import HelloWorkApplicator, FranceTravailApplicator, IndeedApplicator, LinkedInApplicator, WTTJApplicator, APECApplicator

# Fichiers de logs
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OFFERS_FILE = os.path.join(BASE_DIR, "logs", "offers.json")
APPLIED_FILE = os.path.join(BASE_DIR, "logs", "applied.json")

logger = None
app_logger = None
running = True


def load_config(config_path: str = "config.yaml") -> dict:
    """Charge la configuration"""
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def signal_handler(signum, frame):
    """Arret propre"""
    global running
    if logger:
        logger.info("Arret demande...")
    running = False
    sys.exit(0)


def save_offers(offers: list, filename: str = OFFERS_FILE):
    """Sauvegarde les offres en JSON"""
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)

    existing = []
    if path.exists():
        try:
            with open(path) as f:
                existing = json.load(f)
        except Exception:
            existing = []

    existing_urls = {o.get('url') for o in existing}
    new_count = 0
    for offer in offers:
        if offer['url'] not in existing_urls:
            offer['found_date'] = datetime.now(PARIS_TZ).isoformat()
            existing.append(offer)
            new_count += 1

    with open(path, 'w') as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

    return new_count


def load_applied() -> set:
    """Charge la liste des URLs deja postulees"""
    path = Path(APPLIED_FILE)
    if path.exists():
        try:
            with open(path) as f:
                data = json.load(f)
                return {item.get('url', '') for item in data}
        except Exception:
            pass
    return set()


def save_applied(result_dict: dict):
    """Ajoute une candidature au log"""
    path = Path(APPLIED_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)

    existing = []
    if path.exists():
        try:
            with open(path) as f:
                existing = json.load(f)
        except Exception:
            existing = []

    result_dict['timestamp'] = datetime.now(PARIS_TZ).isoformat()
    existing.append(result_dict)

    with open(path, 'w') as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)


def search_all_platforms(config: dict, browser=None, requester=None) -> list:
    """Lance la recherche sur toutes les plateformes actives"""
    search_config = config.get('search', {})
    keywords = search_config.get('keywords', [])
    locations = search_config.get('locations', ['Paris'])
    platforms_config = config.get('platforms', {})

    all_offers = []

    # Indeed (Selenium stealth)
    if platforms_config.get('indeed', {}).get('enabled', False) and browser:
        indeed = IndeedPlatform(platforms_config['indeed'], browser=browser)
        for location in locations:
            try:
                offers = indeed.search(keywords, location)
                all_offers.extend(offers)
                logger.info(f"Indeed [{location}]: {len(offers)} offres")
            except Exception as e:
                logger.error(f"Erreur Indeed [{location}]: {e}")

    # HelloWork (Selenium stealth)
    if platforms_config.get('hellowork', {}).get('enabled', False) and browser:
        hellowork = HelloWorkPlatform(platforms_config['hellowork'], browser=browser)
        for location in locations:
            try:
                offers = hellowork.search(keywords, location)
                all_offers.extend(offers)
                logger.info(f"HelloWork [{location}]: {len(offers)} offres")
            except Exception as e:
                logger.error(f"Erreur HelloWork [{location}]: {e}")

    # France Travail (HTTP requests)
    if platforms_config.get('francetravail', {}).get('enabled', False) and requester:
        ft = FranceTravailPlatform(platforms_config['francetravail'], requester=requester)
        for location in locations:
            try:
                offers = ft.search(keywords, location)
                all_offers.extend(offers)
                logger.info(f"France Travail [{location}]: {len(offers)} offres")
            except Exception as e:
                logger.error(f"Erreur France Travail [{location}]: {e}")

    # LinkedIn (HTTP requests - recherche publique, pas besoin de Selenium ni cookies)
    if platforms_config.get('linkedin', {}).get('enabled', False):
        linkedin = LinkedInPlatform(platforms_config['linkedin'])
        for location in locations:
            try:
                offers = linkedin.search(keywords, location)
                all_offers.extend(offers)
                logger.info(f"LinkedIn [{location}]: {len(offers)} offres")
            except Exception as e:
                logger.error(f"Erreur LinkedIn [{location}]: {e}")

    # Welcome to the Jungle (HTTP requests - API Algolia publique)
    if platforms_config.get('welcome_to_the_jungle', {}).get('enabled', False):
        wttj = WTTJPlatform(platforms_config['welcome_to_the_jungle'])
        for location in locations:
            try:
                offers = wttj.search(keywords, location)
                all_offers.extend(offers)
                logger.info(f"WTTJ [{location}]: {len(offers)} offres")
            except Exception as e:
                logger.error(f"Erreur WTTJ [{location}]: {e}")

    # APEC (HTTP requests - API POST interne)
    if platforms_config.get('apec', {}).get('enabled', False):
        apec = APECPlatform(platforms_config['apec'])
        for location in locations:
            try:
                offers = apec.search(keywords, location)
                all_offers.extend(offers)
                logger.info(f"APEC [{location}]: {len(offers)} offres")
            except Exception as e:
                logger.error(f"Erreur APEC [{location}]: {e}")

    return all_offers


def analyze_offers(offers: list, scam_detector, ai_analyzer=None) -> dict:
    """Analyse les offres avec le detecteur d'arnaques + IA"""
    results = {
        'safe': [],
        'quarantine': [],
        'dangerous': [],
        'ai_filtered': [],  # Offres filtrees par l'IA (ecoles, non pertinentes)
        'total': len(offers)
    }

    for offer in offers:
        offer_dict = offer.to_dict() if hasattr(offer, 'to_dict') else offer
        check = scam_detector.check_offer(offer_dict)

        offer_dict['scam_check'] = {
            'level': check.level.value,
            'score': check.score,
            'reasons': check.reasons,
            'whitelisted': check.url_whitelisted
        }

        if check.level == ScamLevel.SAFE:
            # Pre-filtre geographique: rejeter les offres clairement hors Ile-de-France
            # Le candidat cherche a Paris/IDF uniquement
            location_raw = (offer_dict.get('location', '') or '').lower().strip()
            # Normaliser: remplacer tirets par espaces pour matcher "boulogne billancourt" et "boulogne-billancourt"
            location_norm = location_raw.replace('-', ' ').replace('  ', ' ')
            if location_raw and location_raw not in ('france', 'inconnue', ''):
                # Patterns qui indiquent IDF (departements 75,77,78,91,92,93,94,95 + villes)
                # TOUS SANS TIRETS (on compare avec location_norm qui a des espaces)
                IDF_PATTERNS = [
                    'paris', '75', 'ile de france', 'île de france', 'idf',
                    'la défense', 'la defense',
                    # Departements IDF
                    '92', '93', '94', '91', '95', '77', '78',
                    'hauts de seine', 'seine saint denis', 'val de marne',
                    'essonne', "val d'oise", 'seine et marne', 'yvelines',
                    # Villes IDF courantes
                    'nanterre', 'puteaux', 'courbevoie', 'boulogne billancourt',
                    'boulogne', 'issy les moulineaux', 'issy',
                    'saint denis', 'st denis', 'montreuil', 'saint ouen', 'st ouen',
                    'gennevilliers', 'clichy', 'montrouge', 'neuilly', 'suresnes',
                    'rueil', 'massy', 'versailles', 'guyancourt', 'vélizy', 'velizy',
                    'villepinte', 'rungis', 'créteil', 'creteil', 'ivry', 'gentilly',
                    'fontenay', 'charenton', 'alfortville', 'pantin', 'palaiseau',
                    'antony', 'les ulis', 'meudon', 'bois colombes', 'la garenne',
                    'poissy', 'le plessis', 'élancourt', 'elancourt', 'tremblay',
                    'bonneuil', 'gonesse', 'lieusaint', 'brunoy', 'aubergenville',
                    'croissy', 'fleury merogis', 'villeneuve le roi', 'villejuif',
                    'noisy', 'bobigny', 'aulnay', 'sevran', 'bondy', 'drancy',
                    'epinay', 'stains', 'bagnolet', 'rosny', 'gagny', 'livry',
                    'vitry', 'champigny', 'maisons alfort', 'vincennes',
                    'levallois', 'colombes', 'asnieres', 'clamart', 'chatillon',
                    'malakoff', 'vanves', 'arcueil', 'cachan', 'orly', 'thiais',
                    'evry', 'corbeil', 'savigny', 'draveil', 'grigny', 'viry',
                    'cergy', 'pontoise', 'argenteuil', 'sarcelles', 'garges',
                    'melun', 'meaux', 'chelles', 'torcy', 'lognes', 'marne la vallee',
                    'saint germain', 'sartrouville', 'maisons laffitte', 'chatou',
                    'boissy', 'sucy', 'chennevieres', 'limeil', 'yerres',
                    'orsay', 'saclay', 'gif sur yvette', 'saint cloud',
                    'bagneux', 'fontenay aux roses', 'sceaux', 'chatenay',
                    'verrières', 'wissous', 'fresnes', "l'hay",
                    'fleury', 'villeneuve', 'merogis',
                ]
                is_idf = any(p in location_norm for p in IDF_PATTERNS)
                
                if not is_idf:
                    logger.info(
                        f"Pre-filtre: hors IDF: '{offer_dict.get('title', '')}' "
                        f"@ {offer_dict.get('company', '')} | lieu: {offer_dict.get('location', '')}"
                    )
                    offer_dict['ai_analysis'] = {
                        'is_school': False, 'school_confidence': 0.0, 'school_name': '',
                        'is_relevant': False, 'relevance_score': 0.0,
                        'red_flags': [f'Hors Ile-de-France: {offer_dict.get("location", "")}'],
                        'summary': f'Filtre geo: {offer_dict.get("location", "")}'
                    }
                    results['ai_filtered'].append(offer_dict)
                    continue

            # Pre-filtre rapide: detecter les ecoles/centres de formation par nom d'entreprise
            # Catch ce que la blacklist stricte ne couvre pas (noms partiels, variantes)
            company_lower = (offer_dict.get('company', '') or '').lower()
            title_lower = (offer_dict.get('title', '') or '').lower()
            
            SCHOOL_KEYWORDS = [
                'school', 'academy', 'ecole', 'école', 'campus', 'institut',
                'formation professionnelle', 'centre de formation',
                'lycee', 'lycée', 'college', 'collège',
                'digital school', 'coding school', 'tech school',
                'business school',
            ]
            # Mots qui ANNULENT la detection ecole (vrais employeurs avec "institut" dans le nom)
            SCHOOL_EXCEPTIONS = [
                'institut pasteur', 'institut curie', 'institut max von laue',
                'institut de france', 'institut national',
                'institut de recherche', 'institut laue-langevin',
            ]
            
            is_school_name = False
            matched_keyword = ''
            for kw in SCHOOL_KEYWORDS:
                if kw in company_lower:
                    is_school_name = True
                    matched_keyword = kw
                    break
            
            # Verifier les exceptions (instituts de recherche, etc.)
            if is_school_name:
                for exc in SCHOOL_EXCEPTIONS:
                    if exc in company_lower:
                        is_school_name = False
                        break
            
            if is_school_name:
                logger.info(
                    f"Pre-filtre: ecole detectee par nom ('{matched_keyword}'): "
                    f"'{offer_dict.get('title', '')}' @ {offer_dict.get('company', '')}"
                )
                offer_dict['ai_analysis'] = {
                    'is_school': True, 'school_confidence': 0.95,
                    'school_name': offer_dict.get('company', ''),
                    'is_relevant': False, 'relevance_score': 0.0,
                    'red_flags': [f'Ecole detectee par mot-cle: {matched_keyword}'],
                    'summary': f'Filtre statique: ecole ({matched_keyword})'
                }
                results['ai_filtered'].append(offer_dict)
                continue

            # Pre-filtre: rejeter les offres clairement hors scope
            title_lower = offer_dict.get('title', '').lower()
            desc_lower = offer_dict.get('description', '').lower()
            combined = f"{title_lower} {desc_lower}"

            # Rejeter les CDI/CDD/stages si c'est clair dans le titre
            is_not_alternance = False
            if any(w in title_lower for w in ['cdi ', ' cdi', '(cdi)', 'cdd ', ' cdd', '(cdd)',
                                                'stage ', ' stage', '(stage)', 'freelance',
                                                'interim', 'intérim']):
                # Verifier qu'il n'y a pas "alternance" aussi dans le titre
                if 'alternance' not in title_lower and 'apprentissage' not in title_lower:
                    is_not_alternance = True

            if is_not_alternance:
                logger.info(
                    f"Pre-filtre: pas une alternance: '{offer_dict.get('title', '')}' "
                    f"@ {offer_dict.get('company', '')}"
                )
                offer_dict['ai_analysis'] = {
                    'is_school': False, 'school_confidence': 0.0, 'school_name': '',
                    'is_relevant': False, 'relevance_score': 0.0,
                    'red_flags': ['Pas une alternance (CDI/CDD/stage)'],
                    'summary': 'Filtre: pas une alternance'
                }
                results['ai_filtered'].append(offer_dict)
                continue

            # Pre-filtre domaine: rejeter les offres clairement NON-IT par titre
            # Ces mots dans le titre = pas de l'informatique
            NON_IT_KEYWORDS = [
                # RH / Admin
                'ressources humaines', 'assistant rh', 'chargé de recrutement',
                'gestionnaire paie', 'gestionnaire rh', 'assistant administratif',
                'assistante administrative', 'assistant de direction', 'secrétaire',
                'secretaire', 'assistant direction',
                # Paie / Gestion sociale
                'paie', 'gestion sociale', 'contrôle de gestion sociale',
                'controle de gestion sociale',
                # Gestion (non-IT) — "assistant(e) de gestion" etc.
                'assistant de gestion', 'assistante de gestion',
                'assistant(e) de gestion',
                'assistant gestion', 'assistante gestion',
                # Commerce / Vente / Marketing
                'vendeur', 'vendeuse', 'commercial', 'commerciale',
                'chargé de communication', 'chargée de communication',
                'chargé de com', 'chargée de com',
                'community manager', 'marketing digital', 'chef de produit',
                'chef de produits', 'key account', 'account manager',
                'e-commerce', 'ecommerce', 'trade marketing',
                'assistant commercial', 'assistante commerciale',
                'assistant marketing', 'category manager',
                # Finance / Compta / Assurance
                'comptable', 'comptabilité', 'comptabilite',
                'contrôleur de gestion', 'controleur de gestion',
                'analyste financier', 'trésorerie', 'tresorerie',
                'actuariel', 'actuarielles', 'souscripteur',
                'chargé de trésorerie', 'audit financier',
                # Reporting / Pilotage (non-IT)
                'reporting', 'pilotage réseau', 'pilotage reseau',
                'pilotage commercial', 'pilotage rh',
                # Juridique
                'juriste', 'juridique', 'avocat', 'droit',
                # Logistique / Supply chain / Inventaire / Industrie non-IT
                'logistique', 'supply chain', 'acheteur', 'acheteuse',
                'gestionnaire de stock', 'flux industriels',
                'méthodes traitement', 'methodes traitement',
                'gestion des flux', 'approvisionnement',
                'inventaire', 'coordinateur performance',
                # Relation client / Conseil non-IT
                'conseiller relation', 'relation sociétaires', 'relation societaires',
                'conseiller clientèle', 'conseiller clientele',
                'relation client',
                # BTP / Immobilier
                'conducteur de travaux', 'chef de chantier', 'geometre',
                'architecte bâtiment', 'architecte batiment',
                # Sante / Social
                'infirmier', 'aide-soignant', 'educateur',
                # Education / Pedagogie
                'pédagogique', 'pedagogique',
                'chargé d\'affaire pédagogique', 'charge d\'affaire pedagogique',
                # Design / Mode / Luxe (non-IT)
                'styliste', 'modéliste', 'modeliste',
                'prêt-à-porter', 'pret-a-porter',
                'développement produit', 'developpement produit',
                'assistant pierres', 'direction pierres',
                # Qualite (non-IT) — reception, production, etc.
                'qualité réception', 'qualite reception',
                'qualité production', 'qualite production',
                'assistant qualité', 'assistante qualité',
                'assistant qualite', 'assistante qualite',
                # Operations internes (non-IT)
                'opérations internes', 'operations internes',
                # Autres non-IT
                'chargé d\'affaires spéciales',
                'learning manager', 'learning officer', 'learning & development',
                'learning development',
                'assistant learning', 'amélioration continue',
                'amelioration continue', 'clienteling',
                'chargé des opérations', 'chargée des opérations',
                'chargé des operations', 'chargee des operations',
                'digitalisation rh', 'assistant secrétaire',
                'assistant secretaire', 'chargé d\'études statistiques',
                'charge d\'etudes statistiques',
                'business analyst', 'product owner',
                'proxy product owner',
            ]

            # Phrases NON-IT prioritaires: si le titre matche une de ces phrases
            # multi-mots, on rejette SANS verifier IT_KEYWORDS_TITLE
            # (evite que "réseau" dans "pilotage réseau" sauve l'offre)
            NON_IT_PRIORITY = [
                'pilotage réseau', 'pilotage reseau',
                'pilotage commercial', 'pilotage rh',
                'relation sociétaires', 'relation societaires',
                'relation client', 'opérations internes', 'operations internes',
                'qualité réception', 'qualite reception',
                'coordinateur performance',
            ]
            is_non_it = False
            # D'abord checker les phrases prioritaires (pas d'exception IT)
            for keyword in NON_IT_PRIORITY:
                if keyword in title_lower:
                    is_non_it = True
                    break

            # Ensuite les NON_IT_KEYWORDS classiques (avec exception IT)
            if not is_non_it:
                for keyword in NON_IT_KEYWORDS:
                    if keyword in title_lower:
                        # Exception: si le titre contient aussi un mot IT, ne pas rejeter
                        IT_KEYWORDS_TITLE = [
                            'informatique', 'cyber', 'développeur', 'developpeur',
                            'devops', 'sysadmin', 'réseau', 'reseau', 'système',
                            'systeme', 'cloud', 'data engineer', 'data analyst',
                            'sécurité', 'securite', 'pentest', 'soc ', 'support it',
                            'helpdesk', 'technicien informatique', 'admin sys',
                            'fullstack', 'backend', 'frontend', 'développement web',
                            'developpement web', 'intelligence artificielle',
                            'machine learning', 'reinforcement learning',
                            'infrastructure', ' it ', ' it/',
                        ]
                        if not any(it_kw in title_lower for it_kw in IT_KEYWORDS_TITLE):
                            is_non_it = True
                            break

            if is_non_it:
                logger.info(
                    f"Pre-filtre: domaine non-IT: '{offer_dict.get('title', '')}' "
                    f"@ {offer_dict.get('company', '')}"
                )
                offer_dict['ai_analysis'] = {
                    'is_school': False, 'school_confidence': 0.0, 'school_name': '',
                    'is_relevant': False, 'relevance_score': 0.0,
                    'red_flags': [f'Domaine non-IT detecte dans le titre'],
                    'summary': 'Filtre: domaine non-IT'
                }
                results['ai_filtered'].append(offer_dict)
                continue

            # Pre-filtre: postes exclus par le candidat (IT mais pas souhaites)
            EXCLUDED_IT_ROLES = [
                'technicien proximité', 'technicien proximite',
                'technicien informatique de proximité', 'technicien informatique de proximite',
                'technicien de proximité', 'technicien de proximite',
                'informatique proximité', 'informatique proximite',
            ]
            is_excluded_role = any(kw in title_lower for kw in EXCLUDED_IT_ROLES)
            if is_excluded_role:
                logger.info(
                    f"Pre-filtre: poste exclu (proximite): '{offer_dict.get('title', '')}' "
                    f"@ {offer_dict.get('company', '')}"
                )
                offer_dict['ai_analysis'] = {
                    'is_school': False, 'school_confidence': 0.0, 'school_name': '',
                    'is_relevant': False, 'relevance_score': 0.0,
                    'red_flags': ['Poste exclu: technicien proximite'],
                    'summary': 'Filtre: technicien proximite exclu par candidat'
                }
                results['ai_filtered'].append(offer_dict)
                continue

            # L'offre passe le filtre statique, maintenant check IA
            if ai_analyzer:
                try:
                    # Analyse combinee: detection ecole + pertinence profil (1 seul appel)
                    ai_result = ai_analyzer.analyze_offer(offer_dict)
                    if ai_result:
                        offer_dict['ai_analysis'] = {
                            'is_school': ai_result.is_school,
                            'school_confidence': ai_result.school_confidence,
                            'school_name': ai_result.school_name,
                            'is_relevant': ai_result.is_relevant,
                            'relevance_score': ai_result.relevance_score,
                            'red_flags': ai_result.red_flags,
                            'summary': ai_result.summary
                        }

                        # Filtre 1: ecole deguisee
                        # Whitelist: ces grandes entreprises ne sont JAMAIS des ecoles
                        KNOWN_EMPLOYERS = [
                            'thales', 'orange', 'safran', 'capgemini', 'axa', 'edf',
                            'engie', 'storengy', 'lfb', 'sonepar', 'schneider',
                            'saint-gobain', 'alceane', 'ifremer', 'onera', 'mbda',
                            'airbus', 'dassault', 'renault', 'stellantis', 'bnp',
                            'societe generale', 'credit agricole', 'la poste', 'sncf',
                            'ratp', 'total', 'totalenergies', 'enedis', 'veolia',
                            'suez', 'bouygues', 'vinci', 'alstom', 'atos', 'sopra',
                            'accenture', 'ibm', 'microsoft', 'google', 'amazon',
                            'meta', 'apple', 'oracle', 'sap', 'salesforce',
                            'lvmh', 'hermes', 'hermès', 'chanel', 'dior', 'kering',
                            'carrefour', 'auchan', 'leclerc', 'decathlon',
                            'michelin', 'danone', 'nestle', 'pernod', 'loreal',
                            "l'oreal", "l'oréal", 'sanofi', 'servier', 'biogaran',
                            'pfizer', 'roche', 'bayer', 'novartis',
                            'france televisions', 'france télévisions', 'radio france',
                            'tf1', 'canal+', 'm6',
                            'lafarge', 'legrand', 'valeo', 'faurecia', 'forvia',
                            'stmicroelectronics', 'amadeus', 'worldline', 'ingenico',
                            'docaret', 'atmb', 'smcp', 'fred', 'bon marché',
                            'samaritaine', 'valentino', 'mcdonald', 'howmet',
                            'abeille assurances', 'cnp assurances', 'allianz',
                            'volkswagen', 'verisure', 'siemens', 'bosch',
                            'fayat', 'eiffage', 'socotec', 'bureau veritas',
                            'altares', 'onepoint', 'steamulo', 'urban linker',
                            'mutuelle des architectes', 'groupe ermitage',
                        ]
                        company_check = (offer_dict.get('company', '') or '').lower()
                        is_known_employer = any(emp in company_check for emp in KNOWN_EMPLOYERS)
                        
                        if ai_result.is_school and ai_result.school_confidence >= 0.7 and not is_known_employer:
                            logger.warning(
                                f"IA: ecole deguisee detectee: '{offer_dict.get('title', '')}' "
                                f"@ {offer_dict.get('company', '')} "
                                f"(confiance: {ai_result.school_confidence:.0%}, "
                                f"ecole: {ai_result.school_name})"
                            )
                            results['ai_filtered'].append(offer_dict)
                            continue

                        # Filtre 2: pertinence IA DESACTIVE
                        # Le modele qwen2.5:3b donne 0% meme a des offres IT parfaitement valides
                        # (ex: "Ingenieur Systeme @ Thales" → 0%). Les pre-filtres statiques
                        # (non-IT, geo, ecole par nom, CDI/CDD, technicien proximite) sont plus fiables.
                        # On log juste le score pour debug, sans rejeter.
                        if ai_result.relevance_score < 0.3:
                            logger.debug(
                                f"IA: score bas (non bloquant): '{offer_dict.get('title', '')}' "
                                f"@ {offer_dict.get('company', '')} "
                                f"(pertinence: {ai_result.relevance_score:.0%})"
                            )

                except Exception as e:
                    logger.debug(f"Erreur analyse IA: {e}")
                    # En cas d'erreur IA, on laisse passer l'offre

            results['safe'].append(offer_dict)
        elif check.level == ScamLevel.QUARANTINE:
            results['quarantine'].append(offer_dict)
        else:
            results['dangerous'].append(offer_dict)

    if ai_analyzer and results['ai_filtered']:
        schools = [o for o in results['ai_filtered'] if o.get('ai_analysis', {}).get('is_school', False)]
        irrelevant = [o for o in results['ai_filtered'] if not o.get('ai_analysis', {}).get('is_school', False)]
        logger.info(
            f"IA: {len(results['ai_filtered'])} offre(s) filtree(s) "
            f"({len(schools)} ecoles, {len(irrelevant)} non pertinentes)"
        )

    return results


def apply_to_offers(safe_offers: list, config: dict, browser=None, notifier=None, ai_client=None) -> dict:
    """Postule automatiquement aux offres safe.
    
    Retourne un dict avec les stats: applied, failed, skipped, external
    """
    apply_config = config.get('apply', {})
    if not apply_config.get('enabled', False):
        logger.info("Candidature auto desactivee dans la config")
        return {'applied': 0, 'failed': 0, 'skipped': 0, 'external': 0}

    profile = config.get('profile', {})
    max_per_session = apply_config.get('max_per_session', 20)
    delay = apply_config.get('delay_between_applies', 30)

    # Charger les URLs deja postulees
    already_applied = load_applied()

    # Filtrer les offres deja traitees
    to_apply = [o for o in safe_offers if o['url'] not in already_applied]
    if not to_apply:
        logger.info("Toutes les offres safe ont deja ete traitees")
        return {'applied': 0, 'failed': 0, 'skipped': 0, 'external': 0}

    # Trier par priorite de plateforme: HelloWork > WTTJ > LinkedIn > France Travail > APEC > Indeed
    # Indeed est bloque par CAPTCHA, on le met en dernier
    # WTTJ et APEC sont en externe (notification Telegram), priorite intermediaire
    platform_priority = {'hellowork': 0, 'wttj': 1, 'linkedin': 2, 'francetravail': 3, 'apec': 4, 'indeed': 5}
    to_apply.sort(key=lambda o: platform_priority.get(o.get('platform', ''), 99))

    # Limiter au max par session
    to_apply = to_apply[:max_per_session]
    logger.info(f"Candidatures a envoyer: {len(to_apply)}")

    # Creer les applicators
    # Indeed est reactive UNIQUEMENT si 2captcha est configure (sinon search only)
    # LinkedIn: pas d'applicator (sessions revoquees) — notification Telegram pour postulation manuelle
    captcha_solver = create_solver(config)
    linkedin_config = config.get('platforms', {}).get('linkedin', {})
    applicators = {
        'hellowork': HelloWorkApplicator(profile, browser=browser, ai_client=ai_client, config=config) if browser else None,
        'francetravail': FranceTravailApplicator(profile, browser=browser, ai_client=ai_client, config=config) if browser else None,
        'wttj': WTTJApplicator(profile, browser=browser, ai_client=ai_client, config=config),
        'apec': APECApplicator(profile, config=config),
    }
    # LinkedIn: apply desactive (anti-bot revoque les sessions)
    # Les offres LinkedIn sont envoyees via Telegram pour postulation manuelle
    if linkedin_config.get('apply_enabled', False) and browser:
        easy_apply_only = linkedin_config.get('easy_apply_only', True)
        applicators['linkedin'] = LinkedInApplicator(
            profile, browser=browser, ai_client=ai_client,
            easy_apply_only=easy_apply_only
        )
        logger.info(f"LinkedIn Apply active (easy_apply_only={easy_apply_only})")
    else:
        logger.info("LinkedIn Apply desactive — offres envoyees via Telegram pour postulation manuelle")

    if captcha_solver and browser:
        applicators['indeed'] = IndeedApplicator(profile, browser=browser, captcha_solver=captcha_solver, ai_client=ai_client)
        logger.info("Indeed Apply active avec 2captcha")
    else:
        logger.info("Indeed Apply desactive (pas de cle 2captcha)")

    stats = {'applied': 0, 'failed': 0, 'skipped': 0, 'external': 0}

    for i, offer in enumerate(to_apply):
        platform = offer.get('platform', '')
        applicator = applicators.get(platform)

        if not applicator:
            # LinkedIn: envoyer via Telegram pour postulation manuelle
            if platform == 'linkedin' and notifier:
                title = offer.get('title', 'Sans titre')
                company = offer.get('company', 'Inconnue')
                location = offer.get('location', '')
                url = offer.get('url', '')
                ai_summary = offer.get('ai_analysis', {}).get('summary', '')

                msg = (
                    f"<b>OFFRE LINKEDIN</b> (postule manuellement)\n\n"
                    f"<b>{title}</b>\n"
                    f"Entreprise: {company}\n"
                )
                if location:
                    msg += f"Lieu: {location}\n"
                if ai_summary:
                    msg += f"\n<b>Analyse IA:</b> {ai_summary}\n"
                msg += f"\n<b>Postule ici:</b> {url}\n"
                msg += f"\n{datetime.now(PARIS_TZ).strftime('%d/%m/%Y %H:%M')}"

                notifier.send(msg)
                logger.info(f"  LinkedIn: notification Telegram envoyee pour '{title}' @ {company}")

                # Sauvegarder comme "manual" dans applied.json
                save_applied({
                    'url': offer['url'],
                    'offer_title': title,
                    'company': company,
                    'platform': 'linkedin',
                    'status': 'manual',
                    'details': 'Envoye via Telegram pour postulation manuelle',
                })
                stats['external'] += 1
                continue

            logger.debug(f"Pas d'applicator pour {platform}, skip")
            stats['skipped'] += 1
            continue

        logger.info(f"[{i+1}/{len(to_apply)}] Candidature: {offer['title']} @ {offer['company']} ({platform})")

        # Recuperer le resume IA si disponible
        ai_summary = offer.get('ai_analysis', {}).get('summary', '')

        try:
            result = applicator.apply(offer)

            # Sauvegarder le resultat
            save_applied(result.to_dict())

            if result.success:
                stats['applied'] += 1
                logger.info(f"  -> POSTULE avec succes")
                if notifier:
                    notifier.notify_application(offer, success=True, details=result.details,
                                                ai_summary=ai_summary)

            elif result.status.value == 'external':
                stats['external'] += 1
                details = result.external_url or result.contact_email or result.details
                logger.info(f"  -> EXTERNE: {details}")
                if notifier:
                    notifier.notify_application(offer, success=True,
                        details=f"Lien externe: {details}", ai_summary=ai_summary)

            elif result.status.value == 'login':
                stats['failed'] += 1
                logger.warning(f"  -> LOGIN REQUIS: {result.details}")
                if notifier:
                    notifier.notify_application(offer, success=False,
                        details=f"Connexion requise — {result.details}")
                # Arreter les candidatures sur cette plateforme (pas connecte)
                logger.warning(
                    f"  -> Arret des candidatures {platform}: pas connecte au compte. "
                    "Importe tes cookies pour continuer."
                )
                if notifier:
                    notifier.send(
                        f"⚠️ Candidatures {platform} ARRETEES — pas connecte au compte.\n"
                        f"Lance: python3 agent.py --import-cookies cookies.txt"
                    )
                # Skip toutes les offres restantes de cette plateforme
                stats['skipped'] += sum(1 for o in to_apply[i+1:] if o.get('platform') == platform)
                break

            elif result.status.value == 'skipped':
                stats['skipped'] += 1
                logger.info(f"  -> SKIP: {result.details}")

            else:
                stats['failed'] += 1
                logger.warning(f"  -> ECHEC: {result.details}")
                if notifier:
                    notifier.notify_application(offer, success=False, details=result.details)

        except Exception as e:
            stats['failed'] += 1
            logger.error(f"  -> ERREUR: {e}")

        # Pause entre les candidatures (adapte par plateforme)
        if i < len(to_apply) - 1:
            if platform == 'hellowork':
                wait = random.randint(10, 15)  # HelloWork SmartApply: 10-15s suffit
            elif platform == 'linkedin':
                wait = random.randint(20, 35)  # LinkedIn: 20-35s (plus prudent, anti-bot)
            else:
                wait = delay  # Autres plateformes: delai config (30s)
            logger.debug(f"  Pause {wait}s avant la prochaine candidature")
            time.sleep(wait)

    return stats


def print_results(results: dict, apply_stats: dict = None):
    """Affiche les resultats"""
    print("\n" + "=" * 60)
    print(f"  RESULTATS SYLPH - {datetime.now(PARIS_TZ).strftime('%d/%m/%Y %H:%M')}")
    print("=" * 60)

    print(f"\n  Total: {results['total']} offres trouvees")
    print(f"  Safe: {len(results['safe'])}")
    print(f"  Quarantaine: {len(results['quarantine'])}")
    print(f"  Dangereuses: {len(results['dangerous'])}")
    ai_filtered = results.get('ai_filtered', [])
    if ai_filtered:
        print(f"  Filtrees par IA (ecoles): {len(ai_filtered)}")

    if apply_stats:
        print(f"\n  --- CANDIDATURES ---")
        print(f"  Envoyees: {apply_stats['applied']}")
        print(f"  Externes: {apply_stats['external']}")
        print(f"  Echouees: {apply_stats['failed']}")
        print(f"  Skippees: {apply_stats['skipped']}")

    if results['safe']:
        print("\n--- OFFRES VALIDEES ---")
        for i, offer in enumerate(results['safe'][:20], 1):  # Limiter l'affichage
            print(f"\n  {i}. {offer['title']}")
            print(f"     Entreprise: {offer['company']}")
            print(f"     Plateforme: {offer['platform']}")
            print(f"     URL: {offer['url']}")

        if len(results['safe']) > 20:
            print(f"\n  ... et {len(results['safe']) - 20} autres offres")

    if results['quarantine']:
        print("\n--- OFFRES EN QUARANTAINE ---")
        for i, offer in enumerate(results['quarantine'], 1):
            reasons = offer.get('scam_check', {}).get('reasons', [])
            print(f"\n  {i}. {offer['title']} @ {offer['company']}")
            print(f"     Raisons: {', '.join(reasons)}")

    if results['dangerous']:
        print(f"\n--- {len(results['dangerous'])} OFFRES DANGEREUSES (bloquees) ---")

    ai_filtered_list = results.get('ai_filtered', [])
    if ai_filtered_list:
        print(f"\n--- FILTREES PAR IA ({len(ai_filtered_list)}) ---")
        for i, offer in enumerate(ai_filtered_list, 1):
            ai_info = offer.get('ai_analysis', {})
            print(f"  {i}. {offer['title']} @ {offer['company']}")
            if ai_info.get('is_school', False):
                school = ai_info.get('school_name', '?')
                conf = ai_info.get('school_confidence', 0)
                print(f"     Ecole detectee: {school} (confiance: {conf:.0%})")
            else:
                relevance = ai_info.get('relevance_score', 0)
                summary = ai_info.get('summary', '')
                print(f"     Non pertinent (score: {relevance:.0%}) - {summary}")

    print("\n" + "=" * 60)


COOKIES_FILE = os.path.join(BASE_DIR, "cookies.txt")


def run_import_cookies(cookies_path: str, config: dict):
    """Importe les cookies depuis un fichier cookies.txt (format Netscape).
    
    Les cookies sont injectes dans le profil Chromium persistant pour que
    les prochaines sessions soient connectees aux plateformes.
    
    Usage:
        1. Sur ton PC, connecte-toi a HelloWork/Indeed/FT
        2. Exporte les cookies avec l'extension 'Get cookies.txt LOCALLY'
        3. Copie le fichier sur le serveur: scp cookies.txt user@server:~/sylph/
        4. Lance: python3 agent.py --import-cookies cookies.txt
    """
    if not os.path.exists(cookies_path):
        print(f"  Erreur: fichier '{cookies_path}' introuvable.")
        print(f"  Usage: python3 agent.py --import-cookies cookies.txt")
        return

    # Parser le fichier cookies.txt (format Netscape)
    cookies = _parse_cookies_txt(cookies_path)
    if not cookies:
        print("  Erreur: aucun cookie valide trouve dans le fichier.")
        print("  Verifie que c'est bien un fichier cookies.txt (format Netscape).")
        return

    # Filtrer les cookies par plateforme
    platforms = {
        'hellowork': ['.hellowork.com', 'www.hellowork.com', 'hellowork.com'],
        'indeed': ['.indeed.com', 'fr.indeed.com', 'secure.indeed.com', 'indeed.com'],
        'francetravail': ['.francetravail.fr', 'candidat.francetravail.fr', 'francetravail.fr'],
        'linkedin': ['.linkedin.com', 'www.linkedin.com', 'linkedin.com'],
    }

    platform_cookies = {}
    for name, domains in platforms.items():
        matching = [c for c in cookies if any(c['domain'].endswith(d.lstrip('.')) or c['domain'] == d for d in domains)]
        if matching:
            platform_cookies[name] = matching

    print(f"\n  Cookies trouves: {len(cookies)} total")
    for name, cks in platform_cookies.items():
        print(f"    {name}: {len(cks)} cookies")

    if not platform_cookies:
        print("\n  Aucun cookie de plateforme reconnue. Assure-toi d'etre connecte")
        print("  a HelloWork/Indeed/France Travail avant d'exporter les cookies.")
        return

    # Sauvegarder en JSON interne pour injection dans Selenium
    cookies_json_path = os.path.join(os.path.dirname(cookies_path) or '.', 'logs', 'cookies.json')
    Path(cookies_json_path).parent.mkdir(parents=True, exist_ok=True)

    with open(cookies_json_path, 'w') as f:
        json.dump(cookies, f, indent=2, ensure_ascii=False)

    print(f"\n  Cookies sauvegardes dans {cookies_json_path}")

    # Tester l'injection dans Selenium
    print("\n  Test d'injection des cookies dans Chromium...")
    profile_dir = config.get('browser', {}).get('profile_dir', os.path.join(os.path.expanduser('~'), '.sylph-profile'))
    browser = create_stealth_browser(headless=True, profile_dir=profile_dir)
    try:
        browser.start()
        driver = browser.driver

        for name, cks in platform_cookies.items():
            # Naviguer vers le domaine pour pouvoir injecter les cookies
            domain = cks[0]['domain'].lstrip('.')
            try:
                driver.get(f"https://{domain}")
                time.sleep(2)

                injected = 0
                for cookie in cks:
                    try:
                        selenium_cookie = {
                            'name': cookie['name'],
                            'value': cookie['value'],
                            'domain': cookie['domain'],
                            'path': cookie.get('path', '/'),
                            'secure': cookie.get('secure', False),
                        }
                        if cookie.get('expiry'):
                            selenium_cookie['expiry'] = int(cookie['expiry'])
                        driver.add_cookie(selenium_cookie)
                        injected += 1
                    except Exception as e:
                        pass  # Certains cookies peuvent echouer (domaine different)

                print(f"    {name}: {injected}/{len(cks)} cookies injectes")

            except Exception as e:
                print(f"    {name}: erreur — {e}")

        # Verifier la connexion HelloWork
        if 'hellowork' in platform_cookies:
            print("\n  Verification connexion HelloWork...")
            driver.get("https://www.hellowork.com/fr-fr/mon-espace.html")
            time.sleep(3)
            url = driver.current_url
            if 'login' in url or 'connexion' in url:
                print("    -> PAS connecte (redirige vers login)")
                print("    Les cookies ont peut-etre expire. Re-exporte-les.")
            else:
                print("    -> CONNECTE a HelloWork!")

        # Verifier la connexion Indeed
        if 'indeed' in platform_cookies:
            print("\n  Verification connexion Indeed...")
            driver.get("https://fr.indeed.com/account/view")
            time.sleep(3)
            url = driver.current_url
            page_text = driver.page_source.lower()
            if 'login' in url or 'signin' in url or 'secure.indeed' in url:
                print("    -> PAS connecte (redirige vers login)")
                print("    Les cookies ont peut-etre expire. Re-exporte-les.")
            elif 'captcha' in page_text or 'robot' in page_text:
                print("    -> Bloque par CAPTCHA (impossible de verifier)")
            else:
                print("    -> CONNECTE a Indeed!")

        # Verifier la connexion LinkedIn
        if 'linkedin' in platform_cookies:
            print("\n  Verification connexion LinkedIn...")
            driver.get("https://www.linkedin.com/feed/")
            time.sleep(3)
            url = driver.current_url
            if 'login' in url or 'authwall' in url or 'signup' in url:
                print("    -> PAS connecte (redirige vers login)")
                print("    Les cookies ont peut-etre expire. Re-exporte-les.")
            else:
                print("    -> CONNECTE a LinkedIn!")

    except Exception as e:
        print(f"\n  Erreur: {e}")
    finally:
        browser.quit()

    print("\n  Import termine. Les sessions seront utilisees par l'agent.\n")


def _parse_cookies_txt(filepath: str) -> list:
    """Parse un fichier cookies.txt au format Netscape.
    
    Format: domain\tHTTPONLY\tpath\tsecure\texpiry\tname\tvalue
    Les lignes commencant par # sont des commentaires.
    """
    cookies = []
    try:
        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split('\t')
                if len(parts) >= 7:
                    domain = parts[0]
                    # Netscape format: col 0=domain, 1=flag, 2=path, 3=secure, 4=expiry, 5=name, 6=value
                    cookie = {
                        'domain': domain,
                        'path': parts[2],
                        'secure': parts[3].upper() == 'TRUE',
                        'expiry': int(parts[4]) if parts[4] != '0' else None,
                        'name': parts[5],
                        'value': parts[6],
                    }
                    cookies.append(cookie)
    except Exception as e:
        print(f"  Erreur lecture cookies.txt: {e}")
    return cookies


def show_quarantine(config: dict):
    """Affiche et gere les offres en quarantaine"""
    scam_detector = create_detector(config)
    pending = scam_detector.get_quarantine()

    if not pending:
        print("Aucune offre en quarantaine.")
        return

    print(f"\n--- {len(pending)} offre(s) en quarantaine ---\n")
    for i, offer in enumerate(pending):
        print(f"  {i + 1}. {offer['title']} @ {offer['company']}")
        print(f"     Score: {offer['score']}")
        print(f"     Raisons: {', '.join(offer['reasons'])}")
        print(f"     URL: {offer['url']}")
        print()

    print("Commandes: approve <num> | reject <num> | quit")
    while True:
        try:
            cmd = input("> ").strip()
            if cmd == 'quit' or cmd == 'q':
                break
            parts = cmd.split()
            if len(parts) == 2:
                action, num = parts[0], int(parts[1]) - 1
                if action == 'approve':
                    if scam_detector.approve_quarantine(num):
                        print(f"  Offre {num + 1} approuvee")
                    else:
                        print("  Index invalide")
                elif action == 'reject':
                    if scam_detector.reject_quarantine(num):
                        print(f"  Offre {num + 1} rejetee")
                    else:
                        print("  Index invalide")
            else:
                print("  Usage: approve <num> | reject <num> | quit")
        except (KeyboardInterrupt, EOFError):
            break
        except ValueError:
            print("  Numero invalide")


def run_once(config: dict, search_only: bool = False):
    """Execute une seule recherche (+ candidatures si pas search_only)"""
    logger.info("=== Recherche Sylph ===")

    # Telegram notifier
    notifier = create_notifier(config)

    # Client IA (Ollama)
    ai_client = create_ai_client(config)
    ai_analyzer = create_analyzer(ai_client)

    # Requester HTTP (France Travail)
    requester = create_requester()

    # Navigateur stealth (Indeed + HelloWork + candidatures)
    browser = None
    platforms_config = config.get('platforms', {})
    need_browser = (
        platforms_config.get('indeed', {}).get('enabled', False) or
        platforms_config.get('hellowork', {}).get('enabled', False) or
        (not search_only and config.get('apply', {}).get('enabled', False))
    )

    if need_browser:
        try:
            profile_dir = config.get('browser', {}).get('profile_dir')
            browser = create_stealth_browser(headless=True, profile_dir=profile_dir)
            browser.start()
            browser.load_cookies()  # Injecter les sessions sauvegardees
        except Exception as e:
            logger.error(f"Impossible de demarrer le navigateur: {e}")
            logger.info("Les plateformes Selenium seront desactivees")
            browser = None

    try:
        # 1. Rechercher les offres
        offers = search_all_platforms(config, browser=browser, requester=requester)
        logger.info(f"Total brut: {len(offers)} offres")

        if not offers:
            logger.info("Aucune offre trouvee.")
            print("\nAucune offre trouvee.")
            if notifier:
                notifier.notify_error("Aucune offre trouvee dans la recherche")
            return

        # 2. Deduplication: ne garder que les nouvelles offres (pas dans offers.json)
        existing_urls = set()
        try:
            if os.path.exists(OFFERS_FILE):
                with open(OFFERS_FILE, 'r') as f:
                    existing = json.load(f)
                    existing_urls = {o.get('url') for o in existing if o.get('url')}
        except Exception:
            pass

        new_offers = []
        for o in offers:
            od = o.to_dict() if hasattr(o, 'to_dict') else o
            if od.get('url') not in existing_urls:
                new_offers.append(o)

        logger.info(f"Deduplication: {len(new_offers)} nouvelles offres sur {len(offers)} (deja connues: {len(offers) - len(new_offers)})")

        if not new_offers:
            logger.info("Aucune nouvelle offre.")
            print("\nAucune nouvelle offre.")
            if notifier:
                notifier.notify_error("Aucune nouvelle offre dans cette recherche")
            return

        # 3. Analyser avec le detecteur d'arnaques + IA (uniquement les nouvelles)
        scam_detector = create_detector(config)
        results = analyze_offers(new_offers, scam_detector, ai_analyzer=ai_analyzer)

        # 4. Sauvegarder les offres safe
        if results['safe']:
            new_count = save_offers(results['safe'])
            logger.info(f"{new_count} nouvelles offres sauvegardees")

        # 5. Candidatures automatiques (sauf si search_only)
        apply_stats = None
        if not search_only and results['safe']:
            apply_stats = apply_to_offers(
                results['safe'], config, browser=browser, notifier=notifier,
                ai_client=ai_client
            )

        # 6. Afficher les resultats
        print_results(results, apply_stats)

        # 7. Envoyer le resume Telegram
        if notifier:
            applied = apply_stats['applied'] if apply_stats else 0
            failed = apply_stats['failed'] if apply_stats else 0
            notifier.notify_summary(
                total_found=results['total'],
                applied=applied,
                failed=failed,
                blocked=len(results['dangerous'])
            )

    finally:
        if browser:
            browser.quit()

    logger.info("=== Recherche terminee ===")


def _parse_time(time_str) -> tuple[int, int]:
    """Parse un horaire 'HH:MM' ou int (heure seule) en (heure, minute)"""
    if isinstance(time_str, str) and ':' in time_str:
        parts = time_str.split(':')
        return int(parts[0]), int(parts[1])
    return int(time_str), 0


def run_continuous(config: dict):
    """Mode continu - recherche reguliere entre 8h et 16h30, avec compte rendu de fin de journee"""
    logger.info("=== Mode continu Sylph demarre ===")
    automation = config.get('automation', {})
    delay = automation.get('delay_between_applications', 3600)

    start_h, start_m = _parse_time(automation.get('active_hours', {}).get('start', '08:00'))
    end_h, end_m = _parse_time(automation.get('active_hours', {}).get('end', '16:30'))

    # Demarrer le bot Telegram interactif (thread daemon)
    ai_client = create_ai_client(config)
    telegram_bot = create_bot(config, ai_client=ai_client)
    if telegram_bot:
        telegram_bot.start()
        logger.info("Bot Telegram interactif demarre")

    # Stats de la journee
    day_stats = {
        'searches': 0,
        'total_found': 0,
        'applied': 0,
        'failed': 0,
        'skipped': 0,
        'external': 0,
        'blocked': 0,
        'errors': 0,
        'date': datetime.now(PARIS_TZ).strftime('%d/%m/%Y'),
    }
    recap_sent_today = False

    while running:
        now = datetime.now(PARIS_TZ)
        current_minutes = now.hour * 60 + now.minute
        start_minutes = start_h * 60 + start_m
        end_minutes = end_h * 60 + end_m

        # Reset stats si nouveau jour
        today = now.strftime('%d/%m/%Y')
        if today != day_stats['date']:
            day_stats = {
                'searches': 0, 'total_found': 0, 'applied': 0,
                'failed': 0, 'skipped': 0, 'external': 0,
                'blocked': 0, 'errors': 0, 'date': today,
            }
            recap_sent_today = False

        if start_minutes <= current_minutes < end_minutes:
            # === Dans les heures actives: lancer une recherche ===
            logger.info("Lancement d'une recherche...")
            try:
                stats = run_once_with_stats(config)
                day_stats['searches'] += 1
                day_stats['total_found'] += stats.get('total_found', 0)
                day_stats['applied'] += stats.get('applied', 0)
                day_stats['failed'] += stats.get('failed', 0)
                day_stats['skipped'] += stats.get('skipped', 0)
                day_stats['external'] += stats.get('external', 0)
                day_stats['blocked'] += stats.get('blocked', 0)
            except Exception as e:
                logger.error(f"Erreur pendant la recherche: {e}")
                day_stats['errors'] += 1
                try:
                    notifier = create_notifier(config)
                    if notifier:
                        notifier.notify_error(f"Erreur pendant la recherche: {e}")
                except Exception:
                    pass

        elif current_minutes >= end_minutes and not recap_sent_today:
            # === Fin de journee: envoyer le compte rendu ===
            logger.info("Fin de journee - envoi du compte rendu...")
            _send_daily_recap(config, day_stats)
            recap_sent_today = True

        else:
            logger.info(f"Hors heures actives ({start_h:02d}:{start_m:02d}-{end_h:02d}:{end_m:02d}). Attente...")

        logger.info(f"Prochaine verification dans {delay}s")
        for _ in range(delay):
            if not running:
                break
            time.sleep(1)

    # Arreter le bot Telegram
    if telegram_bot:
        telegram_bot.stop()

    logger.info("=== Mode continu arrete ===")


def run_once_with_stats(config: dict) -> dict:
    """Execute une recherche + candidatures et retourne les stats pour le recap journalier"""
    logger.info("=== Recherche Sylph ===")

    notifier = create_notifier(config)
    ai_client = create_ai_client(config)
    ai_analyzer = create_analyzer(ai_client)
    requester = create_requester()
    browser = None
    platforms_config = config.get('platforms', {})
    need_browser = (
        platforms_config.get('indeed', {}).get('enabled', False) or
        platforms_config.get('hellowork', {}).get('enabled', False) or
        config.get('apply', {}).get('enabled', False)
    )

    if need_browser:
        try:
            profile_dir = config.get('browser', {}).get('profile_dir')
            browser = create_stealth_browser(headless=True, profile_dir=profile_dir)
            browser.start()
            browser.load_cookies()  # Injecter les sessions sauvegardees
        except Exception as e:
            logger.error(f"Impossible de demarrer le navigateur: {e}")
            browser = None

    stats = {'total_found': 0, 'applied': 0, 'failed': 0, 'skipped': 0, 'external': 0, 'blocked': 0, 'ai_filtered': 0}

    try:
        offers = search_all_platforms(config, browser=browser, requester=requester)
        logger.info(f"Total brut: {len(offers)} offres")

        if not offers:
            logger.info("Aucune offre trouvee.")
            if notifier:
                notifier.notify_error("Aucune offre trouvee dans la recherche")
            return stats

        scam_detector = create_detector(config)
        results = analyze_offers(offers, scam_detector, ai_analyzer=ai_analyzer)
        stats['total_found'] = results['total']
        stats['blocked'] = len(results['dangerous'])
        stats['ai_filtered'] = len(results.get('ai_filtered', []))

        if results['safe']:
            new_count = save_offers(results['safe'])
            logger.info(f"{new_count} nouvelles offres sauvegardees")

        if results['safe']:
            apply_stats = apply_to_offers(
                results['safe'], config, browser=browser, notifier=notifier,
                ai_client=ai_client
            )
            stats['applied'] = apply_stats['applied']
            stats['failed'] = apply_stats['failed']
            stats['skipped'] = apply_stats['skipped']
            stats['external'] = apply_stats['external']

        print_results(results, apply_stats if results['safe'] else None)

        if notifier:
            notifier.notify_summary(
                total_found=results['total'],
                applied=stats['applied'],
                failed=stats['failed'],
                blocked=stats['blocked']
            )

    finally:
        if browser:
            browser.quit()

    logger.info("=== Recherche terminee ===")
    return stats


def _send_daily_recap(config: dict, day_stats: dict):
    """Envoie le compte rendu de fin de journee sur Telegram"""
    notifier = create_notifier(config)
    if not notifier:
        return

    # Charger applied.json complet
    today = day_stats['date']
    all_applied = []
    today_applied = []
    path = Path(APPLIED_FILE)
    if path.exists():
        try:
            with open(path) as f:
                all_applied = json.load(f)
            today_str = datetime.now(PARIS_TZ).strftime('%Y-%m-%d')
            for entry in all_applied:
                ts = entry.get('timestamp', '')
                if ts.startswith(today_str):
                    today_applied.append(entry)
        except Exception:
            pass

    # Charger offers.json pour le total global
    total_offers = 0
    offers_path = Path(OFFERS_FILE)
    if offers_path.exists():
        try:
            with open(offers_path) as f:
                total_offers = len(json.load(f))
        except Exception:
            pass

    # Stats du jour
    successes = [a for a in today_applied if a.get('status') == 'success']
    externals = [a for a in today_applied if a.get('status') == 'external']
    failures = [a for a in today_applied if a.get('status') in ('failed', 'captcha')]

    # Stats globales (tout l'historique)
    all_successes = sum(1 for a in all_applied if a.get('status') == 'success')
    all_externals = sum(1 for a in all_applied if a.get('status') == 'external')
    all_failures = sum(1 for a in all_applied if a.get('status') in ('failed', 'captcha'))

    msg = (
        f"<b>COMPTE RENDU SYLPH - {today}</b>\n"
        f"{'=' * 30}\n\n"
        f"<b>AUJOURD'HUI</b>\n"
        f"Recherches effectuees: {day_stats['searches']}\n"
        f"Offres trouvees: {day_stats['total_found']}\n"
        f"Offres bloquees (scam): {day_stats['blocked']}\n"
        f"Candidatures envoyees: {len(successes)}\n"
        f"Liens externes: {len(externals)}\n"
        f"Echouees: {len(failures)}\n"
        f"Erreurs systeme: {day_stats['errors']}\n"
    )

    if successes:
        msg += f"\n<b>Candidatures du jour:</b>\n"
        for a in successes[:15]:
            msg += f"  - {a.get('offer_title', '?')} @ {a.get('company', '?')} ({a.get('platform', '?')})\n"
        if len(successes) > 15:
            msg += f"  ... et {len(successes) - 15} autres\n"

    if externals:
        msg += f"\n<b>Liens externes du jour:</b>\n"
        for a in externals[:10]:
            detail = a.get('external_url', '') or a.get('contact_email', '') or a.get('details', '')
            msg += f"  - {a.get('offer_title', '?')} @ {a.get('company', '?')}: {detail}\n"

    msg += (
        f"\n{'=' * 30}\n"
        f"<b>TOTAL GLOBAL</b>\n"
        f"Offres en base: {total_offers}\n"
        f"Candidatures envoyees: {all_successes}\n"
        f"Liens externes: {all_externals}\n"
        f"Echouees: {all_failures}\n"
        f"Total tentatives: {len(all_applied)}\n"
    )

    msg += f"\nFin de journee a {datetime.now(PARIS_TZ).strftime('%H:%M')}. A demain!"

    notifier.send(msg)
    logger.info("Compte rendu de fin de journee envoye sur Telegram")


def main():
    global logger, app_logger

    parser = argparse.ArgumentParser(description="Sylph - Agent de recherche d'alternance")
    parser.add_argument('--once', action='store_true', help="Une seule recherche + candidatures")
    parser.add_argument('--search-only', action='store_true', help="Recherche sans postuler")
    parser.add_argument('--quarantine', action='store_true', help="Gerer la quarantaine")
    parser.add_argument('--import-cookies', metavar='FILE', help="Importer cookies.txt depuis ton navigateur")
    parser.add_argument('--config', default='config.yaml', help="Fichier de config")
    args = parser.parse_args()

    # Charger la config
    config = load_config(args.config)

    # Setup logger
    log_file = config.get('logging', {}).get('file', os.path.join(BASE_DIR, 'logs', 'agent.log'))
    log_level = config.get('logging', {}).get('level', 'INFO')
    logger = setup_logger("job-agent", log_file, log_level)
    app_logger = ApplicationLogger(logger)

    # Signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    logger.info("Sylph - Agent de recherche d'alternance")

    if args.quarantine:
        show_quarantine(config)
    elif args.import_cookies:
        run_import_cookies(args.import_cookies, config)
    elif args.once or args.search_only:
        run_once(config, search_only=args.search_only)
    else:
        run_continuous(config)


if __name__ == "__main__":
    main()
