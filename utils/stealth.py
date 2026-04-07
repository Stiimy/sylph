"""Navigateur stealth partage entre les plateformes"""

import json
import os
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import random
import logging

logger = logging.getLogger("job-agent")

COOKIES_JSON = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "cookies.json")


class StealthBrowser:
    """Navigateur Selenium stealth pour eviter la detection anti-bot"""

    # Profil par defaut pour garder les sessions (cookies, login)
    DEFAULT_PROFILE = os.path.join(os.path.expanduser("~"), ".sylph-profile")

    def __init__(self, headless: bool = True, profile_dir: str = None):
        self.headless = headless
        self.profile_dir = profile_dir or self.DEFAULT_PROFILE
        self.driver = None

    def start(self):
        """Demarre le navigateur avec config anti-detection + profil persistant"""
        options = Options()

        if self.headless:
            options.add_argument('--headless=new')

        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--start-maximized')

        # Profil persistant — garde les cookies et sessions entre les lancements
        options.add_argument(f'--user-data-dir={self.profile_dir}')

        # Anti-detection
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument('--disable-features=NetworkService,NetworkServiceInProcess')
        options.add_argument('--disable-extensions')
        options.add_argument('--disable-sync')
        options.add_argument('--no-first-run')

        # User-agent Windows classique
        options.add_argument(
            '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
        )
        options.add_argument('--accept-lang=fr-FR,fr')

        options.binary_location = '/usr/bin/chromium'
        options.add_experimental_option('excludeSwitches', ['enable-automation'])
        options.add_experimental_option('useAutomationExtension', False)

        try:
            service = Service('/usr/bin/chromedriver')
            self.driver = webdriver.Chrome(service=service, options=options)

            # Supprimer le flag webdriver
            self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': '''
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    window.navigator.chrome = {runtime: {}};
                '''
            })

            logger.info(f"Navigateur stealth demarre (profil: {self.profile_dir})")
            return self.driver

        except Exception as e:
            logger.error(f"Erreur demarrage navigateur: {e}")
            raise

    def load_cookies(self, cookies_file: str = COOKIES_JSON):
        """Charge les cookies depuis le fichier JSON et les injecte dans le navigateur.
        
        Les cookies sont groupes par domaine. Pour chaque domaine, on navigue
        vers le site puis on injecte les cookies correspondants.
        """
        import os
        if not os.path.exists(cookies_file):
            logger.debug(f"Pas de fichier cookies: {cookies_file}")
            return False

        try:
            with open(cookies_file) as f:
                cookies = json.load(f)
        except Exception as e:
            logger.error(f"Erreur lecture cookies: {e}")
            return False

        if not cookies:
            return False

        # Grouper par domaine racine
        domain_cookies = {}
        for cookie in cookies:
            domain = cookie['domain'].lstrip('.')
            # Extraire le domaine racine (ex: hellowork.com de www.hellowork.com)
            parts = domain.split('.')
            root = '.'.join(parts[-2:]) if len(parts) >= 2 else domain
            if root not in domain_cookies:
                domain_cookies[root] = []
            domain_cookies[root].append(cookie)

        total_injected = 0
        for root_domain, cks in domain_cookies.items():
            try:
                self.driver.get(f"https://{root_domain}")
                time.sleep(2)

                for cookie in cks:
                    try:
                        sel_cookie = {
                            'name': cookie['name'],
                            'value': cookie['value'],
                            'domain': cookie['domain'],
                            'path': cookie.get('path', '/'),
                            'secure': cookie.get('secure', False),
                        }
                        if cookie.get('expiry'):
                            sel_cookie['expiry'] = int(cookie['expiry'])
                        self.driver.add_cookie(sel_cookie)
                        total_injected += 1
                    except Exception:
                        pass
            except Exception as e:
                logger.debug(f"Cookies {root_domain}: erreur navigation — {e}")

        if total_injected > 0:
            logger.info(f"Cookies injectes: {total_injected}/{len(cookies)}")
        return total_injected > 0

    def get(self, url: str, wait: float = 3.0):
        """Ouvre une page avec delai aleatoire"""
        time.sleep(random.uniform(0.5, 1.5))
        self.driver.get(url)
        time.sleep(wait + random.uniform(0.5, 2.0))
        return self

    def accept_cookies(self):
        """Accepte les cookies si un bouton est present"""
        try:
            buttons = self.driver.find_elements(By.CSS_SELECTOR, 'button')
            for btn in buttons:
                text = btn.text.lower().strip()
                if any(w in text for w in ['accepter', 'tout accepter', 'accept all', 'accept']):
                    btn.click()
                    time.sleep(1.5)
                    logger.debug("Cookies acceptes")
                    return True
        except Exception:
            pass
        return False

    def find(self, selector: str, timeout: int = 10):
        """Trouve un element CSS avec attente"""
        try:
            return WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, selector))
            )
        except Exception:
            return None

    def find_all(self, selector: str):
        """Trouve tous les elements CSS"""
        return self.driver.find_elements(By.CSS_SELECTOR, selector)

    def scroll_page(self, times: int = 3, delay: float = 1.0):
        """Scroll progressif pour charger le contenu dynamique"""
        for _ in range(times):
            self.driver.execute_script('window.scrollBy(0, 800)')
            time.sleep(delay + random.uniform(0.3, 1.0))

    def screenshot(self, name: str):
        """Screenshot pour debug"""
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs', f'{name}.png')
        self.driver.save_screenshot(path)
        logger.debug(f"Screenshot: {path}")

    def quit(self):
        """Ferme le navigateur"""
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
            logger.info("Navigateur ferme")


def create_stealth_browser(headless: bool = True, profile_dir: str = None) -> StealthBrowser:
    """Factory function"""
    return StealthBrowser(headless=headless, profile_dir=profile_dir)
