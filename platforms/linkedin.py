"""Plateforme LinkedIn - Recherche publique HTTP (pas de Selenium requis).

LinkedIn expose une recherche d'offres publique sans authentification.
On scrape le HTML avec requests + BeautifulSoup.

IMPORTANT: LinkedIn apply est DESACTIVE (sessions revoquees par anti-bot).
Les offres LinkedIn sont envoyees via Telegram pour postulation manuelle.
"""

from .base import Platform, JobOffer
from bs4 import BeautifulSoup
import requests
import logging
import time
import random
from urllib.parse import quote_plus

logger = logging.getLogger("job-agent")


class LinkedInPlatform(Platform):
    """Recherche d'offres sur LinkedIn via la recherche publique HTTP.
    
    Pas besoin de Selenium ni de cookies — la recherche d'offres LinkedIn
    est accessible publiquement.
    """

    BASE_URL = "https://www.linkedin.com/jobs/search/"

    def __init__(self, config: dict, browser=None):
        super().__init__(config, driver=None)
        # Browser pas utilise pour LinkedIn search (HTTP simple)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/121.0.0.0 Safari/537.36'
            ),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9',
            'Accept-Language': 'fr-FR,fr;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })

    def search(self, keywords: list, location: str) -> list:
        """Recherche des offres sur LinkedIn (page publique).
        
        Parametres de recherche:
            f_TPR=r604800  — offres de la derniere semaine (7 jours)
            f_E=1          — niveau entry-level (alternance)
            f_JT=I         — type: stage/alternance (internship)
            sortBy=DD      — tri par date (plus recentes en premier)
        """
        offers = []

        for keyword in keywords:
            try:
                kw = quote_plus(keyword)
                loc = quote_plus(location)

                # Premiere page (25 offres)
                url = (
                    f"{self.BASE_URL}?keywords={kw}&location={loc}"
                    f"&f_TPR=r604800"  # Derniere semaine
                    f"&sortBy=DD"      # Plus recentes d'abord
                    f"&position=1&pageNum=0"
                )

                logger.info(f"LinkedIn: recherche '{keyword}' a '{location}'")

                # Pause aleatoire avant la requete
                time.sleep(random.uniform(1.0, 3.0))

                resp = self.session.get(url, timeout=15)

                if resp.status_code != 200:
                    logger.warning(f"LinkedIn: status {resp.status_code} pour '{keyword}'")
                    continue

                page_offers = self._parse_search_results(resp.text)
                offers.extend(page_offers)
                logger.info(f"LinkedIn: {len(page_offers)} offres page 1 pour '{keyword}'")

                # Page 2 si la premiere etait pleine (25 offres)
                if len(page_offers) >= 25:
                    time.sleep(random.uniform(2.0, 4.0))
                    url2 = (
                        f"{self.BASE_URL}?keywords={kw}&location={loc}"
                        f"&f_TPR=r604800&sortBy=DD"
                        f"&start=25&position=1&pageNum=1"
                    )
                    resp2 = self.session.get(url2, timeout=15)
                    if resp2.status_code == 200:
                        page2_offers = self._parse_search_results(resp2.text)
                        offers.extend(page2_offers)
                        logger.info(f"LinkedIn: {len(page2_offers)} offres page 2")

            except requests.exceptions.Timeout:
                logger.warning(f"LinkedIn: timeout pour '{keyword}'")
            except Exception as e:
                logger.error(f"LinkedIn: erreur recherche '{keyword}': {e}")

        # Deduplication par URL
        seen = set()
        unique = []
        for o in offers:
            # Normaliser l'URL (retirer les query params de tracking)
            clean_url = o.url.split('?')[0] if o.url else ""
            if clean_url and clean_url not in seen:
                seen.add(clean_url)
                o.url = clean_url  # URL propre
                unique.append(o)

        logger.info(f"LinkedIn: {len(unique)} offres uniques total")
        return unique

    def _parse_search_results(self, html: str) -> list:
        """Parse le HTML de la page de resultats LinkedIn.
        
        Les offres sont dans des elements <li> avec la classe base-card.
        Chaque carte contient:
            - .base-search-card__title (h3) — titre
            - .base-search-card__subtitle (h4) — entreprise
            - .job-search-card__location — lieu
            - a[href*="/jobs/view/"] — lien vers l'offre
            - time.job-search-card__listdate — date de publication
        """
        offers = []
        soup = BeautifulSoup(html, 'html.parser')

        cards = soup.select('.base-card, .base-search-card, .job-search-card')
        if not cards:
            # Fallback: chercher par data-entity-urn
            cards = soup.select('[data-entity-urn*="jobPosting"]')

        for card in cards:
            try:
                # Titre
                title_el = card.select_one(
                    '.base-search-card__title, '
                    'h3.base-search-card__title, '
                    'h3'
                )
                title = title_el.text.strip() if title_el else ""
                if not title:
                    continue

                # Entreprise
                company_el = card.select_one(
                    '.base-search-card__subtitle, '
                    'h4.base-search-card__subtitle, '
                    'h4, '
                    'a[data-tracking-control-name*="company"]'
                )
                company = company_el.text.strip() if company_el else "Non specifie"

                # Lieu
                loc_el = card.select_one(
                    '.job-search-card__location, '
                    'span.job-search-card__location'
                )
                location = loc_el.text.strip() if loc_el else ""

                # URL de l'offre
                link_el = card.select_one(
                    'a[href*="/jobs/view/"], '
                    'a.base-card__full-link, '
                    'a.base-search-card__full-link'
                )
                url = ""
                if link_el:
                    url = link_el.get('href', '')
                    # Nettoyer l'URL (retirer tracking params)
                    if '?' in url:
                        url = url.split('?')[0]

                if not url:
                    continue

                # Date de publication
                date_el = card.select_one(
                    'time.job-search-card__listdate, '
                    'time[datetime]'
                )
                posted_date = None
                if date_el:
                    datetime_str = date_el.get('datetime', '')
                    if datetime_str:
                        try:
                            from datetime import datetime
                            posted_date = datetime.fromisoformat(datetime_str)
                        except Exception:
                            pass

                # Salaire (rarement affiche sur LinkedIn)
                salary_el = card.select_one(
                    '.job-search-card__salary-info, '
                    '.salary-main-rail__salary-info'
                )
                salary = salary_el.text.strip() if salary_el else None

                offers.append(JobOffer(
                    title=title,
                    company=company,
                    location=location,
                    description="",  # Description recuperee plus tard si besoin
                    url=url,
                    platform="linkedin",
                    salary=salary,
                    posted_date=posted_date,
                ))

            except Exception as e:
                logger.debug(f"LinkedIn: erreur extraction carte: {e}")

        return offers

    def apply(self, offer: JobOffer, profile: dict) -> bool:
        """LinkedIn apply desactive — postulation manuelle via Telegram."""
        logger.info(f"LinkedIn: postulation manuelle pour '{offer.title}' -> {offer.url}")
        return False
