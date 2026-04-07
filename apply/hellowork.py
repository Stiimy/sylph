"""
Candidature automatique sur HelloWork via SmartApply.
Utilise Selenium stealth pour remplir le formulaire turbo-frame.
"""

from .base import BaseApplicator, ApplicationResult, ApplyStatus
from .motivation import generate_cover_letter
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
import time
import random
import logging
import os

logger = logging.getLogger("job-agent")


class HelloWorkApplicator(BaseApplicator):
    """Candidature auto sur HelloWork via SmartApply"""

    def __init__(self, profile, browser=None, requester=None, ai_client=None, config=None):
        super().__init__(profile, browser, requester, ai_client)
        self._config = config or {}
        self._login_attempted = False  # Eviter les boucles infinies de login

    def _login(self, driver) -> bool:
        """Auto-login HelloWork avec email + mot de passe depuis config.yaml.
        
        Config attendue:
            platforms.hellowork.email: "..."
            platforms.hellowork.password: "..."
        """
        hw_config = self._config.get('platforms', {}).get('hellowork', {})
        email = hw_config.get('email', '')
        password = hw_config.get('password', '')

        if not email or not password:
            logger.warning(
                "HelloWork auto-login: identifiants manquants dans config.yaml. "
                "Ajoute platforms.hellowork.email et platforms.hellowork.password"
            )
            return False

        try:
            logger.info("HelloWork auto-login: navigation vers la page de connexion...")
            driver.get("https://www.hellowork.com/fr-fr/compte/connexion")
            time.sleep(random.uniform(2.0, 3.5))

            # Accepter les cookies si popup presente
            try:
                self.browser.accept_cookies()
                time.sleep(1)
            except Exception:
                pass

            # Trouver le champ email
            email_field = None
            for sel in ['input[name="email"]', 'input[type="email"]', 'input#email',
                        'input[data-cy="email"]', 'input[placeholder*="mail"]']:
                try:
                    field = driver.find_element(By.CSS_SELECTOR, sel)
                    if field.is_displayed():
                        email_field = field
                        break
                except Exception:
                    continue

            if not email_field:
                logger.error("HelloWork auto-login: champ email non trouve")
                self.browser.screenshot(f"hw_login_noemail_{int(time.time())}")
                return False

            # Remplir email
            email_field.clear()
            self._human_type(email_field, email)
            time.sleep(random.uniform(0.5, 1.0))

            # Trouver le champ mot de passe
            pwd_field = None
            for sel in ['input[name="password"]', 'input[type="password"]', 'input#password',
                        'input[data-cy="password"]']:
                try:
                    field = driver.find_element(By.CSS_SELECTOR, sel)
                    if field.is_displayed():
                        pwd_field = field
                        break
                except Exception:
                    continue

            if not pwd_field:
                # Parfois le formulaire est en 2 etapes: email d'abord, puis mot de passe
                # Soumettre l'email d'abord
                try:
                    submit_btns = driver.find_elements(By.CSS_SELECTOR, 'button[type="submit"], input[type="submit"]')
                    for btn in submit_btns:
                        if btn.is_displayed():
                            btn.click()
                            time.sleep(random.uniform(2.0, 3.0))
                            break
                except Exception:
                    email_field.send_keys(Keys.RETURN)
                    time.sleep(random.uniform(2.0, 3.0))

                # Re-chercher le champ mot de passe
                for sel in ['input[name="password"]', 'input[type="password"]', 'input#password']:
                    try:
                        field = driver.find_element(By.CSS_SELECTOR, sel)
                        if field.is_displayed():
                            pwd_field = field
                            break
                    except Exception:
                        continue

            if not pwd_field:
                logger.error("HelloWork auto-login: champ mot de passe non trouve")
                self.browser.screenshot(f"hw_login_nopwd_{int(time.time())}")
                return False

            # Remplir mot de passe
            pwd_field.clear()
            self._human_type(pwd_field, password)
            time.sleep(random.uniform(0.5, 1.0))

            # Soumettre le formulaire
            try:
                submit_btns = driver.find_elements(By.CSS_SELECTOR, 'button[type="submit"], input[type="submit"]')
                clicked = False
                for btn in submit_btns:
                    if btn.is_displayed():
                        text = btn.text.lower()
                        if any(w in text for w in ['connecter', 'connexion', 'login', 'valider', 'se connecter']):
                            btn.click()
                            clicked = True
                            break
                if not clicked:
                    for btn in submit_btns:
                        if btn.is_displayed():
                            btn.click()
                            clicked = True
                            break
                if not clicked:
                    pwd_field.send_keys(Keys.RETURN)
            except Exception:
                pwd_field.send_keys(Keys.RETURN)

            # Attendre la redirection post-login
            time.sleep(random.uniform(3.0, 5.0))

            # Verifier si le login a reussi
            current_url = driver.current_url
            if 'login' not in current_url.lower():
                logger.info(f"HelloWork auto-login: SUCCES (redirige vers {current_url})")
                return True

            # Verifier les elements de session
            if self._is_logged_in(driver):
                logger.info("HelloWork auto-login: SUCCES (session detectee)")
                return True

            # Verifier s'il y a un message d'erreur
            try:
                page_text = driver.find_element(By.TAG_NAME, 'body').text.lower()
                if any(w in page_text for w in ['mot de passe incorrect', 'identifiants incorrects',
                    'email ou mot de passe', 'invalid password', 'invalid email',
                    'compte introuvable', 'erreur']):
                    logger.error("HelloWork auto-login: identifiants incorrects")
                    self.browser.screenshot(f"hw_login_badcreds_{int(time.time())}")
                    return False
            except Exception:
                pass

            logger.warning("HelloWork auto-login: resultat incertain")
            self.browser.screenshot(f"hw_login_uncertain_{int(time.time())}")
            return False

        except Exception as e:
            logger.error(f"HelloWork auto-login: erreur: {e}")
            self.browser.screenshot(f"hw_login_error_{int(time.time())}")
            return False

    def _is_logged_in(self, driver) -> bool:
        """Verifie si on est connecte a HelloWork.
        
        Detection multi-methode:
        1. Avatar / initiales utilisateur dans le header (ex: cercle "KJ")
        2. Liens d'espace candidat (mon-espace, mes-candidatures, deconnexion)
        3. Absence du bouton "Se connecter"
        4. Cookies de session
        """
        try:
            # Methode 1: Avatar initiales ou menu utilisateur dans le header
            # HelloWork affiche un cercle avec les initiales (ex: "KJ") quand connecte
            avatar_selectors = [
                '[data-cy="userMenu"]',
                '[data-cy="user-menu"]',
                '.user-menu',
                '.avatar',
                '.user-avatar',
                'button[class*="avatar"]',
                'nav [class*="user"]',
                'header [class*="user"]',
                # Selecteurs generiques pour cercle d'initiales
                'header button[class*="rounded-full"]',
                'header [class*="avatar"]',
                'header [class*="initials"]',
                'nav [class*="avatar"]',
                'nav button[aria-haspopup]',
                'header button[aria-haspopup]',
            ]
            for sel in avatar_selectors:
                try:
                    elems = driver.find_elements(By.CSS_SELECTOR, sel)
                    if elems and any(e.is_displayed() for e in elems):
                        logger.info(f"HelloWork: connecte (detecte via '{sel}')")
                        return True
                except Exception:
                    continue

            # Methode 2: Liens espace candidat
            link_selectors = [
                'a[href*="/mon-espace"]',
                'a[href*="/espace-candidat"]',
                'a[href*="/mes-candidatures"]',
                'a[href*="/mon-compte"]',
                'a[href*="/deconnexion"]',
                'a[href*="/logout"]',
            ]
            for sel in link_selectors:
                try:
                    elems = driver.find_elements(By.CSS_SELECTOR, sel)
                    if elems and any(e.is_displayed() for e in elems):
                        logger.info(f"HelloWork: connecte (lien detecte via '{sel}')")
                        return True
                except Exception:
                    continue

            # Methode 3: Verifier le texte du header
            try:
                header_text = ""
                for header_sel in ['header', 'nav', '.navbar']:
                    try:
                        header_elem = driver.find_element(By.CSS_SELECTOR, header_sel)
                        header_text = header_elem.text.lower()
                        break
                    except Exception:
                        continue
                
                if header_text:
                    # Si on voit "Se connecter", on n'est PAS connecte
                    if any(w in header_text for w in ['se connecter', 'connexion', 'inscription', 'créer un compte']):
                        logger.info("HelloWork: PAS connecte (bouton 'Se connecter' visible dans header)")
                        return False
                    # Si on voit des liens de session, on EST connecte
                    if any(w in header_text for w in ['mon espace', 'mes candidatures', 'mon compte', 'déconnexion']):
                        logger.info("HelloWork: connecte (lien espace candidat dans header)")
                        return True
            except Exception:
                pass

            # Methode 4: Chercher un element avec 2 lettres majuscules (initiales)
            # C'est le pattern du cercle d'avatar HelloWork
            try:
                # Chercher tous les petits elements textuels dans le header
                header = driver.find_element(By.TAG_NAME, 'header')
                small_elems = header.find_elements(By.CSS_SELECTOR, 'span, div, button, a')
                for elem in small_elems:
                    try:
                        text = elem.text.strip()
                        # Initiales = exactement 2 lettres majuscules (ex: "KJ")
                        if len(text) == 2 and text.isalpha() and text.isupper():
                            logger.info(f"HelloWork: connecte (initiales '{text}' detectees dans header)")
                            return True
                    except Exception:
                        continue
            except Exception:
                pass

            # Methode 5: Verifier les cookies de session
            try:
                cookies = driver.get_cookies()
                session_cookies = [c for c in cookies if 
                    any(name in c['name'].lower() for name in 
                        ['session', 'auth', 'token', 'user', 'logged', 'connect']
                    ) and 'hellowork' in c.get('domain', '')
                ]
                if session_cookies:
                    logger.info(f"HelloWork: cookies de session trouves ({len(session_cookies)}) — probablement connecte")
                    # Avec les cookies + pas de bouton "Se connecter" visible = connecte
                    return True
            except Exception:
                pass

            logger.warning("HelloWork: impossible de confirmer la connexion")
            return False
        except Exception as e:
            logger.error(f"HelloWork: erreur verification connexion: {e}")
            return False

    def apply(self, offer: dict) -> ApplicationResult:
        """Postule sur une offre HelloWork"""
        url = offer.get('url', '')
        title = offer.get('title', '')
        company = offer.get('company', '')

        if not self.browser or not self.browser.driver:
            return ApplicationResult(
                status=ApplyStatus.FAILED,
                platform="hellowork",
                offer_title=title,
                company=company,
                url=url,
                details="Navigateur non disponible"
            )

        try:
            logger.info(f"HelloWork Apply: ouverture de {url}")
            self.browser.get(url, wait=3)
            self.browser.accept_cookies()
            time.sleep(1)

            driver = self.browser.driver

            # Verifier si on est connecte au compte
            logged_in = self._is_logged_in(driver)
            if not logged_in and not self._login_attempted:
                # Tenter l'auto-login
                logger.info("HelloWork: PAS connecte — tentative d'auto-login...")
                self._login_attempted = True
                login_ok = self._login(driver)
                if login_ok:
                    logger.info("HelloWork: auto-login REUSSI — reprise de la candidature")
                    # Re-naviguer vers l'offre apres le login
                    self.browser.get(url, wait=3)
                    self.browser.accept_cookies()
                    time.sleep(1)
                    logged_in = True
                else:
                    logger.warning("HelloWork: auto-login ECHOUE")
            
            if not logged_in:
                logger.warning(
                    "HelloWork: PAS connecte au compte — candidature BLOQUEE. "
                    "Ajoute tes identifiants dans config.yaml: "
                    "platforms.hellowork.email et platforms.hellowork.password"
                )
                self.browser.screenshot(f"hellowork_not_logged_{int(time.time())}")
                return ApplicationResult(
                    status=ApplyStatus.LOGIN_REQUIRED,
                    platform="hellowork",
                    offer_title=title,
                    company=company,
                    url=url,
                    details="Pas connecte — auto-login echoue. Verifier les identifiants dans config.yaml"
                )

            logger.info("HelloWork Apply: connecte au compte — candidature autorisee")

            # Verifier si c'est une offre SmartApply (formulaire direct)
            # ou une redirection externe
            apply_btn = self._find_apply_button(driver)
            if not apply_btn:
                return ApplicationResult(
                    status=ApplyStatus.SKIPPED,
                    platform="hellowork",
                    offer_title=title,
                    company=company,
                    url=url,
                    details="Bouton postuler non trouve"
                )

            # Cliquer sur le bouton postuler pour scroller vers le formulaire
            try:
                driver.execute_script("arguments[0].click();", apply_btn)
            except Exception:
                apply_btn.click()
            time.sleep(2)

            # Attendre que le turbo-frame charge le formulaire
            frame_loaded = self._wait_for_form(driver)
            if not frame_loaded:
                # Peut-etre une redirection externe
                external = self._check_external_redirect(driver, url)
                if external:
                    return ApplicationResult(
                        status=ApplyStatus.EXTERNAL,
                        platform="hellowork",
                        offer_title=title,
                        company=company,
                        url=url,
                        external_url=external,
                        details=f"Redirection externe: {external}"
                    )
                self.browser.screenshot(f"hellowork_noform_{int(time.time())}")
                return ApplicationResult(
                    status=ApplyStatus.FAILED,
                    platform="hellowork",
                    offer_title=title,
                    company=company,
                    url=url,
                    details="Formulaire non charge (turbo-frame)"
                )

            # Remplir le formulaire etape par etape
            form_filled = self._fill_form(driver, offer)

            if form_filled:
                # Verification post-soumission: chercher confirmation ou erreur
                verification = self._verify_submission(driver)

                if verification == "confirmed":
                    logger.info(f"HelloWork Apply: candidature CONFIRMEE pour '{title}' @ {company}")
                    self.browser.screenshot(f"hellowork_ok_{int(time.time())}")
                    return ApplicationResult(
                        status=ApplyStatus.SUCCESS,
                        platform="hellowork",
                        offer_title=title,
                        company=company,
                        url=url,
                        details="SmartApply envoye — confirmation detectee"
                    )
                elif verification == "error":
                    logger.warning(f"HelloWork Apply: ERREUR post-soumission pour '{title}' @ {company}")
                    self.browser.screenshot(f"hellowork_error_{int(time.time())}")
                    return ApplicationResult(
                        status=ApplyStatus.FAILED,
                        platform="hellowork",
                        offer_title=title,
                        company=company,
                        url=url,
                        details="Formulaire soumis mais erreur detectee sur la page"
                    )
                else:
                    # Pas de confirmation ni d'erreur claire — probablement OK mais incertain
                    logger.warning(
                        f"HelloWork Apply: formulaire soumis pour '{title}' @ {company} "
                        "mais pas de confirmation claire detectee"
                    )
                    self.browser.screenshot(f"hellowork_uncertain_{int(time.time())}")
                    return ApplicationResult(
                        status=ApplyStatus.SUCCESS,
                        platform="hellowork",
                        offer_title=title,
                        company=company,
                        url=url,
                        details="SmartApply envoye — pas de confirmation claire (verifier screenshot)"
                    )
            else:
                # Screenshot pour debug
                self.browser.screenshot(f"hellowork_fail_{int(time.time())}")
                return ApplicationResult(
                    status=ApplyStatus.FAILED,
                    platform="hellowork",
                    offer_title=title,
                    company=company,
                    url=url,
                    details="Echec remplissage formulaire"
                )

        except Exception as e:
            logger.error(f"HelloWork Apply: erreur pour '{title}': {e}")
            self.browser.screenshot(f"hellowork_exception_{int(time.time())}")
            return ApplicationResult(
                status=ApplyStatus.FAILED,
                platform="hellowork",
                offer_title=title,
                company=company,
                url=url,
                details=str(e)
            )

    def _find_apply_button(self, driver) -> object | None:
        """Trouve le bouton Postuler"""
        # Essayer plusieurs selecteurs
        selectors = [
            '[data-cy="applyButton"]',
            'a[href="#postuler"]',
            '#mobile-sticky-button',
            'a.btn-apply',
            'button[class*="apply"]',
        ]
        for sel in selectors:
            try:
                elems = driver.find_elements(By.CSS_SELECTOR, sel)
                for elem in elems:
                    if elem.is_displayed():
                        return elem
            except Exception:
                continue

        # Fallback: chercher par texte
        try:
            buttons = driver.find_elements(By.CSS_SELECTOR, 'a, button')
            for btn in buttons:
                text = btn.text.strip().lower()
                if text in ['postuler', 'postuler maintenant', 'candidater']:
                    if btn.is_displayed():
                        return btn
        except Exception:
            pass

        return None

    def _wait_for_form(self, driver, timeout: int = 10) -> bool:
        """Attend que le formulaire SmartApply charge dans le turbo-frame.
        Si connecte, le formulaire peut afficher directement le champ message/CV.
        """
        try:
            WebDriverWait(driver, timeout).until(
                lambda d: (
                    d.find_elements(By.CSS_SELECTOR,
                        '[data-cy="emailInput"], input#Email, '
                        '#postuler input[type="email"], '
                        '#offer-detail-step-frame input, '
                        '#offer-detail-step-frame textarea, '
                        'input[type="file"], '
                        'textarea#Message, textarea[name="Message"], '
                        'button[type="submit"]'
                    )
                )
            )
            return True
        except Exception:
            return False

    def _fill_form(self, driver, offer: dict) -> bool:
        """Remplit le formulaire SmartApply etape par etape.
        Si connecte, certains champs seront pre-remplis ou absents.
        """
        try:
            # Etape 1: Email (peut etre absent ou pre-rempli si connecte)
            email_filled = self._fill_email(driver)
            if not email_filled:
                # Pas de champ email = probablement connecte, le formulaire commence plus loin
                logger.debug("HelloWork Apply: pas de champ email (probablement connecte)")

            # Pause humaine
            time.sleep(random.uniform(1.5, 3.0))

            # Etape 2: Nom / Prenom (si present)
            self._fill_name_fields(driver)
            time.sleep(random.uniform(1.0, 2.0))

            # Etape 3: Telephone (si present)
            self._fill_phone(driver)
            time.sleep(random.uniform(1.0, 2.0))

            # Etape 4: CV upload (si champ present)
            self._upload_cv(driver)
            time.sleep(random.uniform(1.0, 2.0))

            # Etape 5: Message / lettre de motivation (si present)
            self._fill_message(driver, offer)
            time.sleep(random.uniform(1.0, 2.0))

            # Soumettre
            return self._submit_form(driver)

        except Exception as e:
            logger.error(f"HelloWork Apply: erreur remplissage: {e}")
            return False

    def _fill_email(self, driver) -> bool:
        """Remplit le champ email (sauf s'il est deja rempli — connecte)"""
        selectors = [
            '[data-cy="emailInput"]',
            'input#Email',
            'input[name="Email"]',
            'input[type="email"]',
        ]
        for sel in selectors:
            try:
                field = driver.find_element(By.CSS_SELECTOR, sel)
                if field.is_displayed():
                    current_val = field.get_attribute('value') or ''
                    if current_val.strip():
                        logger.debug(f"HelloWork Apply: email deja rempli ({current_val})")
                        field.send_keys(Keys.TAB)
                        time.sleep(2)
                        return True
                    field.clear()
                    self._human_type(field, self.email)
                    logger.debug("HelloWork Apply: email rempli")
                    # Appuyer sur Tab ou cliquer ailleurs pour declencher la validation
                    field.send_keys(Keys.TAB)
                    time.sleep(2)  # Attendre le chargement eventuel du step suivant
                    return True
            except Exception:
                continue
        return False

    def _fill_name_fields(self, driver):
        """Remplit prenom et nom si les champs existent"""
        # Prenom
        for sel in ['input#FirstName', 'input[name="FirstName"]', 'input[name="prenom"]',
                     'input[placeholder*="rénom"]', 'input[placeholder*="renom"]']:
            try:
                field = driver.find_element(By.CSS_SELECTOR, sel)
                if field.is_displayed() and not field.get_attribute('value'):
                    field.clear()
                    self._human_type(field, self.first_name)
                    logger.debug("HelloWork Apply: prenom rempli")
                    break
            except Exception:
                continue

        # Nom
        for sel in ['input#LastName', 'input[name="LastName"]', 'input[name="nom"]',
                     'input[placeholder*="om"]']:
            try:
                field = driver.find_element(By.CSS_SELECTOR, sel)
                if field.is_displayed() and not field.get_attribute('value'):
                    field.clear()
                    self._human_type(field, self.last_name)
                    logger.debug("HelloWork Apply: nom rempli")
                    break
            except Exception:
                continue

    def _fill_phone(self, driver):
        """Remplit le telephone si le champ existe"""
        for sel in ['input#Phone', 'input[name="Phone"]', 'input[name="phone"]',
                     'input[type="tel"]', 'input[placeholder*="elephone"]']:
            try:
                field = driver.find_element(By.CSS_SELECTOR, sel)
                if field.is_displayed() and not field.get_attribute('value'):
                    field.clear()
                    self._human_type(field, self.phone)
                    logger.debug("HelloWork Apply: telephone rempli")
                    break
            except Exception:
                continue

    def _upload_cv(self, driver):
        """Upload le CV si un champ file existe"""
        cv = self.cv_path
        if not cv or not os.path.exists(cv):
            logger.debug("HelloWork Apply: pas de CV ou fichier introuvable")
            return

        for sel in ['input[type="file"]', 'input[name*="cv"]', 'input[name*="CV"]',
                     'input[name*="resume"]', 'input[accept*="pdf"]']:
            try:
                field = driver.find_element(By.CSS_SELECTOR, sel)
                # Les champs file ne sont pas forcement visibles, on envoie directement
                field.send_keys(cv)
                logger.debug("HelloWork Apply: CV uploade")
                time.sleep(2)  # Attendre l'upload
                break
            except Exception:
                continue

    def _fill_message(self, driver, offer: dict):
        """Remplit le message / lettre de motivation si le champ existe"""
        for sel in ['textarea#Message', 'textarea[name="Message"]', 'textarea[name="message"]',
                     'textarea[placeholder*="otivation"]', 'textarea[placeholder*="essage"]',
                     'textarea']:
            try:
                field = driver.find_element(By.CSS_SELECTOR, sel)
                if field.is_displayed():
                    letter = generate_cover_letter(offer, self.profile, ai_client=self.ai_client)
                    field.clear()
                    # Pour les textarea longs, on peut coller directement
                    field.send_keys(letter)
                    logger.debug("HelloWork Apply: lettre de motivation remplie")
                    break
            except Exception:
                continue

    def _submit_form(self, driver) -> bool:
        """Soumet le formulaire"""
        # Chercher le bouton de soumission
        selectors = [
            'button[type="submit"]',
            '[data-cy="submitButton"]',
            'button[class*="submit"]',
            'input[type="submit"]',
        ]
        for sel in selectors:
            try:
                btns = driver.find_elements(By.CSS_SELECTOR, sel)
                for btn in btns:
                    if btn.is_displayed():
                        text = btn.text.lower()
                        # Eviter les boutons de login/connexion
                        if any(w in text for w in ['connexion', 'login', 'inscrire']):
                            continue
                        driver.execute_script("arguments[0].click();", btn)
                        time.sleep(3)
                        logger.info("HelloWork Apply: formulaire soumis")
                        return True
            except Exception:
                continue

        # Fallback: chercher par texte
        try:
            buttons = driver.find_elements(By.CSS_SELECTOR, 'button, input[type="submit"]')
            for btn in buttons:
                text = btn.text.strip().lower()
                if any(w in text for w in ['envoyer', 'soumettre', 'postuler', 'candidater', 'valider']):
                    if btn.is_displayed():
                        driver.execute_script("arguments[0].click();", btn)
                        time.sleep(3)
                        logger.info("HelloWork Apply: formulaire soumis (fallback)")
                        return True
        except Exception:
            pass

        logger.warning("HelloWork Apply: bouton submit non trouve")
        return False

    def _verify_submission(self, driver, timeout: int = 5) -> str:
        """Verifie si la soumission a reussi apres le click submit.
        
        Retourne:
            "confirmed" — message de confirmation detecte
            "error" — message d'erreur detecte  
            "unknown" — rien de clair
        """
        try:
            time.sleep(2)  # Laisser le temps a la page de reagir

            page_text = driver.page_source.lower()

            # Indicateurs de CONFIRMATION HelloWork
            confirmation_signals = [
                'candidature envoyée',
                'candidature envoyee',
                'votre candidature a bien été',
                'votre candidature a bien ete',
                'candidature transmise',
                'merci pour votre candidature',
                'merci pour votre intérêt',
                'merci pour votre interet',
                'votre message a été envoyé',
                'votre message a ete envoye',
                'candidature enregistrée',
                'candidature enregistree',
                'successfully applied',
                'application sent',
            ]
            for signal in confirmation_signals:
                if signal in page_text:
                    logger.info(f"HelloWork Apply: confirmation detectee — '{signal}'")
                    return "confirmed"

            # Indicateurs de confirmation CSS (elements de succes)
            confirm_selectors = [
                '[data-cy="applicationSuccess"]',
                '[data-cy="confirmationMessage"]',
                '.application-success',
                '.confirmation-message',
                '.alert-success',
                '.success-message',
            ]
            for sel in confirm_selectors:
                try:
                    elems = driver.find_elements(By.CSS_SELECTOR, sel)
                    if elems and any(e.is_displayed() for e in elems):
                        logger.info(f"HelloWork Apply: confirmation CSS detectee — '{sel}'")
                        return "confirmed"
                except Exception:
                    continue

            # Indicateurs d'ERREUR
            error_signals = [
                'une erreur est survenue',
                'erreur lors de',
                'veuillez réessayer',
                'veuillez reessayer',
                'champ obligatoire',
                'champs obligatoires',
                'adresse email invalide',
                'email invalide',
                'format invalide',
                'ce champ est requis',
            ]
            for signal in error_signals:
                if signal in page_text:
                    logger.warning(f"HelloWork Apply: erreur detectee — '{signal}'")
                    return "error"

            # Indicateurs d'erreur CSS
            error_selectors = [
                '.alert-danger',
                '.error-message',
                '.form-error',
                '.field-error',
                '[class*="error"]',
                'input:invalid',
            ]
            for sel in error_selectors:
                try:
                    elems = driver.find_elements(By.CSS_SELECTOR, sel)
                    visible_errors = [e for e in elems if e.is_displayed() and e.text.strip()]
                    if visible_errors:
                        error_text = visible_errors[0].text.strip()[:100]
                        logger.warning(f"HelloWork Apply: erreur CSS detectee — '{sel}': {error_text}")
                        return "error"
                except Exception:
                    continue

            # Verifier si le formulaire a disparu (signe de succes sur un SPA turbo)
            form_gone = True
            for sel in ['button[type="submit"]', '[data-cy="submitButton"]']:
                try:
                    btns = driver.find_elements(By.CSS_SELECTOR, sel)
                    if btns and any(b.is_displayed() for b in btns):
                        form_gone = False
                        break
                except Exception:
                    continue

            if form_gone:
                logger.info("HelloWork Apply: formulaire disparu apres soumission (probable succes)")
                return "confirmed"

            return "unknown"

        except Exception as e:
            logger.warning(f"HelloWork Apply: erreur verification post-soumission: {e}")
            return "unknown"

    def _check_external_redirect(self, driver, original_url: str) -> str:
        """Verifie si on a ete redirige vers un site externe"""
        current = driver.current_url
        if 'hellowork.com' not in current and current != original_url:
            return current
        return ""

    def _human_type(self, element, text: str):
        """Tape le texte caractere par caractere avec delai humain"""
        for char in text:
            element.send_keys(char)
            time.sleep(random.uniform(0.03, 0.12))
