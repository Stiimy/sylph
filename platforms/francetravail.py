"""Plateforme France Travail (ex Pole Emploi) - Scraping web"""

from .base import Platform, JobOffer
import logging
from urllib.parse import quote_plus

logger = logging.getLogger("job-agent")

# Code type contrat alternance/apprentissage
CONTRACT_TYPE_ALTERNANCE = "E2"


class FranceTravailPlatform(Platform):
    """Recherche d'offres sur France Travail via scraping web"""

    def __init__(self, config: dict, requester=None):
        super().__init__(config, driver=None)
        self.requester = requester

    def search(self, keywords: list, location: str) -> list:
        """Recherche des offres sur France Travail"""
        offers = []

        # Mapping location vers code France Travail
        location_code = self._get_location_code(location)

        for keyword in keywords:
            try:
                kw = quote_plus(keyword)
                url = f"https://candidat.francetravail.fr/offres/recherche?motsCles={kw}&lieu={location_code}&typeContrat={CONTRACT_TYPE_ALTERNANCE}"

                logger.info(f"France Travail: recherche '{keyword}' a '{location}'")
                soup = self.requester.get(url)

                if not soup:
                    logger.warning(f"France Travail: pas de reponse pour '{keyword}'")
                    continue

                # Extraction des resultats
                results = soup.select('.result-list .result, .media')
                if not results:
                    results = soup.select('li.result')

                logger.info(f"France Travail: {len(results)} resultats pour '{keyword}'")

                for result in results[:20]:
                    try:
                        # Titre
                        title_elem = (
                            result.select_one('h2') or
                            result.select_one('h3') or
                            result.select_one('.media-heading') or
                            result.select_one('[data-id-job]')
                        )
                        if not title_elem:
                            continue
                        title = title_elem.get_text(strip=True)
                        if not title:
                            continue

                        # URL de l'offre
                        link_elem = (
                            title_elem.select_one('a') or
                            result.select_one('a[href*="/offres/"]') or
                            result.select_one('a')
                        )
                        offer_url = ""
                        if link_elem and link_elem.get('href'):
                            href = link_elem['href']
                            if href.startswith('/'):
                                offer_url = "https://candidat.francetravail.fr" + href
                            elif href.startswith('http'):
                                offer_url = href

                        # Entreprise
                        company_elem = (
                            result.select_one('.subtext') or
                            result.select_one('.company') or
                            result.select_one('p.description')
                        )
                        company = ""
                        if company_elem:
                            company = company_elem.get_text(strip=True)
                            # Souvent le format est "Entreprise - Lieu"
                            if ' - ' in company:
                                parts = company.split(' - ')
                                company = parts[0].strip()

                        # Lieu
                        location_elem = result.select_one('.location, .subtext')
                        loc_text = ""
                        if location_elem:
                            loc_full = location_elem.get_text(strip=True)
                            # Extraire la localisation (souvent apres un tiret)
                            if ' - ' in loc_full:
                                parts = loc_full.split(' - ')
                                loc_text = parts[-1].strip() if len(parts) > 1 else loc_full

                        # Description courte
                        desc_elem = result.select_one('.description, .media-body p')
                        description = desc_elem.get_text(strip=True)[:200] if desc_elem else ""

                        if title and offer_url:
                            offers.append(JobOffer(
                                title=title,
                                company=company if company else "Non specifie",
                                location=loc_text,
                                description=description,
                                url=offer_url,
                                platform="francetravail"
                            ))

                    except Exception as e:
                        logger.debug(f"France Travail: erreur extraction: {e}")

            except Exception as e:
                logger.error(f"France Travail: erreur recherche '{keyword}': {e}")

        # Deduplication par URL
        seen_urls = set()
        unique = []
        for offer in offers:
            if offer.url and offer.url not in seen_urls:
                seen_urls.add(offer.url)
                unique.append(offer)

        logger.info(f"France Travail: {len(unique)} offres uniques")
        return unique

    def apply(self, offer: JobOffer, profile: dict) -> bool:
        """France Travail necessite une candidature manuelle"""
        logger.info(f"France Travail: postulation manuelle pour '{offer.title}' -> {offer.url}")
        return False

    def _get_location_code(self, location: str) -> str:
        """Convertit un nom de lieu en code France Travail.
        
        Codes:
            xxD = departement, xxR = region
            11R = Ile-de-France (toute la region)
            75D = Paris uniquement
        """
        location_map = {
            "paris": "11R",           # IDF entiere (pas juste 75)
            "île-de-france": "11R",
            "ile-de-france": "11R",
            "lyon": "69D",
            "marseille": "13D",
            "toulouse": "31D",
            "bordeaux": "33D",
            "lille": "59D",
            "nantes": "44D",
            "strasbourg": "67D",
            "france": "",
        }
        return location_map.get(location.lower(), "")
