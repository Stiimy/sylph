"""
Candidature automatique sur Indeed via Easy Apply.
Indeed est la plateforme la plus agressive en anti-bot.
CAPTCHA et bans sont frequents.
Utilise 2captcha pour contourner les CAPTCHAs si configure.
"""

from .base import BaseApplicator, ApplicationResult, ApplyStatus
from .motivation import generate_cover_letter
from utils.captcha import detect_captcha_type, inject_captcha_token, CaptchaSolver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
import time
import random
import os
import logging

logger = logging.getLogger("job-agent")


class IndeedApplicator(BaseApplicator):
    """Candidature auto sur Indeed via Easy Apply.
    
    Utilise 2captcha pour resoudre les CAPTCHAs automatiquement.
    """

    def __init__(self, profile: dict, browser=None, requester=None, captcha_solver: CaptchaSolver = None, ai_client=None):
        super().__init__(profile, browser=browser, requester=requester, ai_client=ai_client)
        self.captcha_solver = captcha_solver

    def _is_logged_in(self, driver) -> bool:
        """Verifie si on est connecte a Indeed"""
        try:
            # Methode 1: Chercher des elements de session
            indicators = [
                '#AccountMenu',
                'a[href*="/account"]',
                'a[href*="/myaccount"]',
                '[data-gnav-element-name="AccountMenu"]',
                'a[href*="/saved"]',
                '.gnav-AccountLink',
            ]
            for sel in indicators:
                try:
                    elems = driver.find_elements(By.CSS_SELECTOR, sel)
                    if elems and any(e.is_displayed() for e in elems):
                        logger.info(f"Indeed: connecte (detecte via '{sel}')")
                        return True
                except Exception:
                    continue

            # Methode 2: Verifier si le header montre "Connexion" ou "Mon compte"
            try:
                header_text = ""
                for header_sel in ['header', 'nav', '#gnav-header']:
                    try:
                        header_elem = driver.find_element(By.CSS_SELECTOR, header_sel)
                        header_text = header_elem.text.lower()
                        break
                    except Exception:
                        continue

                if header_text:
                    if any(w in header_text for w in ['connexion', 'se connecter', 'sign in', 'log in']):
                        logger.info("Indeed: PAS connecte (bouton connexion visible)")
                        return False
                    if any(w in header_text for w in ['mon compte', 'my account', 'mes offres', 'my jobs']):
                        logger.info("Indeed: connecte (lien mon compte dans header)")
                        return True
            except Exception:
                pass

            # Methode 3: Cookies de session
            try:
                cookies = driver.get_cookies()
                session_cookies = [c for c in cookies if
                    any(name in c['name'].lower() for name in
                        ['session', 'auth', 'token', 'indeed_rpc', 'CTK']
                    ) and 'indeed' in c.get('domain', '')
                ]
                if session_cookies:
                    logger.info(f"Indeed: cookies de session trouves ({len(session_cookies)})")
                else:
                    logger.info("Indeed: aucun cookie de session trouve")
            except Exception:
                pass

            logger.warning("Indeed: impossible de confirmer la connexion")
            return False
        except Exception as e:
            logger.error(f"Indeed: erreur verification connexion: {e}")
            return False

    def apply(self, offer: dict) -> ApplicationResult:
        """Tente de postuler via Indeed Easy Apply"""
        url = offer.get('url', '')
        title = offer.get('title', '')
        company = offer.get('company', '')

        if not self.browser or not self.browser.driver:
            return ApplicationResult(
                status=ApplyStatus.FAILED,
                platform="indeed",
                offer_title=title,
                company=company,
                url=url,
                details="Navigateur non disponible"
            )

        try:
            logger.info(f"Indeed Apply: ouverture de {url}")
            self.browser.get(url, wait=3)
            self.browser.accept_cookies()
            time.sleep(2)

            driver = self.browser.driver

            # Verifier si on est bloque (page 403 / CAPTCHA)
            if self._is_blocked(driver):
                return ApplicationResult(
                    status=ApplyStatus.CAPTCHA,
                    platform="indeed",
                    offer_title=title,
                    company=company,
                    url=url,
                    details="Bloque par Indeed (CAPTCHA ou 403)"
                )

            # Verifier si on est connecte au compte
            logged_in = self._is_logged_in(driver)
            if not logged_in:
                logger.warning(
                    "Indeed: PAS connecte au compte — candidature BLOQUEE. "
                    "Lance: python3 agent.py --import-cookies cookies.txt"
                )
                self.browser.screenshot(f"indeed_not_logged_{int(time.time())}")
                return ApplicationResult(
                    status=ApplyStatus.LOGIN_REQUIRED,
                    platform="indeed",
                    offer_title=title,
                    company=company,
                    url=url,
                    details="Pas connecte au compte Indeed — candidature annulee"
                )

            # Chercher le bouton Easy Apply
            apply_btn = self._find_apply_button(driver)
            if not apply_btn:
                # Peut-etre une redirection vers le site de l'entreprise
                ext_btn = self._find_external_apply(driver)
                if ext_btn:
                    ext_url = ext_btn.get_attribute('href') or ""
                    return ApplicationResult(
                        status=ApplyStatus.EXTERNAL,
                        platform="indeed",
                        offer_title=title,
                        company=company,
                        url=url,
                        external_url=ext_url,
                        details=f"Postuler sur le site de l'entreprise: {ext_url}"
                    )
                return ApplicationResult(
                    status=ApplyStatus.SKIPPED,
                    platform="indeed",
                    offer_title=title,
                    company=company,
                    url=url,
                    details="Pas de bouton Easy Apply"
                )

            # Cliquer sur Easy Apply
            try:
                driver.execute_script("arguments[0].click();", apply_btn)
            except Exception:
                apply_btn.click()
            time.sleep(3)

            # Verifier si un modal/formulaire s'est ouvert
            form_opened = self._wait_for_form(driver)
            if not form_opened:
                # Peut-etre redirige vers la page de login
                if 'login' in driver.current_url.lower() or 'signin' in driver.current_url.lower():
                    return ApplicationResult(
                        status=ApplyStatus.LOGIN_REQUIRED,
                        platform="indeed",
                        offer_title=title,
                        company=company,
                        url=url,
                        details="Connexion Indeed requise pour Easy Apply"
                    )
                return ApplicationResult(
                    status=ApplyStatus.FAILED,
                    platform="indeed",
                    offer_title=title,
                    company=company,
                    url=url,
                    details="Formulaire Easy Apply non charge"
                )

            # Remplir le formulaire multi-etapes
            success = self._fill_multi_step_form(driver, offer)

            if success:
                # Verification post-soumission
                verification = self._verify_submission(driver)

                if verification == "confirmed":
                    logger.info(f"Indeed Apply: candidature CONFIRMEE pour '{title}' @ {company}")
                    self.browser.screenshot(f"indeed_ok_{int(time.time())}")
                    return ApplicationResult(
                        status=ApplyStatus.SUCCESS,
                        platform="indeed",
                        offer_title=title,
                        company=company,
                        url=url,
                        details="Easy Apply envoye — confirmation detectee"
                    )
                elif verification == "error":
                    logger.warning(f"Indeed Apply: ERREUR post-soumission pour '{title}' @ {company}")
                    self.browser.screenshot(f"indeed_error_{int(time.time())}")
                    return ApplicationResult(
                        status=ApplyStatus.FAILED,
                        platform="indeed",
                        offer_title=title,
                        company=company,
                        url=url,
                        details="Formulaire soumis mais erreur detectee"
                    )
                else:
                    logger.warning(
                        f"Indeed Apply: formulaire soumis pour '{title}' @ {company} "
                        "mais pas de confirmation claire"
                    )
                    self.browser.screenshot(f"indeed_uncertain_{int(time.time())}")
                    return ApplicationResult(
                        status=ApplyStatus.SUCCESS,
                        platform="indeed",
                        offer_title=title,
                        company=company,
                        url=url,
                        details="Easy Apply envoye — pas de confirmation claire (verifier screenshot)"
                    )
            else:
                self.browser.screenshot(f"indeed_fail_{int(time.time())}")
                return ApplicationResult(
                    status=ApplyStatus.FAILED,
                    platform="indeed",
                    offer_title=title,
                    company=company,
                    url=url,
                    details="Echec remplissage formulaire Easy Apply"
                )

        except Exception as e:
            logger.error(f"Indeed Apply: erreur pour '{title}': {e}")
            return ApplicationResult(
                status=ApplyStatus.FAILED,
                platform="indeed",
                offer_title=title,
                company=company,
                url=url,
                details=str(e)
            )

    def _is_blocked(self, driver) -> bool:
        """Detecte si Indeed nous bloque. Tente de resoudre le CAPTCHA si 2captcha est configure."""
        try:
            page = driver.page_source.lower()
            title = driver.title.lower()
            
            # Verifier 403 / forbidden (pas de CAPTCHA a resoudre)
            if '403' in title or 'forbidden' in title:
                logger.warning("Indeed: page 403 Forbidden, pas de CAPTCHA a resoudre")
                return True
            
            has_captcha = any(w in page for w in ['captcha', 'robot', 'blocked', 'access denied'])
            if not has_captcha:
                return False
            
            # CAPTCHA detecte - tenter resolution si solver configure
            if not self.captcha_solver:
                logger.warning("Indeed: CAPTCHA detecte mais pas de solver 2captcha configure")
                return True
            
            logger.info("Indeed: CAPTCHA detecte, tentative de resolution via 2captcha...")
            captcha_type, site_key = detect_captcha_type(driver)
            
            if captcha_type == "none" or not site_key:
                logger.warning(f"Indeed: CAPTCHA detecte mais impossible d'extraire le type/sitekey (type={captcha_type})")
                return True
            
            # Resoudre le CAPTCHA
            current_url = driver.current_url
            token = None
            
            if captcha_type == "hcaptcha":
                token = self.captcha_solver.solve_hcaptcha(site_key, current_url)
            elif captcha_type == "recaptcha":
                token = self.captcha_solver.solve_recaptcha_v2(site_key, current_url)
            
            if not token:
                logger.error("Indeed: 2captcha n'a pas pu resoudre le CAPTCHA")
                return True
            
            # Injecter le token et soumettre
            inject_captcha_token(driver, token, captcha_type)
            time.sleep(2)
            
            # Essayer de soumettre le formulaire CAPTCHA
            try:
                submit_btns = driver.find_elements(By.CSS_SELECTOR, 
                    'button[type="submit"], input[type="submit"], .challenge-form button')
                for btn in submit_btns:
                    if btn.is_displayed():
                        driver.execute_script("arguments[0].click();", btn)
                        break
            except Exception:
                # Parfois le callback JS soumet automatiquement
                pass
            
            time.sleep(3)
            
            # Verifier si on est toujours bloque
            page_after = driver.page_source.lower()
            still_blocked = any(w in page_after for w in ['captcha', 'robot', 'blocked'])
            
            if still_blocked:
                logger.warning("Indeed: CAPTCHA resolu mais toujours bloque (ban IP?)")
                return True
            
            logger.info("Indeed: CAPTCHA resolu avec succes!")
            return False
            
        except Exception as e:
            logger.error(f"Indeed: erreur detection/resolution CAPTCHA: {e}")
        return False

    def _find_apply_button(self, driver) -> object | None:
        """Trouve le bouton Postuler rapidement / Easy Apply"""
        selectors = [
            '#indeedApplyButton',
            'button[id*="apply"]',
            '.ia-IndeedApplyButton',
            'button[class*="IndeedApply"]',
            'button[aria-label*="Postuler"]',
        ]
        for sel in selectors:
            try:
                elems = driver.find_elements(By.CSS_SELECTOR, sel)
                for elem in elems:
                    if elem.is_displayed():
                        text = elem.text.lower()
                        if 'postuler' in text or 'apply' in text:
                            return elem
            except Exception:
                continue
        return None

    def _find_external_apply(self, driver) -> object | None:
        """Trouve le lien 'Postuler sur le site de l'entreprise'"""
        try:
            links = driver.find_elements(By.CSS_SELECTOR, 'a[href]')
            for link in links:
                text = link.text.lower()
                if 'site de l' in text or 'postuler' in text:
                    href = link.get_attribute('href') or ""
                    if 'indeed.com' not in href and href.startswith('http'):
                        return link
        except Exception:
            pass
        return None

    def _wait_for_form(self, driver, timeout: int = 10) -> bool:
        """Attend l'ouverture du formulaire Easy Apply"""
        try:
            WebDriverWait(driver, timeout).until(
                lambda d: d.find_elements(By.CSS_SELECTOR,
                    '.ia-BasePage, .ia-container, [class*="IndeedApply"], '
                    'input[name="name"], input[type="email"]')
            )
            return True
        except Exception:
            return False

    def _fill_multi_step_form(self, driver, offer: dict) -> bool:
        """Remplit le formulaire multi-etapes d'Indeed"""
        max_steps = 5

        for step in range(max_steps):
            logger.debug(f"Indeed Apply: etape {step + 1}")
            time.sleep(random.uniform(1.5, 3.0))

            # Remplir les champs visibles sur cette etape
            self._fill_visible_fields(driver, offer)

            # Chercher le bouton Continuer / Soumettre
            submitted = self._click_next_or_submit(driver)
            if submitted == "submitted":
                return True
            elif submitted == "next":
                time.sleep(2)
                continue
            else:
                # Pas de bouton trouve
                break

        return False

    def _fill_visible_fields(self, driver, offer: dict):
        """Remplit tous les champs visibles sur l'etape courante"""
        # Nom complet
        for sel in ['input[name="name"]', 'input[id*="name"]', 'input[placeholder*="nom"]']:
            try:
                f = driver.find_element(By.CSS_SELECTOR, sel)
                if f.is_displayed() and not f.get_attribute('value'):
                    f.clear()
                    self._human_type(f, self.full_name)
                    break
            except Exception:
                continue

        # Email
        for sel in ['input[type="email"]', 'input[name="email"]', 'input[id*="email"]']:
            try:
                f = driver.find_element(By.CSS_SELECTOR, sel)
                if f.is_displayed() and not f.get_attribute('value'):
                    f.clear()
                    self._human_type(f, self.email)
                    break
            except Exception:
                continue

        # Telephone
        for sel in ['input[type="tel"]', 'input[name="phone"]', 'input[id*="phone"]']:
            try:
                f = driver.find_element(By.CSS_SELECTOR, sel)
                if f.is_displayed() and not f.get_attribute('value'):
                    f.clear()
                    self._human_type(f, self.phone)
                    break
            except Exception:
                continue

        # CV upload
        cv = self.cv_path
        if cv and os.path.exists(cv):
            try:
                file_inputs = driver.find_elements(By.CSS_SELECTOR, 'input[type="file"]')
                for fi in file_inputs:
                    fi.send_keys(cv)
                    time.sleep(2)
                    break
            except Exception:
                pass

        # Message / motivation
        for sel in ['textarea', 'textarea[name*="message"]', 'textarea[name*="letter"]']:
            try:
                f = driver.find_element(By.CSS_SELECTOR, sel)
                if f.is_displayed() and not f.get_attribute('value'):
                    letter = generate_cover_letter(offer, self.profile, ai_client=self.ai_client)
                    f.send_keys(letter)
                    break
            except Exception:
                continue

    def _click_next_or_submit(self, driver) -> str:
        """Clique sur Continuer ou Soumettre. Retourne 'next', 'submitted', ou ''"""
        try:
            buttons = driver.find_elements(By.CSS_SELECTOR, 'button, input[type="submit"]')
            for btn in buttons:
                if not btn.is_displayed():
                    continue
                text = btn.text.strip().lower()

                # Bouton de soumission finale
                if any(w in text for w in ['soumettre', 'envoyer', 'submit', 'postuler']):
                    driver.execute_script("arguments[0].click();", btn)
                    time.sleep(3)
                    return "submitted"

            # Bouton continuer / suivant
            for btn in buttons:
                if not btn.is_displayed():
                    continue
                text = btn.text.strip().lower()
                if any(w in text for w in ['continuer', 'suivant', 'next', 'continue']):
                    driver.execute_script("arguments[0].click();", btn)
                    time.sleep(2)
                    return "next"

        except Exception:
            pass
        return ""

    def _human_type(self, element, text: str):
        """Tape comme un humain"""
        for char in text:
            element.send_keys(char)
            time.sleep(random.uniform(0.04, 0.15))

    def _verify_submission(self, driver, timeout: int = 5) -> str:
        """Verifie si la soumission Indeed a reussi.
        
        Retourne:
            "confirmed" — message de confirmation detecte
            "error" — message d'erreur detecte  
            "unknown" — rien de clair
        """
        try:
            time.sleep(2)

            page_text = driver.page_source.lower()

            # Indicateurs de CONFIRMATION Indeed
            confirmation_signals = [
                'candidature envoyée',
                'candidature envoyee',
                'your application has been submitted',
                'application submitted',
                'votre candidature a été envoyée',
                'votre candidature a ete envoyee',
                'merci d\'avoir postulé',
                'thank you for applying',
                'successfully applied',
            ]
            for signal in confirmation_signals:
                if signal in page_text:
                    logger.info(f"Indeed Apply: confirmation detectee — '{signal}'")
                    return "confirmed"

            # Elements CSS de confirmation
            confirm_selectors = [
                '.ia-PostApply',
                '.ia-PostApply-header',
                '[class*="PostApply"]',
                '[class*="success"]',
                '.ia-Success',
            ]
            for sel in confirm_selectors:
                try:
                    elems = driver.find_elements(By.CSS_SELECTOR, sel)
                    if elems and any(e.is_displayed() for e in elems):
                        logger.info(f"Indeed Apply: confirmation CSS detectee — '{sel}'")
                        return "confirmed"
                except Exception:
                    continue

            # Indicateurs d'ERREUR
            error_signals = [
                'erreur',
                'error',
                'something went wrong',
                'une erreur est survenue',
                'veuillez réessayer',
                'please try again',
                'champ obligatoire',
                'required field',
            ]
            for signal in error_signals:
                if signal in page_text:
                    # Filtrer les faux positifs (le mot "error" dans du JS/CSS)
                    # On cherche dans le body text visible
                    try:
                        body_text = driver.find_element(By.TAG_NAME, 'body').text.lower()
                        if signal in body_text:
                            logger.warning(f"Indeed Apply: erreur detectee — '{signal}'")
                            return "error"
                    except Exception:
                        pass

            # Verifier si le formulaire Easy Apply a disparu
            form_gone = True
            for sel in ['.ia-BasePage', '.ia-container', '[class*="IndeedApply"]']:
                try:
                    elems = driver.find_elements(By.CSS_SELECTOR, sel)
                    if elems and any(e.is_displayed() for e in elems):
                        form_gone = False
                        break
                except Exception:
                    continue

            if form_gone:
                logger.info("Indeed Apply: formulaire disparu apres soumission (probable succes)")
                return "confirmed"

            return "unknown"

        except Exception as e:
            logger.warning(f"Indeed Apply: erreur verification post-soumission: {e}")
            return "unknown"
