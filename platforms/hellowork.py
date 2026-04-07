"""Plateforme HelloWork - Selenium stealth (SPA avec Turbo)"""

from .base import Platform, JobOffer
from selenium.webdriver.common.by import By
import logging
import time
from urllib.parse import quote_plus

logger = logging.getLogger("job-agent")


class HelloWorkPlatform(Platform):
    """Recherche d'offres sur HelloWork via Selenium stealth"""

    def __init__(self, config: dict, browser=None):
        super().__init__(config, driver=None)
        self.browser = browser

    def search(self, keywords: list, location: str) -> list:
        """Recherche sur HelloWork"""
        offers = []

        for keyword in keywords:
            try:
                kw = quote_plus(keyword)
                loc = quote_plus(location)
                url = f"https://www.hellowork.com/fr-fr/emploi/recherche.html?k={kw}&l={loc}"

                logger.info(f"HelloWork: recherche '{keyword}' a '{location}'")
                self.browser.get(url, wait=4)

                # Accepter les cookies (important pour HelloWork)
                self.browser.accept_cookies()
                time.sleep(1)

                # Les offres sont dans le turbo-frame #turboSerp
                serp = self.browser.find_all('#turboSerp')
                if not serp:
                    logger.warning(f"HelloWork: turboSerp pas trouve pour '{keyword}'")
                    continue

                # Les liens d'offres sont dans le serp avec le format /fr-fr/emplois/XXXXX.html
                links = serp[0].find_elements(By.CSS_SELECTOR, 'a')

                logger.info(f"HelloWork: {len(links)} liens dans serp pour '{keyword}'")

                for link in links:
                    try:
                        href = link.get_attribute('href') or ""
                        if '/fr-fr/emplois/' not in href:
                            continue

                        text = link.text.strip()
                        if not text or len(text) < 5:
                            continue

                        # Le texte contient souvent "Titre\nEntreprise"
                        parts = text.split('\n')
                        title = parts[0].strip() if parts else text
                        company = parts[1].strip() if len(parts) > 1 else "Non specifie"

                        # Lieu - chercher dans le parent
                        loc_text = ""
                        try:
                            parent = link.find_element(By.XPATH, '..')
                            loc_elems = parent.find_elements(By.CSS_SELECTOR,
                                '[class*="location"], [class*="lieu"]')
                            if loc_elems:
                                loc_text = loc_elems[0].text.strip()
                        except Exception:
                            pass

                        if title and href:
                            offers.append(JobOffer(
                                title=title,
                                company=company,
                                location=loc_text,
                                description="",
                                url=href,
                                platform="hellowork"
                            ))

                    except Exception as e:
                        logger.debug(f"HelloWork: erreur extraction lien: {e}")

            except Exception as e:
                logger.error(f"HelloWork: erreur recherche '{keyword}': {e}")

        # Deduplication
        seen = set()
        unique = []
        for o in offers:
            if o.url not in seen:
                seen.add(o.url)
                unique.append(o)

        logger.info(f"HelloWork: {len(unique)} offres uniques")
        return unique

    def apply(self, offer: JobOffer, profile: dict) -> bool:
        """HelloWork necessite validation manuelle"""
        logger.info(f"HelloWork: postulation manuelle pour '{offer.title}'")
        return False
