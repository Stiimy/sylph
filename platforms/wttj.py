"""Plateforme Welcome to the Jungle (WTTJ) - Recherche via API Algolia.

WTTJ utilise Algolia pour la recherche. Les credentials sont publiques
(embarquees dans le frontend). La recherche fonctionne en HTTP pur
sans Selenium — il suffit d'envoyer le bon Referer.

Candidature automatique IMPOSSIBLE:
- reCAPTCHA v3 sur le formulaire
- Auth requise pour postuler
- La majorite des offres redirigent vers des ATS externes (Workday, Lever, etc.)

Strategie: recherche + notification Telegram pour candidature manuelle.
"""

from .base import Platform, JobOffer
import requests
import logging
import time
import random

logger = logging.getLogger("job-agent")

# Algolia credentials (publiques, embarquees dans le frontend WTTJ)
ALGOLIA_APP_ID = "CSEKHVMS53"
ALGOLIA_API_KEY = "4bd8f6215d0cc52b26430765769e65a0"
ALGOLIA_INDEX = "wttj_jobs_production_fr"
ALGOLIA_URL = f"https://{ALGOLIA_APP_ID}-dsn.algolia.net/1/indexes/{ALGOLIA_INDEX}/query"

# Coordonnees de Paris pour la recherche geographique
PARIS_LAT = 48.8566
PARIS_LNG = 2.3522


class WTTJPlatform(Platform):
    """Recherche d'offres sur Welcome to the Jungle via l'API Algolia.

    Pas besoin de Selenium — HTTP pur avec l'API Algolia publique.
    """

    def __init__(self, config: dict, browser=None):
        super().__init__(config, driver=None)
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'x-algolia-application-id': ALGOLIA_APP_ID,
            'x-algolia-api-key': ALGOLIA_API_KEY,
            'Referer': 'https://www.welcometothejungle.com/',
            'Origin': 'https://www.welcometothejungle.com',
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/121.0.0.0 Safari/537.36'
            ),
        })

    def search(self, keywords: list, location: str) -> list:
        """Recherche des offres sur WTTJ via Algolia.

        Filtres:
            - aroundLatLng: geolocalisation (Paris par defaut)
            - aroundRadius: rayon de recherche (30km)
            - facetFilters: type de contrat = apprenticeship
            - hitsPerPage: 50 resultats par page (max)
        """
        offers = []

        # Mapping localisation vers coordonnees
        coords = self._get_coords(location)

        for keyword in keywords:
            try:
                logger.info(f"WTTJ: recherche '{keyword}' a '{location}'")

                # Rechercher les offres (2 pages max = 100 offres)
                for page in range(2):
                    try:
                        payload = {
                            'query': keyword,
                            'aroundLatLng': f"{coords[0]},{coords[1]}",
                            'aroundRadius': 30000,  # 30km
                            'hitsPerPage': 50,
                            'page': page,
                            'facetFilters': [
                                ['contract_type:apprenticeship',
                                 'contract_type:internship']
                            ],
                        }

                        resp = self.session.post(ALGOLIA_URL, json=payload, timeout=15)

                        if resp.status_code == 403:
                            logger.warning("WTTJ: Algolia 403 — referer bloque")
                            break
                        if resp.status_code != 200:
                            logger.warning(f"WTTJ: Algolia HTTP {resp.status_code}")
                            break

                        data = resp.json()
                        hits = data.get('hits', [])

                        if not hits:
                            break

                        logger.info(f"WTTJ: page {page+1} — {len(hits)} resultats "
                                    f"(total: {data.get('nbHits', '?')})")

                        for hit in hits:
                            try:
                                offer = self._parse_hit(hit)
                                if offer:
                                    offers.append(offer)
                            except Exception as e:
                                logger.debug(f"WTTJ: erreur parsing hit: {e}")

                        # Delai entre les pages
                        if page < 1:
                            time.sleep(random.uniform(0.5, 1.5))

                    except requests.RequestException as e:
                        logger.error(f"WTTJ: erreur requete page {page}: {e}")
                        break

            except Exception as e:
                logger.error(f"WTTJ: erreur recherche '{keyword}': {e}")

        # Deduplication par URL
        seen = set()
        unique = []
        for o in offers:
            if o.url not in seen:
                seen.add(o.url)
                unique.append(o)

        logger.info(f"WTTJ: {len(unique)} offres uniques")
        return unique

    def _parse_hit(self, hit: dict) -> JobOffer | None:
        """Parse un hit Algolia en JobOffer"""
        name = hit.get('name', '').strip()
        if not name:
            return None

        # Organisation (entreprise)
        org = hit.get('organization', {})
        company = org.get('name', 'Non specifie')
        org_slug = org.get('slug', '')

        # Slug du job pour construire l'URL
        job_slug = hit.get('slug', '')
        if not job_slug or not org_slug:
            return None

        url = f"https://www.welcometothejungle.com/fr/companies/{org_slug}/jobs/{job_slug}"

        # Localisation
        offices = hit.get('office', {})
        if isinstance(offices, dict):
            city = offices.get('city', '')
            country = offices.get('country_code', '')
            loc_text = f"{city}, {country}".strip(', ') if city else ''
        elif isinstance(offices, list) and offices:
            city = offices[0].get('city', '') if isinstance(offices[0], dict) else ''
            loc_text = city
        else:
            loc_text = ''

        # Description
        description = hit.get('body', '') or hit.get('summary', '') or ''
        if len(description) > 500:
            description = description[:500] + '...'

        # Salaire
        salary = ''
        salary_min = hit.get('salary_min')
        salary_max = hit.get('salary_max')
        salary_period = hit.get('salary_period', '')
        salary_currency = hit.get('salary_currency', 'EUR')
        if salary_min and salary_max:
            salary = f"{salary_min}-{salary_max} {salary_currency}"
            if salary_period:
                salary += f" ({salary_period})"
        elif salary_min:
            salary = f"A partir de {salary_min} {salary_currency}"

        # Type de contrat
        contract = hit.get('contract_type', '')
        if isinstance(contract, dict):
            contract_type = contract.get('fr', contract.get('en', ''))
        else:
            contract_type = str(contract) if contract else ''
        
        # Traduire pour l'affichage
        contract_map = {
            'apprenticeship': 'Alternance',
            'internship': 'Stage',
            'full_time': 'CDI',
            'part_time': 'Temps partiel',
            'temporary': 'CDD',
            'freelance': 'Freelance',
            'vie': 'VIE',
        }
        contract_label = contract_map.get(contract_type, contract_type)

        # Ajouter le type de contrat dans la description si present
        if contract_label and contract_label.lower() not in description.lower():
            description = f"[{contract_label}] {description}"

        return JobOffer(
            title=name,
            company=company,
            location=loc_text,
            description=description,
            url=url,
            platform="wttj",
            salary=salary if salary else None,
        )

    def apply(self, offer: JobOffer, profile: dict) -> bool:
        """WTTJ necessite candidature manuelle (reCAPTCHA + auth)"""
        logger.info(f"WTTJ: candidature manuelle requise pour '{offer.title}' -> {offer.url}")
        return False

    def _get_coords(self, location: str) -> tuple:
        """Retourne les coordonnees GPS pour une localisation"""
        coords_map = {
            'paris': (PARIS_LAT, PARIS_LNG),
            'lyon': (45.764, 4.8357),
            'marseille': (43.2965, 5.3698),
            'toulouse': (43.6047, 1.4442),
            'bordeaux': (44.8378, -0.5792),
            'lille': (50.6292, 3.0573),
            'nantes': (47.2184, -1.5536),
            'strasbourg': (48.5734, 7.7521),
        }
        return coords_map.get(location.lower(), (PARIS_LAT, PARIS_LNG))
