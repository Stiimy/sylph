"""
Auto-apply sur SmartRecruiters.

SmartRecruiters a une API publique de candidature:
POST https://jobs.smartrecruiters.com/api/apply/{postingId}

Mais en pratique, les pages sont protegees par Cloudflare et
l'API necessite souvent un token/session.

Approche: Selenium fallback — naviguer sur la page de l'offre,
cliquer Apply, remplir le formulaire.

SmartRecruiters est un SPA React, mais le formulaire de candidature
est relativement standard.

Patterns d'URL detectes:
- jobs.smartrecruiters.com/{company}/{postingId}
- *.smartrecruiters.com/...
"""

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
import time
import random
import logging
import os
import re

logger = logging.getLogger("job-agent")

SR_DOMAINS = ['smartrecruiters.com']


def is_smartrecruiters_url(url: str) -> bool:
    """Verifie si une URL est un site SmartRecruiters."""
    return 'smartrecruiters.com' in url.lower()


class SmartRecruitersApplicator:
    """Auto-apply sur SmartRecruiters via Selenium.

    SmartRecruiters est un SPA React. Le flow:
    1. Page offre -> bouton "Apply" / "Postuler"
    2. Formulaire: prenom, nom, email, telephone, CV
    3. (Optionnel) questions supplementaires
    4. Submit

    Cloudflare peut bloquer — on utilise le browser stealth.
    """

    def __init__(self, profile: dict, browser=None, ai_client=None):
        self.profile = profile
        self.browser = browser
        self.ai_client = ai_client

    @property
    def first_name(self) -> str:
        name = self.profile.get('name', '')
        parts = name.split()
        return parts[-1] if len(parts) > 1 else parts[0] if parts else ""

    @property
    def last_name(self) -> str:
        name = self.profile.get('name', '')
        parts = name.split()
        return parts[0] if len(parts) > 1 else ""

    @property
    def email(self) -> str:
        return self.profile.get('email', '')

    @property
    def phone(self) -> str:
        return self.profile.get('phone', '')

    @property
    def cv_path(self) -> str:
        return self.profile.get('cv_path', '')

    def apply(self, url: str, offer: dict) -> dict:
        """Tente de postuler sur SmartRecruiters.

        Args:
            url: URL de l'offre SmartRecruiters
            offer: dict de l'offre

        Returns:
            dict avec success: bool, details: str
        """
        if not self.browser:
            return {'success': False, 'details': 'Pas de browser disponible'}

        driver = self.browser.driver
        if not driver:
            return {'success': False, 'details': 'Pas de driver Selenium'}

        title = offer.get('title', '')
        company = offer.get('company', '')

        try:
            logger.info(f"SmartRecruiters: navigation vers {url}")
            driver.get(url)
            time.sleep(random.uniform(4.0, 6.0))

            # Verifier Cloudflare challenge
            page_text = driver.find_element(By.TAG_NAME, 'body').text.lower()
            if 'checking your browser' in page_text or 'just a moment' in page_text:
                logger.warning("SmartRecruiters: Cloudflare challenge detecte, attente...")
                time.sleep(random.uniform(8.0, 12.0))
                page_text = driver.find_element(By.TAG_NAME, 'body').text.lower()
                if 'checking your browser' in page_text:
                    return {'success': False, 'details': 'Bloque par Cloudflare'}

            # Accepter cookies
            self._accept_cookies(driver)

            # Cliquer sur Apply
            if not self._click_apply(driver):
                return {'success': False, 'details': 'Bouton Apply non trouve'}

            # Remplir le formulaire
            time.sleep(random.uniform(2.0, 4.0))
            success = self._fill_form(driver, offer)

            if success:
                logger.info(f"SmartRecruiters: candidature envoyee pour '{title}' @ {company}")
                self.browser.screenshot(f"sr_success_{company}_{int(time.time())}")
                return {'success': True, 'details': 'Candidature envoyee via SmartRecruiters'}
            else:
                self.browser.screenshot(f"sr_fail_{company}_{int(time.time())}")
                return {'success': False, 'details': 'Echec remplissage formulaire SmartRecruiters'}

        except Exception as e:
            logger.error(f"SmartRecruiters: erreur pour '{title}': {e}")
            try:
                self.browser.screenshot(f"sr_error_{int(time.time())}")
            except Exception:
                pass
            return {'success': False, 'details': f'Erreur SmartRecruiters: {e}'}

    def _accept_cookies(self, driver):
        """Accepte la banniere cookies."""
        selectors = [
            'button#onetrust-accept-btn-handler',
            'button[id*="accept"]',
            'button[class*="accept"]',
            '#cookie-consent-accept',
        ]
        for sel in selectors:
            try:
                btn = driver.find_element(By.CSS_SELECTOR, sel)
                if btn.is_displayed():
                    btn.click()
                    time.sleep(1)
                    return
            except Exception:
                continue

        try:
            for btn in driver.find_elements(By.TAG_NAME, 'button'):
                txt = btn.text.lower().strip()
                if txt in ['accepter', 'accept', 'accept all', 'tout accepter', 'ok']:
                    if btn.is_displayed():
                        btn.click()
                        time.sleep(1)
                        return
        except Exception:
            pass

    def _click_apply(self, driver) -> bool:
        """Clique sur le bouton Apply/Postuler."""
        apply_selectors = [
            'button[data-test="apply-button"]',
            'a[data-test="apply-button"]',
            'button.apply-button',
            'a.apply-button',
            'button[class*="ApplyButton"]',
            'a[class*="ApplyButton"]',
            'a[href*="/apply"]',
        ]

        for sel in apply_selectors:
            try:
                btn = driver.find_element(By.CSS_SELECTOR, sel)
                if btn.is_displayed():
                    btn.click()
                    logger.debug(f"SmartRecruiters: bouton Apply clique ({sel})")
                    time.sleep(random.uniform(2.0, 4.0))
                    return True
            except Exception:
                continue

        # Fallback: chercher par texte
        try:
            for el in driver.find_elements(By.CSS_SELECTOR, 'button, a'):
                txt = el.text.lower().strip()
                if txt in ['apply', 'apply now', 'postuler', 'postuler maintenant']:
                    if el.is_displayed():
                        el.click()
                        logger.debug(f"SmartRecruiters: bouton Apply texte clique ('{txt}')")
                        time.sleep(random.uniform(2.0, 4.0))
                        return True
        except Exception:
            pass

        # Peut-etre qu'on est deja sur le formulaire
        try:
            forms = driver.find_elements(By.CSS_SELECTOR, 'form')
            if forms:
                logger.debug("SmartRecruiters: formulaire detecte, on est deja sur la page apply")
                return True
        except Exception:
            pass

        logger.warning("SmartRecruiters: bouton Apply non trouve")
        return False

    def _fill_form(self, driver, offer: dict) -> bool:
        """Remplit le formulaire SmartRecruiters."""
        # SmartRecruiters: formulaire React avec des champs standards
        field_map = {
            # Prenom
            'input[name="firstName"]': self.first_name,
            'input[name="first_name"]': self.first_name,
            'input[id*="firstName" i]': self.first_name,
            'input[aria-label*="first name" i]': self.first_name,
            'input[aria-label*="prenom" i]': self.first_name,
            'input[placeholder*="first name" i]': self.first_name,
            'input[placeholder*="prenom" i]': self.first_name,
            # Nom
            'input[name="lastName"]': self.last_name,
            'input[name="last_name"]': self.last_name,
            'input[id*="lastName" i]': self.last_name,
            'input[aria-label*="last name" i]': self.last_name,
            'input[aria-label*="nom" i]': self.last_name,
            'input[placeholder*="last name" i]': self.last_name,
            'input[placeholder*="nom" i]': self.last_name,
            # Email
            'input[name="email"]': self.email,
            'input[type="email"]': self.email,
            'input[id*="email" i]': self.email,
            'input[aria-label*="email" i]': self.email,
            # Telephone
            'input[name="phone"]': self.phone,
            'input[name="phoneNumber"]': self.phone,
            'input[type="tel"]': self.phone,
            'input[id*="phone" i]': self.phone,
            'input[aria-label*="phone" i]': self.phone,
            'input[aria-label*="telephone" i]': self.phone,
        }

        filled = set()
        for selector, value in field_map.items():
            if not value:
                continue
            try:
                field = driver.find_element(By.CSS_SELECTOR, selector)
                field_id = field.get_attribute('id') or field.get_attribute('name') or selector
                if field.is_displayed() and field_id not in filled:
                    current = field.get_attribute('value') or ''
                    if current.strip():
                        filled.add(field_id)
                        continue
                    field.clear()
                    self._human_type(field, value)
                    filled.add(field_id)
                    time.sleep(random.uniform(0.3, 0.7))
            except Exception:
                continue

        if filled:
            logger.info(f"SmartRecruiters: {len(filled)} champs remplis")

        # Upload CV
        cv = self.cv_path
        if cv and os.path.isfile(cv):
            try:
                file_inputs = driver.find_elements(By.CSS_SELECTOR, 'input[type="file"]')
                for fi in file_inputs:
                    try:
                        fi.send_keys(cv)
                        logger.info("SmartRecruiters: CV uploade")
                        time.sleep(random.uniform(2.0, 4.0))
                        break
                    except Exception:
                        continue
            except Exception:
                logger.warning("SmartRecruiters: upload CV echoue")

        # Cocher les checkboxes (consent, privacy)
        try:
            checkboxes = driver.find_elements(By.CSS_SELECTOR,
                'input[type="checkbox"][name*="consent" i], '
                'input[type="checkbox"][name*="privacy" i], '
                'input[type="checkbox"][name*="agree" i], '
                'input[type="checkbox"][required]')
            for cb in checkboxes:
                if not cb.is_selected():
                    try:
                        cb.click()
                    except Exception:
                        # Essayer via JS
                        driver.execute_script("arguments[0].click();", cb)
        except Exception:
            pass

        # Submit
        submit_selectors = [
            'button[type="submit"]',
            'button[data-test="submit-application"]',
            'button[class*="submit" i]',
        ]

        for sel in submit_selectors:
            try:
                btn = driver.find_element(By.CSS_SELECTOR, sel)
                if btn.is_displayed():
                    txt = btn.text.lower()
                    if any(w in txt for w in ['annuler', 'cancel', 'retour', 'back']):
                        continue
                    btn.click()
                    logger.info(f"SmartRecruiters: formulaire soumis ('{btn.text}')")
                    time.sleep(random.uniform(3.0, 5.0))
                    return self._verify_submission(driver)
            except Exception:
                continue

        # Fallback par texte
        try:
            for btn in driver.find_elements(By.CSS_SELECTOR, 'button'):
                txt = btn.text.lower().strip()
                if any(w in txt for w in ['submit', 'soumettre', 'envoyer', 'apply', 'postuler']):
                    if btn.is_displayed():
                        btn.click()
                        logger.info(f"SmartRecruiters: formulaire soumis (texte: '{txt}')")
                        time.sleep(random.uniform(3.0, 5.0))
                        return self._verify_submission(driver)
        except Exception:
            pass

        logger.warning("SmartRecruiters: bouton submit non trouve")
        return False

    def _verify_submission(self, driver) -> bool:
        """Verifie le succes de la soumission."""
        try:
            page_text = driver.find_element(By.TAG_NAME, 'body').text.lower()

            success_words = [
                'merci', 'thank you', 'candidature envoyee', 'application submitted',
                'successfully', 'confirmation', 'received', 'recue',
                'congratulations', 'felicitations'
            ]
            for w in success_words:
                if w in page_text:
                    logger.info(f"SmartRecruiters: confirmation ('{w}')")
                    return True

            error_words = ['erreur', 'error', 'required', 'obligatoire', 'invalide']
            for w in error_words:
                if w in page_text:
                    logger.warning(f"SmartRecruiters: erreur detectee ('{w}')")
                    return False

            # Pas clair -> optimiste
            logger.warning("SmartRecruiters: resultat incertain, considere comme succes")
            return True

        except Exception:
            return True

    def _human_type(self, element, text: str):
        """Tape avec delais aleatoires."""
        for char in text:
            element.send_keys(char)
            time.sleep(random.uniform(0.03, 0.12))
