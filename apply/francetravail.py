"""
Candidature sur France Travail.

Strategie:
1. Auto-login via identifiants FranceConnect (email + mot de passe)
2. Si email de contact trouve -> envoyer CV + lettre de motivation par email (SMTP)
3. Si lien externe -> retourner l'URL pour postulation manuelle
4. Si login requis -> tenter auto-login puis re-essayer
"""

from .base import BaseApplicator, ApplicationResult, ApplyStatus
from .motivation import generate_cover_letter
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
import time
import re
import random
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import os

logger = logging.getLogger("job-agent")


class FranceTravailApplicator(BaseApplicator):
    """Candidature sur France Travail - auto-login + envoi email automatique"""

    def __init__(self, profile, browser=None, requester=None, ai_client=None, config=None):
        super().__init__(profile, browser, requester, ai_client)
        self._config = config or {}
        self._login_attempted = False

    def _login(self, driver) -> bool:
        """Auto-login France Travail via identifiants.
        
        Config attendue:
            platforms.francetravail.email: "..."
            platforms.francetravail.password: "..."
        """
        ft_config = self._config.get('platforms', {}).get('francetravail', {})
        email = ft_config.get('email', '')
        password = ft_config.get('password', '')

        if not email or not password:
            logger.warning(
                "France Travail auto-login: identifiants manquants. "
                "Ajoute platforms.francetravail.email et platforms.francetravail.password"
            )
            return False

        try:
            logger.info("France Travail auto-login: navigation vers la page de connexion...")
            driver.get("https://candidat.francetravail.fr/espacepersonnel/")
            time.sleep(random.uniform(3.0, 5.0))

            # Accepter les cookies
            try:
                self.browser.accept_cookies()
                time.sleep(1)
            except Exception:
                pass

            # FranceConnect redirige vers une page d'authentification
            # Chercher le bouton "Se connecter" ou le formulaire directement
            
            # Option 1: Bouton "Se connecter avec FranceConnect" ou "Identifiant"
            login_btn = None
            for sel in ['a[href*="authentification"]', 'a[href*="connexion"]',
                        'button[class*="connect"]', '#login-button',
                        'a[class*="login"]', 'a[class*="connect"]']:
                try:
                    elem = driver.find_element(By.CSS_SELECTOR, sel)
                    if elem.is_displayed():
                        login_btn = elem
                        break
                except Exception:
                    continue

            # Fallback: chercher par texte
            if not login_btn:
                try:
                    links = driver.find_elements(By.CSS_SELECTOR, 'a, button')
                    for link in links:
                        text = link.text.lower()
                        if any(w in text for w in ['se connecter', 'connexion', 'identifiant',
                                'mon espace', 'espace personnel']):
                            if link.is_displayed():
                                login_btn = link
                                break
                except Exception:
                    pass

            if login_btn:
                try:
                    driver.execute_script("arguments[0].click();", login_btn)
                except Exception:
                    login_btn.click()
                time.sleep(random.uniform(3.0, 5.0))

            # Maintenant on devrait etre sur la page d'authentification
            # Chercher le champ identifiant (email ou numero de PE)
            id_field = None
            for sel in ['input[name="j_username"]', 'input[name="username"]', 'input[name="email"]',
                        'input[type="email"]', 'input[id*="identifiant"]', 'input[id*="username"]',
                        'input#peConnect-identifiant', '#identifiant']:
                try:
                    field = driver.find_element(By.CSS_SELECTOR, sel)
                    if field.is_displayed():
                        id_field = field
                        break
                except Exception:
                    continue

            if not id_field:
                logger.error("France Travail auto-login: champ identifiant non trouve")
                self.browser.screenshot(f"ft_login_noid_{int(time.time())}")
                return False

            id_field.clear()
            self._human_type(id_field, email)
            time.sleep(random.uniform(0.5, 1.0))

            # Chercher le champ mot de passe
            pwd_field = None
            for sel in ['input[name="j_password"]', 'input[name="password"]', 'input[type="password"]',
                        'input[id*="password"]', '#password']:
                try:
                    field = driver.find_element(By.CSS_SELECTOR, sel)
                    if field.is_displayed():
                        pwd_field = field
                        break
                except Exception:
                    continue

            if not pwd_field:
                # Formulaire en 2 etapes - soumettre l'email d'abord
                try:
                    submit = driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]')
                    submit.click()
                    time.sleep(random.uniform(2.0, 3.5))
                except Exception:
                    id_field.send_keys(Keys.RETURN)
                    time.sleep(random.uniform(2.0, 3.5))

                for sel in ['input[name="j_password"]', 'input[name="password"]', 'input[type="password"]']:
                    try:
                        field = driver.find_element(By.CSS_SELECTOR, sel)
                        if field.is_displayed():
                            pwd_field = field
                            break
                    except Exception:
                        continue

            if not pwd_field:
                logger.error("France Travail auto-login: champ mot de passe non trouve")
                self.browser.screenshot(f"ft_login_nopwd_{int(time.time())}")
                return False

            pwd_field.clear()
            self._human_type(pwd_field, password)
            time.sleep(random.uniform(0.5, 1.0))

            # Soumettre
            try:
                submit = driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]')
                submit.click()
            except Exception:
                pwd_field.send_keys(Keys.RETURN)

            time.sleep(random.uniform(4.0, 6.0))

            # Verifier le succes du login
            current_url = driver.current_url
            if 'espacepersonnel' in current_url or 'tableau-de-bord' in current_url:
                logger.info(f"France Travail auto-login: SUCCES ({current_url})")
                return True

            # Verifier les indicateurs dans le header
            try:
                page_text = driver.find_element(By.TAG_NAME, 'body').text.lower()
                if any(w in page_text for w in ['déconnexion', 'deconnexion', 'mon espace',
                    'tableau de bord', 'mes candidatures']):
                    logger.info("France Travail auto-login: SUCCES (indicateurs detectes)")
                    return True
                if any(w in page_text for w in ['identifiant ou mot de passe incorrect',
                    'erreur', 'invalide']):
                    logger.error("France Travail auto-login: identifiants incorrects")
                    return False
            except Exception:
                pass

            logger.warning("France Travail auto-login: resultat incertain")
            self.browser.screenshot(f"ft_login_uncertain_{int(time.time())}")
            return False

        except Exception as e:
            logger.error(f"France Travail auto-login: erreur: {e}")
            self.browser.screenshot(f"ft_login_error_{int(time.time())}")
            return False

    def _send_email_application(self, to_email: str, offer: dict) -> bool:
        """Envoie une candidature par email (CV + lettre de motivation).
        
        Config attendue:
            profile.email: "votre@email.com"
            profile.email_password: "mot de passe app"
            profile.cv_path: "/path/to/cv.pdf"
        """
        smtp_config = self._config.get('smtp', {})
        from_email = self.email
        password = smtp_config.get('password', '')
        smtp_host = smtp_config.get('host', 'smtp-mail.outlook.com')
        smtp_port = smtp_config.get('port', 587)

        if not password:
            logger.warning(
                "Email SMTP: mot de passe manquant. "
                "Ajoute smtp.password dans config.yaml"
            )
            return False

        title = offer.get('title', 'Offre')
        company = offer.get('company', 'votre entreprise')

        try:
            # Generer la lettre de motivation
            letter = generate_cover_letter(offer, self.profile, ai_client=self.ai_client)

            # Construire l'email
            msg = MIMEMultipart()
            msg['From'] = from_email
            msg['To'] = to_email
            msg['Subject'] = f"Candidature alternance - {title} - {self.full_name}"

            # Corps de l'email
            body = f"""Bonjour,

{letter}

Cordialement,
{self.full_name}
{self.phone}
{self.email}
"""
            msg.attach(MIMEText(body, 'plain', 'utf-8'))

            # Joindre le CV
            cv_path = self.cv_path
            if cv_path and os.path.exists(cv_path):
                with open(cv_path, 'rb') as f:
                    part = MIMEBase('application', 'pdf')
                    part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header('Content-Disposition', 
                                    f'attachment; filename="CV_{self.full_name.replace(" ", "_")}.pdf"')
                    msg.attach(part)

            # Envoyer
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                server.login(from_email, password)
                server.send_message(msg)

            logger.info(f"Email de candidature envoye a {to_email} pour '{title}'")
            return True

        except Exception as e:
            logger.error(f"Erreur envoi email a {to_email}: {e}")
            return False

    def apply(self, offer: dict) -> ApplicationResult:
        """Tente de postuler sur France Travail"""
        url = offer.get('url', '')
        title = offer.get('title', '')
        company = offer.get('company', '')

        if not self.browser or not self.browser.driver:
            return ApplicationResult(
                status=ApplyStatus.FAILED,
                platform="francetravail",
                offer_title=title,
                company=company,
                url=url,
                details="Navigateur non disponible"
            )

        try:
            logger.info(f"France Travail Apply: ouverture de {url}")
            self.browser.get(url, wait=3)
            self.browser.accept_cookies()
            time.sleep(1)

            driver = self.browser.driver

            # Cliquer sur le bouton Postuler pour charger le dropdown
            apply_btn = self._find_apply_button(driver)
            if not apply_btn:
                return ApplicationResult(
                    status=ApplyStatus.SKIPPED,
                    platform="francetravail",
                    offer_title=title,
                    company=company,
                    url=url,
                    details="Bouton postuler non trouve"
                )

            try:
                driver.execute_script("arguments[0].click();", apply_btn)
            except Exception:
                apply_btn.click()
            time.sleep(3)

            # Extraire les infos de contact du dropdown
            contact_info = self._extract_contact(driver)

            if contact_info.get('email'):
                email = contact_info['email']
                logger.info(f"France Travail: email de contact trouve: {email}")
                
                # Tenter d'envoyer la candidature par email automatiquement
                sent = self._send_email_application(email, offer)
                if sent:
                    return ApplicationResult(
                        status=ApplyStatus.SUCCESS,
                        platform="francetravail",
                        offer_title=title,
                        company=company,
                        url=url,
                        contact_email=email,
                        details=f"Candidature envoyee par email a {email}"
                    )
                else:
                    return ApplicationResult(
                        status=ApplyStatus.EXTERNAL,
                        platform="francetravail",
                        offer_title=title,
                        company=company,
                        url=url,
                        contact_email=email,
                        details=f"Email trouve: {email} — envoi auto echoue, postuler manuellement"
                    )

            if contact_info.get('external_url'):
                ext_url = contact_info['external_url']
                logger.info(f"France Travail: redirection externe vers {ext_url}")
                return ApplicationResult(
                    status=ApplyStatus.EXTERNAL,
                    platform="francetravail",
                    offer_title=title,
                    company=company,
                    url=url,
                    external_url=ext_url,
                    details=f"Lien externe: {ext_url}"
                )

            if contact_info.get('login_required') and not self._login_attempted:
                # Tenter l'auto-login puis re-essayer
                logger.info("France Travail: login requis — tentative d'auto-login...")
                self._login_attempted = True
                login_ok = self._login(driver)
                if login_ok:
                    logger.info("France Travail: auto-login REUSSI — re-essai de la candidature")
                    # Recursion: re-essayer la candidature
                    return self.apply(offer)
                else:
                    return ApplicationResult(
                        status=ApplyStatus.LOGIN_REQUIRED,
                        platform="francetravail",
                        offer_title=title,
                        company=company,
                        url=url,
                        details="Connexion requise — auto-login echoue"
                    )

            return ApplicationResult(
                status=ApplyStatus.SKIPPED,
                platform="francetravail",
                offer_title=title,
                company=company,
                url=url,
                details="Pas d'info de contact trouvee"
            )

        except Exception as e:
            logger.error(f"France Travail Apply: erreur pour '{title}': {e}")
            return ApplicationResult(
                status=ApplyStatus.FAILED,
                platform="francetravail",
                offer_title=title,
                company=company,
                url=url,
                details=str(e)
            )

    def _find_apply_button(self, driver) -> object | None:
        """Trouve le bouton Postuler"""
        selectors = [
            '#detail-apply',
            'a[id="detail-apply"]',
            'a.apply-btn',
            'button.apply-btn',
        ]
        for sel in selectors:
            try:
                elem = driver.find_element(By.CSS_SELECTOR, sel)
                if elem.is_displayed():
                    return elem
            except Exception:
                continue

        try:
            links = driver.find_elements(By.CSS_SELECTOR, 'a, button')
            for link in links:
                text = link.text.strip().lower()
                if text == 'postuler':
                    return link
        except Exception:
            pass
        return None

    def _extract_contact(self, driver) -> dict:
        """Extrait les infos de contact du dropdown Postuler"""
        result = {
            'email': '',
            'external_url': '',
            'phone': '',
            'login_required': False
        }

        try:
            contact_zone = driver.find_elements(By.CSS_SELECTOR,
                '#contactZone, .dropdown-apply, .dropdown-blocs-contact')

            if not contact_zone:
                contact_zone = driver.find_elements(By.CSS_SELECTOR,
                    '[class*="contact"], [class*="postuler"]')

            for zone in contact_zone:
                text = zone.text
                html = zone.get_attribute('innerHTML') or ""

                emails = re.findall(r'[\w.+-]+@[\w-]+\.[\w.-]+', text + html)
                if emails:
                    result['email'] = emails[0]

                links = zone.find_elements(By.CSS_SELECTOR, 'a[href]')
                for link in links:
                    href = link.get_attribute('href') or ""
                    if href and 'francetravail.fr' not in href and href.startswith('http'):
                        result['external_url'] = href
                    if 'authentification' in href or 'connect' in href.lower():
                        result['login_required'] = True

                phones = re.findall(r'(?:\+33|0)\s*[1-9][\s.-]*(?:\d[\s.-]*){8}', text)
                if phones:
                    result['phone'] = phones[0]

        except Exception as e:
            logger.debug(f"France Travail: erreur extraction contact: {e}")

        return result

    def _human_type(self, element, text: str):
        """Tape le texte caractere par caractere avec delai humain"""
        for char in text:
            element.send_keys(char)
            time.sleep(random.uniform(0.03, 0.12))
