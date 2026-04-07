"""Scraper HTTP leger avec requests + BeautifulSoup"""

import requests
from bs4 import BeautifulSoup
import time
import random
import logging

logger = logging.getLogger("job-agent")


class Requester:
    """Scraper HTTP avec headers realistes et delais aleatoires"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Accept-Language': 'fr-FR,fr;q=0.9,en;q=0.8',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
        })

    def get(self, url: str, retries: int = 2) -> BeautifulSoup:
        """Recupere une page avec retry et delai aleatoire"""
        for attempt in range(retries + 1):
            try:
                # Delai aleatoire pour pas ressembler a un bot
                if attempt > 0:
                    wait = random.uniform(2, 5)
                    logger.debug(f"Retry {attempt}, attente {wait:.1f}s")
                    time.sleep(wait)
                else:
                    time.sleep(random.uniform(0.5, 1.5))

                resp = self.session.get(url, timeout=20)

                if resp.status_code == 403:
                    logger.warning(f"403 Forbidden pour {url}")
                    continue
                elif resp.status_code == 429:
                    logger.warning(f"429 Rate limited, attente...")
                    time.sleep(random.uniform(10, 20))
                    continue

                resp.raise_for_status()
                return BeautifulSoup(resp.text, 'html.parser')

            except requests.exceptions.Timeout:
                logger.warning(f"Timeout pour {url}")
            except requests.exceptions.RequestException as e:
                logger.error(f"Erreur HTTP {url}: {e}")

        return None

    def get_json(self, url: str) -> dict:
        """Recupere du JSON"""
        try:
            time.sleep(random.uniform(0.5, 1.5))
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Erreur JSON {url}: {e}")
            return None


def create_requester() -> Requester:
    """Factory function"""
    return Requester()
