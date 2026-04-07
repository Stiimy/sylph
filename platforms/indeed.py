"""Plateforme Indeed - Selenium stealth"""

from .base import Platform, JobOffer
from selenium.webdriver.common.by import By
import logging
from urllib.parse import quote_plus

logger = logging.getLogger("job-agent")


class IndeedPlatform(Platform):
    """Recherche d'offres sur Indeed via Selenium stealth"""

    def __init__(self, config: dict, browser=None):
        super().__init__(config, driver=None)
        self.browser = browser

    def search(self, keywords: list, location: str) -> list:
        """Recherche des offres sur Indeed France"""
        offers = []

        for keyword in keywords:
            try:
                kw = quote_plus(keyword)
                loc = quote_plus(location)
                url = f"https://fr.indeed.com/jobs?q={kw}&l={loc}&sort=date"

                logger.info(f"Indeed: recherche '{keyword}' a '{location}'")
                self.browser.get(url, wait=4)

                # Indeed change souvent ses selectors, on en essaie plusieurs
                cards = self.browser.find_all('.job_seen_beacon')
                if not cards:
                    cards = self.browser.find_all('div[data-jk]')
                if not cards:
                    cards = self.browser.find_all('.resultContent')
                if not cards:
                    cards = self.browser.find_all('.jobsearch-ResultsList > div')

                logger.info(f"Indeed: {len(cards)} cartes pour '{keyword}'")

                for card in cards[:15]:
                    try:
                        # Titre
                        title_elems = card.find_elements(By.CSS_SELECTOR,
                            'h2.jobTitle a span, h2.jobTitle span, .jobTitle a, a[data-jk]')
                        if not title_elems:
                            continue
                        title = title_elems[0].text.strip()
                        if not title:
                            continue

                        # Entreprise
                        company_elems = card.find_elements(By.CSS_SELECTOR,
                            '[data-testid="company-name"], .companyName, .company')
                        company = company_elems[0].text.strip() if company_elems else "Non specifie"

                        # Lieu
                        loc_elems = card.find_elements(By.CSS_SELECTOR,
                            '[data-testid="text-location"], .companyLocation, .location')
                        loc_text = loc_elems[0].text.strip() if loc_elems else ""

                        # URL
                        link_elems = card.find_elements(By.CSS_SELECTOR,
                            'h2.jobTitle a, a[data-jk], a[href*="/rc/clk"], a[href*="viewjob"]')
                        offer_url = ""
                        if link_elems:
                            href = link_elems[0].get_attribute('href') or ""
                            if href:
                                offer_url = href

                        # Salaire
                        salary_elems = card.find_elements(By.CSS_SELECTOR,
                            '.salary-snippet-container, .salaryText, [data-testid="attribute_snippet_testid"]')
                        salary = salary_elems[0].text.strip() if salary_elems else None

                        # Description courte
                        desc_elems = card.find_elements(By.CSS_SELECTOR, '.job-snippet')
                        description = desc_elems[0].text.strip()[:200] if desc_elems else ""

                        if title and offer_url:
                            offers.append(JobOffer(
                                title=title,
                                company=company,
                                location=loc_text,
                                description=description,
                                url=offer_url,
                                platform="indeed",
                                salary=salary
                            ))

                    except Exception as e:
                        logger.debug(f"Indeed: erreur extraction carte: {e}")

            except Exception as e:
                logger.error(f"Indeed: erreur recherche '{keyword}': {e}")

        # Deduplication par URL
        seen = set()
        unique = []
        for o in offers:
            if o.url not in seen:
                seen.add(o.url)
                unique.append(o)

        logger.info(f"Indeed: {len(unique)} offres uniques")
        return unique

    def apply(self, offer: JobOffer, profile: dict) -> bool:
        """Indeed redirige vers le site employeur"""
        logger.info(f"Indeed: postulation manuelle pour '{offer.title}' -> {offer.url}")
        return False
