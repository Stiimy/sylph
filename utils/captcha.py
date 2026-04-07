"""
Solver de CAPTCHA via 2captcha API.
Supporte reCAPTCHA v2 et hCaptcha (utilise par Indeed).

Prix: ~2-3 EUR pour 1000 resolutions.
Temps moyen: 15-45 secondes par CAPTCHA.
"""

import time
import logging
import requests
from typing import Optional

logger = logging.getLogger("job-agent")

# Timeout max pour attendre la resolution
MAX_WAIT = 120  # secondes
POLL_INTERVAL = 5  # secondes entre chaque check


class CaptchaSolver:
    """Resout les CAPTCHAs via l'API 2captcha"""

    API_BASE = "https://2captcha.com"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()

    def solve_recaptcha_v2(self, site_key: str, page_url: str) -> Optional[str]:
        """
        Resout un reCAPTCHA v2.
        Retourne le token g-recaptcha-response, ou None si echec.
        """
        logger.info(f"2captcha: resolution reCAPTCHA v2 pour {page_url}")

        # Etape 1: Envoyer la demande
        try:
            resp = self.session.post(f"{self.API_BASE}/in.php", data={
                'key': self.api_key,
                'method': 'userrecaptcha',
                'googlekey': site_key,
                'pageurl': page_url,
                'json': 1
            })
            data = resp.json()
            if data.get('status') != 1:
                logger.error(f"2captcha erreur envoi: {data}")
                return None
            task_id = data['request']
        except Exception as e:
            logger.error(f"2captcha erreur envoi: {e}")
            return None

        # Etape 2: Attendre la resolution
        return self._poll_result(task_id)

    def solve_hcaptcha(self, site_key: str, page_url: str) -> Optional[str]:
        """
        Resout un hCaptcha (souvent utilise par Indeed).
        Retourne le token h-captcha-response, ou None si echec.
        """
        logger.info(f"2captcha: resolution hCaptcha pour {page_url}")

        try:
            resp = self.session.post(f"{self.API_BASE}/in.php", data={
                'key': self.api_key,
                'method': 'hcaptcha',
                'sitekey': site_key,
                'pageurl': page_url,
                'json': 1
            })
            data = resp.json()
            if data.get('status') != 1:
                logger.error(f"2captcha erreur envoi hcaptcha: {data}")
                return None
            task_id = data['request']
        except Exception as e:
            logger.error(f"2captcha erreur envoi hcaptcha: {e}")
            return None

        return self._poll_result(task_id)

    def _poll_result(self, task_id: str) -> Optional[str]:
        """Attend et recupere le resultat de la resolution"""
        elapsed = 0
        # Attendre un minimum avant le premier check
        time.sleep(15)
        elapsed = 15

        while elapsed < MAX_WAIT:
            try:
                resp = self.session.get(f"{self.API_BASE}/res.php", params={
                    'key': self.api_key,
                    'action': 'get',
                    'id': task_id,
                    'json': 1
                })
                data = resp.json()

                if data.get('status') == 1:
                    token = data['request']
                    logger.info(f"2captcha: CAPTCHA resolu en {elapsed}s")
                    return token
                elif data.get('request') == 'CAPCHA_NOT_READY':
                    pass  # Pas encore pret, on continue
                else:
                    logger.error(f"2captcha erreur resolution: {data}")
                    return None

            except Exception as e:
                logger.error(f"2captcha erreur poll: {e}")
                return None

            time.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL

        logger.error(f"2captcha: timeout apres {MAX_WAIT}s")
        return None

    def get_balance(self) -> float:
        """Verifie le solde du compte 2captcha"""
        try:
            resp = self.session.get(f"{self.API_BASE}/res.php", params={
                'key': self.api_key,
                'action': 'getbalance',
                'json': 1
            })
            data = resp.json()
            if data.get('status') == 1:
                return float(data['request'])
        except Exception:
            pass
        return 0.0


def inject_captcha_token(driver, token: str, captcha_type: str = "recaptcha"):
    """
    Injecte le token CAPTCHA resolu dans la page via JavaScript.
    
    Pour reCAPTCHA v2: met le token dans #g-recaptcha-response et appelle le callback
    Pour hCaptcha: met le token dans [name="h-captcha-response"] et appelle le callback
    """
    if captcha_type == "recaptcha":
        driver.execute_script(f"""
            // Rendre le textarea visible et injecter le token
            var textarea = document.getElementById('g-recaptcha-response');
            if (textarea) {{
                textarea.style.display = 'block';
                textarea.value = '{token}';
            }}
            // Appeler le callback si il existe
            if (typeof ___grecaptcha_cfg !== 'undefined') {{
                var clients = ___grecaptcha_cfg.clients;
                if (clients) {{
                    for (var key in clients) {{
                        var client = clients[key];
                        // Chercher le callback dans l'objet client
                        try {{
                            var callback = Object.values(client).find(v => 
                                typeof v === 'object' && v !== null && typeof v.callback === 'function'
                            );
                            if (callback) callback.callback('{token}');
                        }} catch(e) {{}}
                    }}
                }}
            }}
        """)
    elif captcha_type == "hcaptcha":
        driver.execute_script(f"""
            // Injecter dans le textarea hCaptcha
            var textareas = document.querySelectorAll('[name="h-captcha-response"], textarea[name*="captcha"]');
            textareas.forEach(function(t) {{
                t.style.display = 'block';
                t.value = '{token}';
            }});
            // Appeler le callback hCaptcha
            try {{
                var iframes = document.querySelectorAll('iframe[src*="hcaptcha"]');
                if (window.hcaptcha) {{
                    // Utiliser l'API hCaptcha directement si dispo
                    // Le token est deja injecte
                }}
            }} catch(e) {{}}
        """)
    
    logger.info(f"Token {captcha_type} injecte dans la page")


def detect_captcha_type(driver) -> tuple[str, str]:
    """
    Detecte le type de CAPTCHA present sur la page et retourne (type, site_key).
    Types: "recaptcha", "hcaptcha", "none"
    """
    try:
        page = driver.page_source

        # hCaptcha (Indeed utilise souvent hCaptcha)
        import re
        hcaptcha_match = re.search(r'data-sitekey=["\']([a-f0-9-]+)["\']', page)
        if 'hcaptcha' in page.lower() or 'h-captcha' in page.lower():
            if hcaptcha_match:
                return ("hcaptcha", hcaptcha_match.group(1))
            # Chercher dans les iframes
            iframes = driver.find_elements(
                __import__('selenium.webdriver.common.by', fromlist=['By']).By.CSS_SELECTOR,
                'iframe[src*="hcaptcha"]'
            )
            if iframes:
                src = iframes[0].get_attribute('src') or ""
                key_match = re.search(r'sitekey=([a-f0-9-]+)', src)
                if key_match:
                    return ("hcaptcha", key_match.group(1))
            return ("hcaptcha", "")

        # reCAPTCHA v2
        recaptcha_match = re.search(r'data-sitekey=["\']([A-Za-z0-9_-]+)["\']', page)
        if 'recaptcha' in page.lower() or 'g-recaptcha' in page.lower():
            if recaptcha_match:
                return ("recaptcha", recaptcha_match.group(1))
            return ("recaptcha", "")

    except Exception as e:
        logger.debug(f"Erreur detection CAPTCHA: {e}")

    return ("none", "")


def create_solver(config: dict) -> Optional[CaptchaSolver]:
    """Cree un CaptchaSolver si la cle API est configuree"""
    captcha_config = config.get('captcha', {})
    api_key = captcha_config.get('2captcha_api_key', '')
    
    if not api_key:
        return None
    
    solver = CaptchaSolver(api_key)
    
    # Verifier le solde
    balance = solver.get_balance()
    if balance > 0:
        logger.info(f"2captcha connecte - solde: {balance:.2f} USD")
    else:
        logger.warning("2captcha: solde a 0 ou cle invalide")
    
    return solver
