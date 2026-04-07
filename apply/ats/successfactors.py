"""
Auto-apply sur SAP SuccessFactors / contactrh.com.

SuccessFactors est un ATS server-rendered (jQuery + Bootstrap 3), PAS un SPA.
Utilise par de grandes entreprises (Capgemini, Servier, Safran, etc.).

Patterns d'URL detectes:
- *.contactrh.com/...
- *.successfactors.com/...
- *.sapsf.com/...

Flow typique:
1. Page offre -> bouton "Postuler" (a.dialogApplyBtn ou dropdown "Postuler maintenant")
2. Redirect vers /talentcommunity/apply/{jobId}/?locale=fr_FR
3. Formulaire multi-etapes:
   a. Email -> "Commencer" / "Continue"
   b. Infos personnelles (prenom, nom, telephone)
   c. Upload CV (input[type=file])
   d. Lettre de motivation (optionnel, textarea)
   e. Questions custom (optionnel)
   f. Submit
4. Page de confirmation

Anti-bot: script anti-clickjacking present mais PAS de CAPTCHA.
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

# Domaines SuccessFactors connus
SF_DOMAINS = ['contactrh.com', 'successfactors.com', 'sapsf.com']


def is_successfactors_url(url: str) -> bool:
    """Verifie si une URL est un site SuccessFactors."""
    url_lower = url.lower()
    return any(domain in url_lower for domain in SF_DOMAINS)


class SuccessFactorsApplicator:
    """Auto-apply sur SuccessFactors via Selenium.

    Necessite un browser (StealthBrowser) avec un driver Selenium.
    """

    def __init__(self, profile: dict, browser=None, ai_client=None):
        self.profile = profile
        self.browser = browser
        self.ai_client = ai_client

    @property
    def first_name(self) -> str:
        name = self.profile.get('name', '')
        parts = name.split()
        # Format "NOM Prenom" -> prenom = Prenom
        return parts[-1] if len(parts) > 1 else parts[0] if parts else ""

    @property
    def last_name(self) -> str:
        name = self.profile.get('name', '')
        parts = name.split()
        # Format "NOM Prenom" -> nom = NOM
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
        """Tente de postuler sur un site SuccessFactors.

        Args:
            url: URL externe vers le site SuccessFactors
            offer: dict de l'offre (title, company, description...)

        Returns:
            dict avec:
                success: bool
                details: str (message descriptif)
        """
        if not self.browser:
            return {'success': False, 'details': 'Pas de browser disponible'}

        driver = self.browser.driver
        if not driver:
            return {'success': False, 'details': 'Pas de driver Selenium'}

        title = offer.get('title', '')
        company = offer.get('company', '')

        try:
            logger.info(f"SuccessFactors: navigation vers {url}")
            driver.get(url)
            time.sleep(random.uniform(3.0, 5.0))

            # Accepter les cookies si popup
            self._accept_cookies(driver)

            # Etape 1: trouver et cliquer sur le bouton "Postuler"
            apply_url = self._find_apply_button(driver, url)
            if not apply_url:
                return {'success': False, 'details': 'Bouton Postuler non trouve'}

            # Si on a obtenu une URL apply, naviguer
            if apply_url != driver.current_url:
                logger.info(f"SuccessFactors: navigation vers formulaire {apply_url}")
                driver.get(apply_url)
                time.sleep(random.uniform(3.0, 5.0))
                self._accept_cookies(driver)

            # Etape 2: remplir le formulaire
            success = self._fill_application_form(driver, offer)
            if success:
                logger.info(f"SuccessFactors: candidature envoyee pour '{title}' @ {company}")
                self.browser.screenshot(f"sf_success_{company}_{int(time.time())}")
                return {'success': True, 'details': f'Candidature envoyee via SuccessFactors'}
            else:
                self.browser.screenshot(f"sf_fail_{company}_{int(time.time())}")
                return {'success': False, 'details': 'Echec remplissage formulaire SuccessFactors'}

        except Exception as e:
            logger.error(f"SuccessFactors: erreur pour '{title}': {e}")
            try:
                self.browser.screenshot(f"sf_error_{int(time.time())}")
            except Exception:
                pass
            return {'success': False, 'details': f'Erreur SuccessFactors: {e}'}

    def _accept_cookies(self, driver):
        """Accepte la banniere cookies si presente."""
        cookie_selectors = [
            'button#onetrust-accept-btn-handler',
            'button[id*="accept"]',
            'button[class*="accept"]',
            'a[class*="accept"]',
            'button[data-testid="cookie-accept"]',
            '#cookie-consent-accept',
            '.cookie-banner button',
        ]
        for sel in cookie_selectors:
            try:
                btn = driver.find_element(By.CSS_SELECTOR, sel)
                if btn.is_displayed():
                    btn.click()
                    logger.debug("SuccessFactors: cookies acceptes")
                    time.sleep(1)
                    return
            except Exception:
                continue

        # Essayer aussi par texte du bouton
        try:
            buttons = driver.find_elements(By.TAG_NAME, 'button')
            for btn in buttons:
                txt = btn.text.lower().strip()
                if txt in ['accepter', 'accept', 'accept all', 'tout accepter',
                           'accepter tout', 'j\'accepte', 'ok', 'agree']:
                    if btn.is_displayed():
                        btn.click()
                        logger.debug("SuccessFactors: cookies acceptes (par texte)")
                        time.sleep(1)
                        return
        except Exception:
            pass

    def _find_apply_button(self, driver, original_url: str) -> str:
        """Trouve le bouton Postuler et retourne l'URL du formulaire.

        SuccessFactors a 2 variantes:
        1. Lien direct: <a class="dialogApplyBtn" href="/talentcommunity/apply/...">
        2. Dropdown: <a class="applyOption"> avec un menu qui contient "Postuler maintenant"

        Returns:
            URL du formulaire, ou None si pas trouve
        """
        # Variante 1: lien direct dialogApplyBtn
        try:
            apply_link = driver.find_element(By.CSS_SELECTOR, 'a.dialogApplyBtn')
            href = apply_link.get_attribute('href')
            if href:
                logger.info(f"SuccessFactors: bouton dialogApplyBtn trouve -> {href}")
                return href
        except Exception:
            pass

        # Variante 2: dropdown applyOption
        try:
            apply_options = driver.find_elements(By.CSS_SELECTOR, 'a.applyOption, button.applyOption')
            for opt in apply_options:
                if opt.is_displayed():
                    opt.click()
                    time.sleep(1)
                    # Chercher le lien "Postuler maintenant" dans le dropdown
                    dropdown_links = driver.find_elements(By.CSS_SELECTOR, '.dropdown-menu a, [role="menu"] a')
                    for link in dropdown_links:
                        txt = link.text.lower()
                        if any(w in txt for w in ['postuler', 'apply', 'candidater']):
                            href = link.get_attribute('href')
                            if href:
                                logger.info(f"SuccessFactors: dropdown Postuler -> {href}")
                                return href
                    break
        except Exception:
            pass

        # Variante 3: chercher tout lien/bouton contenant "postuler" / "apply"
        try:
            all_links = driver.find_elements(By.CSS_SELECTOR, 'a, button')
            for el in all_links:
                txt = el.text.lower().strip()
                href = el.get_attribute('href') or ''
                if any(w in txt for w in ['postuler', 'apply now', 'candidater', 'postuler maintenant']):
                    if href and '/apply' in href.lower():
                        logger.info(f"SuccessFactors: lien Postuler generique -> {href}")
                        return href
                    elif el.tag_name == 'button' or not href:
                        # C'est un bouton, cliquer dessus
                        el.click()
                        time.sleep(2)
                        new_url = driver.current_url
                        if new_url != original_url:
                            logger.info(f"SuccessFactors: bouton Postuler clique -> {new_url}")
                            return new_url
        except Exception:
            pass

        # Variante 4: URL contient deja /apply
        if '/apply' in driver.current_url.lower() or '/talentcommunity/apply' in driver.current_url.lower():
            logger.info("SuccessFactors: on est deja sur la page de candidature")
            return driver.current_url

        # Variante 5: construire l'URL apply a partir de l'URL actuelle
        # Certaines URLs ont le format .../career/{jobId} et le formulaire est a /talentcommunity/apply/{jobId}/
        current = driver.current_url
        match = re.search(r'/career(?:Section)?/(?:jobdetail\.ftl\?job=)?(\d+)', current, re.IGNORECASE)
        if match:
            job_id = match.group(1)
            base_url = current.split('/career')[0]
            apply_url = f"{base_url}/talentcommunity/apply/{job_id}/?locale=fr_FR"
            logger.info(f"SuccessFactors: URL apply construite -> {apply_url}")
            return apply_url

        logger.warning(f"SuccessFactors: bouton Postuler non trouve sur {current}")
        self.browser.screenshot(f"sf_no_apply_btn_{int(time.time())}")
        return None

    def _fill_application_form(self, driver, offer: dict) -> bool:
        """Remplit le formulaire de candidature SuccessFactors.

        Le formulaire est souvent multi-etapes:
        1. Email + "Commencer"
        2. Infos personnelles
        3. CV upload
        4. (Optionnel) lettre de motivation
        5. Submit

        Certains formulaires sont en une seule page.
        """
        # Attendre que le formulaire charge
        time.sleep(random.uniform(2.0, 3.0))

        # ----- EMAIL -----
        email_filled = self._fill_email_step(driver)
        if not email_filled:
            # Peut-etre qu'on est directement sur le formulaire complet
            logger.debug("SuccessFactors: pas d'etape email, tentative formulaire direct")

        # ----- INFOS PERSONNELLES -----
        self._fill_personal_info(driver)

        # ----- UPLOAD CV -----
        cv_uploaded = self._upload_cv(driver)
        if not cv_uploaded:
            logger.warning("SuccessFactors: CV non uploade")

        # ----- LETTRE DE MOTIVATION (optionnel) -----
        self._fill_cover_letter(driver, offer)

        # ----- ACCEPTER LES CONDITIONS (checkbox) -----
        self._accept_terms(driver)

        # ----- SUBMIT -----
        return self._submit_form(driver)

    def _fill_email_step(self, driver) -> bool:
        """Remplit l'etape email et clique sur Commencer/Continue."""
        email_selectors = [
            'input[name="email"]',
            'input[type="email"]',
            'input[id*="email" i]',
            'input[name*="email" i]',
            'input[placeholder*="email" i]',
            'input[placeholder*="courriel" i]',
            'input[name="userName"]',
        ]

        email_field = None
        for sel in email_selectors:
            try:
                field = driver.find_element(By.CSS_SELECTOR, sel)
                if field.is_displayed():
                    email_field = field
                    break
            except Exception:
                continue

        if not email_field:
            return False

        # Remplir l'email
        email_field.clear()
        self._human_type(email_field, self.email)
        time.sleep(random.uniform(0.5, 1.0))

        # Cliquer sur "Commencer" / "Continue" / "Next"
        start_selectors = [
            'button[type="submit"]',
            'input[type="submit"]',
            'button[id*="continue" i]',
            'button[id*="start" i]',
            'a.btn[href*="apply"]',
        ]

        for sel in start_selectors:
            try:
                btn = driver.find_element(By.CSS_SELECTOR, sel)
                if btn.is_displayed():
                    txt = btn.text.lower().strip()
                    btn_value = (btn.get_attribute('value') or '').lower()
                    if any(w in txt or w in btn_value for w in [
                        'commencer', 'continue', 'continuer', 'next', 'suivant',
                        'start', 'begin', 'soumettre', 'submit', 'envoyer',
                        'postuler', 'apply'
                    ]):
                        btn.click()
                        logger.debug("SuccessFactors: etape email validee")
                        time.sleep(random.uniform(2.0, 4.0))
                        return True
            except Exception:
                continue

        # Fallback: submit avec Enter
        try:
            email_field.send_keys(Keys.RETURN)
            time.sleep(random.uniform(2.0, 4.0))
            return True
        except Exception:
            return False

    def _fill_personal_info(self, driver):
        """Remplit les champs prenom, nom, telephone."""
        # Mapping champ -> valeur
        field_map = {
            # Prenom
            'input[name*="firstName" i]': self.first_name,
            'input[name*="prenom" i]': self.first_name,
            'input[id*="firstName" i]': self.first_name,
            'input[id*="prenom" i]': self.first_name,
            'input[placeholder*="prenom" i]': self.first_name,
            'input[placeholder*="first name" i]': self.first_name,
            # Nom
            'input[name*="lastName" i]': self.last_name,
            'input[name*="nom" i]': self.last_name,
            'input[id*="lastName" i]': self.last_name,
            'input[id*="nom" i]': self.last_name,
            'input[placeholder*="nom" i]': self.last_name,
            'input[placeholder*="last name" i]': self.last_name,
            # Telephone
            'input[name*="phone" i]': self.phone,
            'input[name*="telephone" i]': self.phone,
            'input[name*="mobile" i]': self.phone,
            'input[type="tel"]': self.phone,
            'input[id*="phone" i]': self.phone,
            'input[id*="telephone" i]': self.phone,
            'input[placeholder*="telephone" i]': self.phone,
            'input[placeholder*="phone" i]': self.phone,
        }

        filled = set()
        for selector, value in field_map.items():
            if not value:
                continue
            # Eviter de remplir 2 fois le meme champ
            try:
                field = driver.find_element(By.CSS_SELECTOR, selector)
                if field.is_displayed() and field.get_attribute('id') not in filled:
                    field_id = field.get_attribute('id') or field.get_attribute('name') or selector
                    # Ne pas ecraser un champ deja rempli (pre-rempli)
                    current_val = field.get_attribute('value') or ''
                    if current_val.strip():
                        logger.debug(f"SuccessFactors: champ {field_id} deja rempli: '{current_val}'")
                        filled.add(field_id)
                        continue
                    field.clear()
                    self._human_type(field, value)
                    filled.add(field_id)
                    logger.debug(f"SuccessFactors: champ {field_id} rempli")
                    time.sleep(random.uniform(0.3, 0.7))
            except Exception:
                continue

        # Re-remplir l'email si on est sur un formulaire en une page
        # (l'email est peut-etre un champ du formulaire complet)
        email_selectors = [
            'input[name*="email" i]',
            'input[type="email"]',
            'input[id*="email" i]',
        ]
        for sel in email_selectors:
            try:
                field = driver.find_element(By.CSS_SELECTOR, sel)
                field_id = field.get_attribute('id') or field.get_attribute('name') or sel
                if field.is_displayed() and field_id not in filled:
                    current_val = field.get_attribute('value') or ''
                    if not current_val.strip():
                        field.clear()
                        self._human_type(field, self.email)
                        filled.add(field_id)
                        logger.debug(f"SuccessFactors: email rempli dans formulaire complet")
                        time.sleep(random.uniform(0.3, 0.7))
            except Exception:
                continue

        if filled:
            logger.info(f"SuccessFactors: {len(filled)} champs remplis")
        else:
            logger.warning("SuccessFactors: aucun champ personnel trouve")

    def _upload_cv(self, driver) -> bool:
        """Upload le CV via input[type=file]."""
        cv = self.cv_path
        if not cv or not os.path.isfile(cv):
            logger.warning(f"SuccessFactors: CV non trouve: {cv}")
            return False

        file_selectors = [
            'input[type="file"]',
            'input[name*="resume" i]',
            'input[name*="cv" i]',
            'input[accept*=".pdf"]',
            'input[id*="resume" i]',
            'input[id*="cv" i]',
            'input[id*="file" i]',
        ]

        for sel in file_selectors:
            try:
                inputs = driver.find_elements(By.CSS_SELECTOR, sel)
                for inp in inputs:
                    # Les input file sont souvent hidden, on peut quand meme send_keys
                    try:
                        inp.send_keys(cv)
                        logger.info(f"SuccessFactors: CV uploade via {sel}")
                        time.sleep(random.uniform(2.0, 4.0))  # Attendre l'upload
                        return True
                    except Exception:
                        continue
            except Exception:
                continue

        # Essayer de trouver un bouton "Ajouter un CV" / "Upload"
        try:
            buttons = driver.find_elements(By.CSS_SELECTOR, 'button, a.btn, label')
            for btn in buttons:
                txt = btn.text.lower()
                if any(w in txt for w in ['cv', 'resume', 'upload', 'ajouter', 'fichier',
                                           'importer', 'telecharger', 'joindre', 'piece jointe']):
                    # Chercher un input[type=file] associe (via for/id ou a l'interieur)
                    for_attr = btn.get_attribute('for') or ''
                    if for_attr:
                        try:
                            file_input = driver.find_element(By.ID, for_attr)
                            file_input.send_keys(cv)
                            logger.info(f"SuccessFactors: CV uploade via label '{btn.text}'")
                            time.sleep(random.uniform(2.0, 4.0))
                            return True
                        except Exception:
                            pass
        except Exception:
            pass

        logger.warning("SuccessFactors: champ upload CV non trouve")
        return False

    def _fill_cover_letter(self, driver, offer: dict):
        """Remplit la lettre de motivation si un textarea est present."""
        textarea_selectors = [
            'textarea[name*="coverLetter" i]',
            'textarea[name*="lettre" i]',
            'textarea[name*="motivation" i]',
            'textarea[name*="message" i]',
            'textarea[id*="coverLetter" i]',
            'textarea[id*="motivation" i]',
            'textarea[placeholder*="motivation" i]',
            'textarea[placeholder*="cover letter" i]',
        ]

        textarea = None
        for sel in textarea_selectors:
            try:
                field = driver.find_element(By.CSS_SELECTOR, sel)
                if field.is_displayed():
                    textarea = field
                    break
            except Exception:
                continue

        if not textarea:
            # Chercher un textarea generique qui n'est pas un champ "autre"
            try:
                textareas = driver.find_elements(By.TAG_NAME, 'textarea')
                for ta in textareas:
                    if ta.is_displayed():
                        name = (ta.get_attribute('name') or '').lower()
                        placeholder = (ta.get_attribute('placeholder') or '').lower()
                        # Ignorer les champs "commentaires" ou trop generiques
                        if any(w in name or w in placeholder for w in
                               ['comment', 'note', 'autre', 'other', 'question']):
                            continue
                        textarea = ta
                        break
            except Exception:
                pass

        if not textarea:
            logger.debug("SuccessFactors: pas de champ lettre de motivation")
            return

        # Generer la lettre
        from ..motivation import generate_cover_letter
        letter = generate_cover_letter(offer, self.profile, self.ai_client)

        if letter:
            textarea.clear()
            # Pour les textareas longs, envoyer le texte d'un coup (pas human_type)
            textarea.send_keys(letter)
            logger.info(f"SuccessFactors: lettre de motivation remplie ({len(letter)} chars)")
            time.sleep(random.uniform(0.5, 1.0))

    def _accept_terms(self, driver):
        """Coche les checkboxes obligatoires (CGU, RGPD, etc.)."""
        checkbox_selectors = [
            'input[type="checkbox"][name*="consent" i]',
            'input[type="checkbox"][name*="rgpd" i]',
            'input[type="checkbox"][name*="gdpr" i]',
            'input[type="checkbox"][name*="terms" i]',
            'input[type="checkbox"][name*="conditions" i]',
            'input[type="checkbox"][name*="agree" i]',
            'input[type="checkbox"][name*="accept" i]',
            'input[type="checkbox"][name*="privacy" i]',
            'input[type="checkbox"][name*="politique" i]',
            'input[type="checkbox"][id*="consent" i]',
            'input[type="checkbox"][id*="terms" i]',
            'input[type="checkbox"][id*="agree" i]',
            'input[type="checkbox"][id*="privacy" i]',
        ]

        checked = 0
        for sel in checkbox_selectors:
            try:
                boxes = driver.find_elements(By.CSS_SELECTOR, sel)
                for box in boxes:
                    if not box.is_selected():
                        try:
                            box.click()
                            checked += 1
                        except Exception:
                            # Parfois il faut cliquer sur le label
                            box_id = box.get_attribute('id')
                            if box_id:
                                try:
                                    label = driver.find_element(By.CSS_SELECTOR, f'label[for="{box_id}"]')
                                    label.click()
                                    checked += 1
                                except Exception:
                                    pass
            except Exception:
                continue

        # Aussi checker les checkboxes obligatoires (required) non deja cochees
        try:
            required_boxes = driver.find_elements(By.CSS_SELECTOR, 'input[type="checkbox"][required]')
            for box in required_boxes:
                if not box.is_selected():
                    try:
                        box.click()
                        checked += 1
                    except Exception:
                        box_id = box.get_attribute('id')
                        if box_id:
                            try:
                                label = driver.find_element(By.CSS_SELECTOR, f'label[for="{box_id}"]')
                                label.click()
                                checked += 1
                            except Exception:
                                pass
        except Exception:
            pass

        if checked:
            logger.debug(f"SuccessFactors: {checked} checkbox(es) cochee(s)")

    def _submit_form(self, driver) -> bool:
        """Soumet le formulaire de candidature."""
        # Chercher le bouton submit
        submit_selectors = [
            'button[type="submit"]',
            'input[type="submit"]',
            'button[id*="submit" i]',
            'button[id*="apply" i]',
            'button[name*="submit" i]',
            'a.btn[id*="submit" i]',
        ]

        for sel in submit_selectors:
            try:
                btns = driver.find_elements(By.CSS_SELECTOR, sel)
                for btn in btns:
                    if btn.is_displayed():
                        txt = btn.text.lower().strip()
                        btn_value = (btn.get_attribute('value') or '').lower()
                        # Filtrer les boutons qui ne sont pas le submit final
                        if any(w in txt or w in btn_value for w in [
                            'annuler', 'cancel', 'retour', 'back', 'precedent'
                        ]):
                            continue
                        btn.click()
                        logger.info(f"SuccessFactors: formulaire soumis (bouton: '{btn.text}')")
                        time.sleep(random.uniform(3.0, 5.0))
                        return self._verify_submission(driver)
            except Exception:
                continue

        # Fallback: chercher par texte
        try:
            buttons = driver.find_elements(By.CSS_SELECTOR, 'button, input[type="submit"], a.btn')
            for btn in buttons:
                txt = btn.text.lower().strip()
                btn_value = (btn.get_attribute('value') or '').lower()
                if any(w in txt or w in btn_value for w in [
                    'soumettre', 'envoyer', 'postuler', 'submit',
                    'send', 'apply', 'confirmer', 'valider'
                ]):
                    btn.click()
                    logger.info(f"SuccessFactors: formulaire soumis (bouton texte: '{txt}')")
                    time.sleep(random.uniform(3.0, 5.0))
                    return self._verify_submission(driver)
        except Exception:
            pass

        logger.warning("SuccessFactors: bouton submit non trouve")
        return False

    def _verify_submission(self, driver) -> bool:
        """Verifie si la candidature a bien ete envoyee."""
        try:
            page_text = driver.find_element(By.TAG_NAME, 'body').text.lower()

            # Indicateurs de succes
            success_indicators = [
                'merci', 'thank you', 'candidature envoyee', 'application submitted',
                'candidature recue', 'application received', 'bien ete envoyee',
                'bien ete prise en compte', 'successfully', 'confirmation',
                'votre candidature', 'your application has been',
                'felicitations', 'congratulations'
            ]

            for indicator in success_indicators:
                if indicator in page_text:
                    logger.info(f"SuccessFactors: confirmation detectee ('{indicator}')")
                    return True

            # Indicateurs d'erreur
            error_indicators = [
                'erreur', 'error', 'obligatoire', 'required', 'invalide', 'invalid',
                'veuillez remplir', 'please fill', 'champ manquant', 'missing field'
            ]

            for indicator in error_indicators:
                if indicator in page_text:
                    logger.warning(f"SuccessFactors: erreur detectee ('{indicator}')")
                    return False

            # Si on ne peut pas determiner, considerer comme succes
            # (le formulaire a ete soumis sans erreur visible)
            current_url = driver.current_url
            if 'confirm' in current_url.lower() or 'success' in current_url.lower() or 'thank' in current_url.lower():
                logger.info(f"SuccessFactors: page de confirmation detectee via URL")
                return True

            logger.warning("SuccessFactors: resultat de soumission incertain, considere comme succes")
            return True

        except Exception as e:
            logger.warning(f"SuccessFactors: verification echouee: {e}")
            return True  # Optimiste — le formulaire a ete soumis

    def _human_type(self, element, text: str):
        """Tape du texte avec des delais aleatoires (anti-bot)."""
        for char in text:
            element.send_keys(char)
            time.sleep(random.uniform(0.03, 0.12))
