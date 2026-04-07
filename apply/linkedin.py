"""
Candidature automatique sur LinkedIn via Easy Apply.
LinkedIn utilise un formulaire modal multi-etapes (nom, email, CV, questions).
Necessite une session active (cookies importes).

IMPORTANT: config.yaml doit avoir linkedin.easy_apply_only: true
pour ne postuler qu'aux offres "Candidature simplifiee" (pas de redirection externe).
"""

from .base import BaseApplicator, ApplicationResult, ApplyStatus
from .motivation import generate_cover_letter
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
import time
import random
import os
import logging

logger = logging.getLogger("job-agent")


class LinkedInApplicator(BaseApplicator):
    """Candidature auto sur LinkedIn via Easy Apply.
    
    LinkedIn Easy Apply = formulaire modal multi-etapes:
    1. Coordonnees (pre-rempli si connecte)
    2. CV upload
    3. Questions supplementaires (optionnel)
    4. Lettre de motivation (optionnel)
    5. Review + Submit
    """

    def __init__(self, profile: dict, browser=None, requester=None, ai_client=None,
                 easy_apply_only: bool = True):
        super().__init__(profile, browser=browser, requester=requester, ai_client=ai_client)
        self.easy_apply_only = easy_apply_only

    def _is_logged_in(self, driver) -> bool:
        """Verifie si on est connecte a LinkedIn.
        
        Methode 1: Elements UI de session (nav, profil, feed)
        Methode 2: URL de redirection (authwall = pas connecte)
        Methode 3: Cookies de session (li_at = cookie principal)
        """
        try:
            # Methode 1: Verifier la redirection
            current_url = driver.current_url
            if any(w in current_url for w in ['/authwall', '/login', '/signup', '/uas/login']):
                logger.info("LinkedIn: PAS connecte (redirige vers login/authwall)")
                return False

            # Methode 2: Elements UI de session
            indicators = [
                '.global-nav__me',
                '.global-nav__me-photo',
                'a[href*="/in/"]',
                'a[href*="/feed/"]',
                '#global-nav',
                '.feed-identity-module',
                'img.global-nav__me-photo',
                '[data-control-name="identity_welcome_message"]',
                'a[href*="/messaging/"]',
                'a[href*="/notifications/"]',
            ]
            for sel in indicators:
                try:
                    elems = driver.find_elements(By.CSS_SELECTOR, sel)
                    if elems and any(e.is_displayed() for e in elems):
                        logger.info(f"LinkedIn: connecte (detecte via '{sel}')")
                        return True
                except Exception:
                    continue

            # Methode 3: Verifier le header pour "Rejoindre" / "S'identifier"
            try:
                for header_sel in ['header', 'nav', '.global-nav']:
                    try:
                        header_elem = driver.find_element(By.CSS_SELECTOR, header_sel)
                        header_text = header_elem.text.lower()
                        if any(w in header_text for w in [
                            's\'identifier', 'se connecter', 'rejoindre',
                            'sign in', 'join now'
                        ]):
                            logger.info("LinkedIn: PAS connecte (bouton 'S'identifier' visible)")
                            return False
                        if any(w in header_text for w in [
                            'messagerie', 'notifications', 'messaging',
                            'mon réseau', 'emplois'
                        ]):
                            logger.info("LinkedIn: connecte (navigation connectee visible)")
                            return True
                        break
                    except Exception:
                        continue
            except Exception:
                pass

            # Methode 4: Cookie li_at (cookie d'authentification principal LinkedIn)
            try:
                cookies = driver.get_cookies()
                li_at = [c for c in cookies if c['name'] == 'li_at']
                if li_at:
                    logger.info("LinkedIn: cookie li_at present (probablement connecte)")
                    return True
                else:
                    logger.info("LinkedIn: pas de cookie li_at")
            except Exception:
                pass

            logger.warning("LinkedIn: impossible de confirmer la connexion")
            return False

        except Exception as e:
            logger.error(f"LinkedIn: erreur verification connexion: {e}")
            return False

    def apply(self, offer: dict) -> ApplicationResult:
        """Postule sur une offre LinkedIn via Easy Apply"""
        url = offer.get('url', '')
        title = offer.get('title', '')
        company = offer.get('company', '')

        if not self.browser or not self.browser.driver:
            return ApplicationResult(
                status=ApplyStatus.FAILED,
                platform="linkedin",
                offer_title=title,
                company=company,
                url=url,
                details="Navigateur non disponible"
            )

        try:
            logger.info(f"LinkedIn Apply: ouverture de {url}")
            self.browser.get(url, wait=3)
            self.browser.accept_cookies()
            time.sleep(1)

            driver = self.browser.driver

            # Verifier si on est connecte
            logged_in = self._is_logged_in(driver)
            if not logged_in:
                logger.warning(
                    "LinkedIn: PAS connecte au compte — candidature BLOQUEE. "
                    "Lance: python3 agent.py --import-cookies www.linkedin.com_cookies.txt"
                )
                self.browser.screenshot(f"linkedin_not_logged_{int(time.time())}")
                return ApplicationResult(
                    status=ApplyStatus.LOGIN_REQUIRED,
                    platform="linkedin",
                    offer_title=title,
                    company=company,
                    url=url,
                    details="Pas connecte au compte LinkedIn — candidature annulee"
                )

            logger.info("LinkedIn Apply: connecte au compte — candidature autorisee")

            # Chercher le bouton Easy Apply
            apply_btn = self._find_easy_apply_button(driver)
            if not apply_btn:
                # Verifier si c'est une candidature externe
                ext_btn = self._find_external_apply(driver)
                if ext_btn:
                    ext_url = ext_btn.get_attribute('href') or ""
                    if self.easy_apply_only:
                        return ApplicationResult(
                            status=ApplyStatus.EXTERNAL,
                            platform="linkedin",
                            offer_title=title,
                            company=company,
                            url=url,
                            external_url=ext_url,
                            details=f"Candidature externe (easy_apply_only=true): {ext_url}"
                        )
                    else:
                        return ApplicationResult(
                            status=ApplyStatus.EXTERNAL,
                            platform="linkedin",
                            offer_title=title,
                            company=company,
                            url=url,
                            external_url=ext_url,
                            details=f"Redirection externe: {ext_url}"
                        )

                # Verifier si deja postule
                if self._already_applied(driver):
                    return ApplicationResult(
                        status=ApplyStatus.SKIPPED,
                        platform="linkedin",
                        offer_title=title,
                        company=company,
                        url=url,
                        details="Deja postule a cette offre"
                    )

                self.browser.screenshot(f"linkedin_nobtn_{int(time.time())}")
                return ApplicationResult(
                    status=ApplyStatus.SKIPPED,
                    platform="linkedin",
                    offer_title=title,
                    company=company,
                    url=url,
                    details="Bouton Easy Apply non trouve"
                )

            # Cliquer sur Easy Apply
            try:
                driver.execute_script("arguments[0].click();", apply_btn)
            except Exception:
                apply_btn.click()
            time.sleep(2)

            # Attendre l'ouverture du modal
            modal_opened = self._wait_for_modal(driver)
            if not modal_opened:
                # Peut-etre redirige vers login
                if 'login' in driver.current_url.lower() or 'authwall' in driver.current_url.lower():
                    return ApplicationResult(
                        status=ApplyStatus.LOGIN_REQUIRED,
                        platform="linkedin",
                        offer_title=title,
                        company=company,
                        url=url,
                        details="Connexion LinkedIn requise pour Easy Apply"
                    )
                self.browser.screenshot(f"linkedin_nomodal_{int(time.time())}")
                return ApplicationResult(
                    status=ApplyStatus.FAILED,
                    platform="linkedin",
                    offer_title=title,
                    company=company,
                    url=url,
                    details="Modal Easy Apply non charge"
                )

            # Remplir le formulaire multi-etapes
            success = self._fill_multi_step_form(driver, offer)

            if success:
                verification = self._verify_submission(driver)

                if verification == "confirmed":
                    logger.info(f"LinkedIn Apply: candidature CONFIRMEE pour '{title}' @ {company}")
                    self.browser.screenshot(f"linkedin_ok_{int(time.time())}")
                    return ApplicationResult(
                        status=ApplyStatus.SUCCESS,
                        platform="linkedin",
                        offer_title=title,
                        company=company,
                        url=url,
                        details="Easy Apply envoye — confirmation detectee"
                    )
                elif verification == "error":
                    logger.warning(f"LinkedIn Apply: ERREUR post-soumission pour '{title}' @ {company}")
                    self.browser.screenshot(f"linkedin_error_{int(time.time())}")
                    return ApplicationResult(
                        status=ApplyStatus.FAILED,
                        platform="linkedin",
                        offer_title=title,
                        company=company,
                        url=url,
                        details="Formulaire soumis mais erreur detectee"
                    )
                else:
                    logger.warning(
                        f"LinkedIn Apply: formulaire soumis pour '{title}' @ {company} "
                        "mais pas de confirmation claire"
                    )
                    self.browser.screenshot(f"linkedin_uncertain_{int(time.time())}")
                    return ApplicationResult(
                        status=ApplyStatus.SUCCESS,
                        platform="linkedin",
                        offer_title=title,
                        company=company,
                        url=url,
                        details="Easy Apply envoye — pas de confirmation claire (verifier screenshot)"
                    )
            else:
                # Fermer le modal si encore ouvert pour ne pas bloquer la suite
                self._close_modal(driver)
                self.browser.screenshot(f"linkedin_fail_{int(time.time())}")
                return ApplicationResult(
                    status=ApplyStatus.FAILED,
                    platform="linkedin",
                    offer_title=title,
                    company=company,
                    url=url,
                    details="Echec remplissage formulaire Easy Apply"
                )

        except Exception as e:
            logger.error(f"LinkedIn Apply: erreur pour '{title}': {e}")
            try:
                self.browser.screenshot(f"linkedin_exception_{int(time.time())}")
            except Exception:
                pass
            return ApplicationResult(
                status=ApplyStatus.FAILED,
                platform="linkedin",
                offer_title=title,
                company=company,
                url=url,
                details=str(e)
            )

    def _find_easy_apply_button(self, driver) -> object | None:
        """Trouve le bouton 'Candidature simplifiee' / 'Easy Apply' de LinkedIn.
        
        LinkedIn utilise plusieurs variantes:
        - Bouton principal sur la page de l'offre
        - Bouton dans le panneau lateral (job detail pane)
        """
        selectors = [
            # Bouton Easy Apply principal
            'button.jobs-apply-button',
            'button[aria-label*="Candidature simplifi"]',
            'button[aria-label*="Easy Apply"]',
            'button[aria-label*="Postuler"]',
            '.jobs-apply-button--top-card',
            # Bouton dans le detail de l'offre
            '.jobs-unified-top-card button[aria-label*="Easy"]',
            '.jobs-unified-top-card button[aria-label*="simplifi"]',
            # Selecteurs generiques LinkedIn
            'button[data-control-name="jobdetails_topcard_inapply"]',
            '.jobs-s-apply button',
        ]
        for sel in selectors:
            try:
                elems = driver.find_elements(By.CSS_SELECTOR, sel)
                for elem in elems:
                    if elem.is_displayed():
                        text = elem.text.strip().lower()
                        # Verifier que c'est bien un bouton de candidature
                        if any(w in text for w in [
                            'candidature simplifi', 'easy apply', 'postuler',
                            'candidature facile'
                        ]):
                            return elem
                        # Bouton sans texte mais avec la bonne classe
                        if 'jobs-apply-button' in (elem.get_attribute('class') or ''):
                            return elem
            except Exception:
                continue

        # Fallback: chercher par texte dans tous les boutons
        try:
            buttons = driver.find_elements(By.CSS_SELECTOR, 'button')
            for btn in buttons:
                text = btn.text.strip().lower()
                if any(w in text for w in [
                    'candidature simplifi', 'easy apply'
                ]) and btn.is_displayed():
                    return btn
        except Exception:
            pass

        return None

    def _find_external_apply(self, driver) -> object | None:
        """Trouve le bouton 'Postuler' qui redirige vers un site externe"""
        try:
            buttons = driver.find_elements(By.CSS_SELECTOR, 'a.jobs-apply-button, a[data-control-name*="apply"]')
            for btn in buttons:
                if btn.is_displayed():
                    href = btn.get_attribute('href') or ""
                    if href and 'linkedin.com' not in href:
                        return btn
            # Fallback: bouton Postuler sans "simplifiee"
            buttons = driver.find_elements(By.CSS_SELECTOR, 'button, a')
            for btn in buttons:
                text = btn.text.strip().lower()
                if 'postuler' in text and 'simplifi' not in text and btn.is_displayed():
                    href = btn.get_attribute('href') or ""
                    if href and 'linkedin.com' not in href:
                        return btn
        except Exception:
            pass
        return None

    def _already_applied(self, driver) -> bool:
        """Detecte si on a deja postule a cette offre"""
        try:
            page_text = driver.page_source.lower()
            indicators = [
                'candidature envoyée',
                'candidature envoyee',
                'already applied',
                'applied',
                'vous avez postulé',
                'vous avez postule',
            ]
            # Chercher dans les badges/labels pres du bouton
            badge_selectors = [
                '.artdeco-inline-feedback',
                '.jobs-unified-top-card__applied-date',
                '.post-apply-timeline',
                'span[class*="applied"]',
            ]
            for sel in badge_selectors:
                try:
                    elems = driver.find_elements(By.CSS_SELECTOR, sel)
                    if elems and any(e.is_displayed() for e in elems):
                        logger.info(f"LinkedIn: deja postule (badge detecte via '{sel}')")
                        return True
                except Exception:
                    continue

            # Verifier dans le texte de la page
            for indicator in indicators:
                if indicator in page_text:
                    # Eviter les faux positifs (le mot dans la description de l'offre)
                    # Chercher specifiquement dans la zone du bouton
                    try:
                        top_card = driver.find_element(By.CSS_SELECTOR, 
                            '.jobs-unified-top-card, .jobs-details-top-card')
                        card_text = top_card.text.lower()
                        if indicator in card_text:
                            logger.info(f"LinkedIn: deja postule ('{indicator}' dans top card)")
                            return True
                    except Exception:
                        pass
        except Exception:
            pass
        return False

    def _wait_for_modal(self, driver, timeout: int = 10) -> bool:
        """Attend l'ouverture du modal Easy Apply LinkedIn.
        
        Le modal a la classe .jobs-easy-apply-modal ou .artdeco-modal
        et contient un formulaire.
        """
        try:
            WebDriverWait(driver, timeout).until(
                lambda d: d.find_elements(By.CSS_SELECTOR,
                    '.jobs-easy-apply-modal, '
                    '.jobs-easy-apply-content, '
                    '.artdeco-modal[role="dialog"], '
                    'div[data-test-modal-id="easy-apply-modal"], '
                    '.jobs-easy-apply-form-section__grouping'
                )
            )
            # Attendre que le contenu du modal charge
            time.sleep(1.5)
            return True
        except Exception:
            return False

    def _fill_multi_step_form(self, driver, offer: dict) -> bool:
        """Remplit le formulaire multi-etapes du modal Easy Apply LinkedIn.
        
        Chaque etape a un bouton 'Suivant' ou 'Envoyer la candidature'.
        On boucle jusqu'au submit final.
        """
        max_steps = 8  # LinkedIn peut avoir jusqu'a 7-8 etapes

        for step in range(max_steps):
            logger.debug(f"LinkedIn Apply: etape {step + 1}")
            time.sleep(random.uniform(1.5, 2.5))

            # Remplir les champs visibles de cette etape
            self._fill_current_step(driver, offer)

            # Upload CV si le champ est present
            self._upload_cv(driver)

            # Remplir la lettre de motivation si present
            self._fill_cover_letter(driver, offer)

            # Repondre aux questions supplementaires si presentes
            self._answer_additional_questions(driver)

            # Chercher le bouton Suivant ou Envoyer
            action = self._click_next_or_submit(driver)

            if action == "submitted":
                time.sleep(3)
                return True
            elif action == "next":
                time.sleep(2)
                continue
            elif action == "review":
                # Page de review avant soumission — cliquer sur Envoyer
                time.sleep(1.5)
                submitted = self._click_submit_on_review(driver)
                if submitted:
                    time.sleep(3)
                    return True
                else:
                    logger.warning("LinkedIn Apply: impossible de soumettre depuis la page de review")
                    break
            else:
                # Pas de bouton trouve — peut-etre stuck
                logger.warning(f"LinkedIn Apply: aucun bouton trouve a l'etape {step + 1}")
                break

        return False

    def _fill_current_step(self, driver, offer: dict):
        """Remplit les champs de l'etape courante du formulaire.
        
        LinkedIn pre-remplit souvent les champs si on est connecte.
        On verifie avant de remplir pour ne pas ecraser les valeurs.
        """
        # Email
        for sel in [
            'input[name*="email"]', 'input[type="email"]',
            'input[id*="email"]', 'input[autocomplete="email"]',
        ]:
            try:
                f = driver.find_element(By.CSS_SELECTOR, sel)
                if f.is_displayed() and not f.get_attribute('value'):
                    f.clear()
                    self._human_type(f, self.email)
                    logger.debug("LinkedIn Apply: email rempli")
                    break
            except Exception:
                continue

        # Telephone
        for sel in [
            'input[name*="phone"]', 'input[type="tel"]',
            'input[id*="phone"]', 'input[autocomplete="tel"]',
        ]:
            try:
                f = driver.find_element(By.CSS_SELECTOR, sel)
                if f.is_displayed() and not f.get_attribute('value'):
                    f.clear()
                    self._human_type(f, self.phone)
                    logger.debug("LinkedIn Apply: telephone rempli")
                    break
            except Exception:
                continue

        # Nom complet (rare si connecte)
        for sel in [
            'input[name*="name"]', 'input[id*="name"]',
            'input[autocomplete="name"]',
        ]:
            try:
                f = driver.find_element(By.CSS_SELECTOR, sel)
                if f.is_displayed() and not f.get_attribute('value'):
                    # Eviter les champs qui ne sont pas pour le nom (ex: company name)
                    label_text = self._get_field_label(driver, f).lower()
                    if any(w in label_text for w in ['nom', 'name', 'prénom', 'prenom']):
                        f.clear()
                        self._human_type(f, self.full_name)
                        logger.debug("LinkedIn Apply: nom rempli")
                        break
            except Exception:
                continue

        # Ville / Localisation (parfois demande)
        for sel in [
            'input[name*="city"]', 'input[name*="location"]',
            'input[id*="city"]', 'input[autocomplete="address-level2"]',
        ]:
            try:
                f = driver.find_element(By.CSS_SELECTOR, sel)
                if f.is_displayed() and not f.get_attribute('value'):
                    f.clear()
                    self._human_type(f, "Paris")
                    time.sleep(1)
                    # LinkedIn peut proposer des suggestions — selectionner la premiere
                    try:
                        suggestion = WebDriverWait(driver, 3).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR,
                                '.basic-typeahead__selectable, '
                                '[role="option"], '
                                '.search-typeahead-v2__hit'
                            ))
                        )
                        suggestion.click()
                    except Exception:
                        f.send_keys(Keys.RETURN)
                    logger.debug("LinkedIn Apply: ville remplie (Paris)")
                    break
            except Exception:
                continue

    def _upload_cv(self, driver):
        """Upload le CV si un champ file est present dans le modal"""
        cv = self.cv_path
        if not cv or not os.path.exists(cv):
            logger.debug("LinkedIn Apply: pas de CV ou fichier introuvable")
            return

        try:
            # LinkedIn met souvent le champ file dans un label
            file_inputs = driver.find_elements(By.CSS_SELECTOR,
                '.jobs-easy-apply-modal input[type="file"], '
                '.artdeco-modal input[type="file"], '
                'input[type="file"][name*="resume"], '
                'input[type="file"][name*="cv"], '
                'input[type="file"]'
            )
            for fi in file_inputs:
                try:
                    # Verifier si un CV est deja uploade
                    parent = fi.find_element(By.XPATH, '..')
                    parent_text = parent.text.lower()
                    if any(w in parent_text for w in ['cv', 'resume', 'curriculum']):
                        fi.send_keys(cv)
                        time.sleep(3)  # Attendre l'upload
                        logger.debug("LinkedIn Apply: CV uploade")
                        return
                except Exception:
                    pass

            # Fallback: premier input file dans le modal
            if file_inputs:
                file_inputs[0].send_keys(cv)
                time.sleep(3)
                logger.debug("LinkedIn Apply: CV uploade (fallback)")
        except Exception as e:
            logger.debug(f"LinkedIn Apply: erreur upload CV — {e}")

    def _fill_cover_letter(self, driver, offer: dict):
        """Remplit le champ lettre de motivation si present"""
        try:
            # LinkedIn peut avoir un textarea pour la lettre
            textareas = driver.find_elements(By.CSS_SELECTOR,
                '.jobs-easy-apply-modal textarea, '
                '.artdeco-modal textarea'
            )
            for ta in textareas:
                if ta.is_displayed() and not ta.get_attribute('value'):
                    label = self._get_field_label(driver, ta).lower()
                    if any(w in label for w in [
                        'lettre', 'motivation', 'cover letter', 'message',
                        'additional information', 'informations supplémentaires',
                        'informations supplementaires'
                    ]):
                        letter = generate_cover_letter(offer, self.profile, ai_client=self.ai_client)
                        ta.send_keys(letter)
                        logger.debug("LinkedIn Apply: lettre de motivation remplie")
                        return
        except Exception:
            pass

    def _answer_additional_questions(self, driver):
        """Repond aux questions supplementaires du formulaire LinkedIn.
        
        LinkedIn peut demander:
        - Nombre d'annees d'experience (input number)
        - Diplome le plus eleve (select/radio)
        - Autorisation de travail (radio yes/no)
        - Questions custom de l'employeur
        """
        try:
            # Questions avec input number (annees d'experience, etc.)
            number_inputs = driver.find_elements(By.CSS_SELECTOR,
                '.jobs-easy-apply-modal input[type="number"], '
                '.jobs-easy-apply-modal input[type="text"][id*="numeric"]'
            )
            for inp in number_inputs:
                if inp.is_displayed() and not inp.get_attribute('value'):
                    label = self._get_field_label(driver, inp).lower()
                    if any(w in label for w in ['expérience', 'experience', 'année', 'annee', 'years']):
                        inp.clear()
                        inp.send_keys("2")  # BTS = 2 ans d'etudes
                        logger.debug(f"LinkedIn Apply: experience remplie (2)")
                    elif any(w in label for w in ['salary', 'salaire', 'rémunération', 'remuneration']):
                        inp.clear()
                        inp.send_keys("900")  # Salaire alternance standard
                        logger.debug("LinkedIn Apply: salaire rempli (900)")
                    else:
                        # Valeur par defaut pour champs numeriques inconnus
                        inp.clear()
                        inp.send_keys("1")
                        logger.debug(f"LinkedIn Apply: champ numerique inconnu rempli (1): {label}")

            # Questions radio / checkbox (oui/non, autorisation de travail, etc.)
            fieldsets = driver.find_elements(By.CSS_SELECTOR,
                '.jobs-easy-apply-modal fieldset, '
                '.jobs-easy-apply-form-section__grouping'
            )
            for fieldset in fieldsets:
                try:
                    if not fieldset.is_displayed():
                        continue
                    legend_text = ""
                    try:
                        legend = fieldset.find_element(By.CSS_SELECTOR, 'legend, label, span')
                        legend_text = legend.text.lower()
                    except Exception:
                        pass

                    # Chercher les radios non cochees
                    radios = fieldset.find_elements(By.CSS_SELECTOR, 'input[type="radio"]')
                    if radios:
                        already_selected = any(r.is_selected() for r in radios)
                        if not already_selected:
                            # Repondre "Oui" par defaut pour les questions standard
                            for radio in radios:
                                try:
                                    radio_label = radio.find_element(By.XPATH, 
                                        'following-sibling::label | ../label | ../../label'
                                    ).text.lower()
                                except Exception:
                                    radio_label = ""

                                if any(w in radio_label for w in ['oui', 'yes']):
                                    driver.execute_script("arguments[0].click();", radio)
                                    logger.debug(f"LinkedIn Apply: radio 'Oui' selectionnee ({legend_text})")
                                    break
                            else:
                                # Aucun "Oui" trouve — selectionner le premier
                                if radios:
                                    driver.execute_script("arguments[0].click();", radios[0])
                                    logger.debug(f"LinkedIn Apply: premier radio selectionne ({legend_text})")

                except Exception:
                    continue

            # Selects (dropdown) — diplome, niveau d'etude, etc.
            selects = driver.find_elements(By.CSS_SELECTOR,
                '.jobs-easy-apply-modal select'
            )
            for select in selects:
                if select.is_displayed():
                    try:
                        from selenium.webdriver.support.ui import Select
                        sel_obj = Select(select)
                        # Si pas encore selectionne (premiere option vide)
                        current = sel_obj.first_selected_option.text.strip()
                        if not current or current.lower() in ['sélectionnez', 'select', '--', '']:
                            label = self._get_field_label(driver, select).lower()
                            options = [o.text.strip().lower() for o in sel_obj.options]

                            if any(w in label for w in ['diplôme', 'diplome', 'degree', 'education']):
                                # Chercher Bac+2 / BTS
                                for i, opt in enumerate(options):
                                    if any(w in opt for w in ['bac+2', 'bts', 'dut', 'associate']):
                                        sel_obj.select_by_index(i)
                                        logger.debug(f"LinkedIn Apply: diplome selectionne ({opt})")
                                        break
                            else:
                                # Selectionner la premiere option non vide
                                for i, opt in enumerate(options):
                                    if opt and opt not in ['sélectionnez', 'select', '--', '']:
                                        sel_obj.select_by_index(i)
                                        logger.debug(f"LinkedIn Apply: select rempli ({opt})")
                                        break
                    except Exception:
                        pass

        except Exception as e:
            logger.debug(f"LinkedIn Apply: erreur reponse questions: {e}")

    def _click_next_or_submit(self, driver) -> str:
        """Clique sur Suivant, Verifier ou Envoyer.
        
        Retourne:
            'submitted' — formulaire soumis
            'next' — passe a l'etape suivante  
            'review' — page de review (derniere etape avant submit)
            '' — aucun bouton trouve
        """
        try:
            # Chercher les boutons dans le modal
            buttons = driver.find_elements(By.CSS_SELECTOR,
                '.jobs-easy-apply-modal button, '
                '.artdeco-modal button, '
                '.jobs-easy-apply-footer button'
            )
            
            for btn in buttons:
                if not btn.is_displayed():
                    continue
                text = btn.text.strip().lower()
                aria_label = (btn.get_attribute('aria-label') or '').lower()
                combined = f"{text} {aria_label}"

                # Bouton de soumission finale
                if any(w in combined for w in [
                    'envoyer la candidature', 'envoyer ma candidature',
                    'submit application', 'send application',
                    'soumettre', 'envoyer'
                ]):
                    driver.execute_script("arguments[0].click();", btn)
                    logger.info("LinkedIn Apply: candidature envoyee")
                    return "submitted"

            # Bouton "Verifier" / "Review" (avant le submit final)
            for btn in buttons:
                if not btn.is_displayed():
                    continue
                text = btn.text.strip().lower()
                aria_label = (btn.get_attribute('aria-label') or '').lower()
                combined = f"{text} {aria_label}"

                if any(w in combined for w in [
                    'vérifier', 'verifier', 'review', 'réviser'
                ]):
                    driver.execute_script("arguments[0].click();", btn)
                    time.sleep(2)
                    logger.debug("LinkedIn Apply: page de review")
                    return "review"

            # Bouton "Suivant" / "Next"
            for btn in buttons:
                if not btn.is_displayed():
                    continue
                text = btn.text.strip().lower()
                aria_label = (btn.get_attribute('aria-label') or '').lower()
                combined = f"{text} {aria_label}"

                if any(w in combined for w in [
                    'suivant', 'next', 'continuer', 'continue'
                ]):
                    driver.execute_script("arguments[0].click();", btn)
                    logger.debug("LinkedIn Apply: etape suivante")
                    return "next"

        except Exception as e:
            logger.debug(f"LinkedIn Apply: erreur navigation boutons: {e}")
        return ""

    def _click_submit_on_review(self, driver) -> bool:
        """Sur la page de review, clique sur le bouton final 'Envoyer'"""
        try:
            time.sleep(1)
            buttons = driver.find_elements(By.CSS_SELECTOR,
                '.jobs-easy-apply-modal button, '
                '.artdeco-modal button'
            )
            for btn in buttons:
                if not btn.is_displayed():
                    continue
                text = btn.text.strip().lower()
                aria_label = (btn.get_attribute('aria-label') or '').lower()
                combined = f"{text} {aria_label}"

                if any(w in combined for w in [
                    'envoyer la candidature', 'envoyer ma candidature',
                    'submit application', 'send application',
                    'envoyer', 'soumettre'
                ]):
                    driver.execute_script("arguments[0].click();", btn)
                    time.sleep(3)
                    logger.info("LinkedIn Apply: candidature envoyee depuis review")
                    return True
        except Exception:
            pass
        return False

    def _close_modal(self, driver):
        """Ferme le modal Easy Apply s'il est encore ouvert"""
        try:
            # Bouton X de fermeture
            close_btns = driver.find_elements(By.CSS_SELECTOR,
                '.artdeco-modal__dismiss, '
                'button[aria-label="Dismiss"], '
                'button[aria-label="Fermer"], '
                '.jobs-easy-apply-modal button[aria-label*="close"], '
                '.artdeco-modal button[data-test-modal-close-btn]'
            )
            for btn in close_btns:
                if btn.is_displayed():
                    btn.click()
                    time.sleep(1)
                    # LinkedIn peut demander "Ignorer cette candidature?"
                    try:
                        discard_btn = driver.find_element(By.CSS_SELECTOR,
                            'button[data-test-dialog-primary-btn], '
                            'button[data-control-name="discard_application_confirm_btn"]'
                        )
                        if discard_btn.is_displayed():
                            discard_btn.click()
                            time.sleep(1)
                    except Exception:
                        pass
                    logger.debug("LinkedIn Apply: modal ferme")
                    return
        except Exception:
            pass

    def _verify_submission(self, driver, timeout: int = 5) -> str:
        """Verifie si la soumission LinkedIn a reussi.
        
        Retourne:
            "confirmed" — message de confirmation detecte
            "error" — message d'erreur detecte  
            "unknown" — rien de clair
        """
        try:
            time.sleep(2)

            page_text = driver.page_source.lower()

            # Indicateurs de CONFIRMATION LinkedIn
            confirmation_signals = [
                'candidature envoyée',
                'candidature envoyee',
                'votre candidature a été envoyée',
                'votre candidature a ete envoyee',
                'your application was sent',
                'application submitted',
                'successfully applied',
                'candidature soumise',
                'merci pour votre candidature',
            ]
            for signal in confirmation_signals:
                if signal in page_text:
                    logger.info(f"LinkedIn Apply: confirmation detectee — '{signal}'")
                    return "confirmed"

            # Elements CSS de confirmation LinkedIn
            confirm_selectors = [
                '.artdeco-inline-feedback--success',
                '.jobs-easy-apply-modal .artdeco-inline-feedback--success',
                '[data-test-post-apply]',
                '.post-apply-timeline',
                '.jpac-modal-content',  # Post-apply content
            ]
            for sel in confirm_selectors:
                try:
                    elems = driver.find_elements(By.CSS_SELECTOR, sel)
                    if elems and any(e.is_displayed() for e in elems):
                        logger.info(f"LinkedIn Apply: confirmation CSS detectee — '{sel}'")
                        return "confirmed"
                except Exception:
                    continue

            # Le modal s'est ferme = probable succes
            modal_gone = True
            for sel in ['.jobs-easy-apply-modal', '.jobs-easy-apply-content']:
                try:
                    elems = driver.find_elements(By.CSS_SELECTOR, sel)
                    if elems and any(e.is_displayed() for e in elems):
                        modal_gone = False
                        break
                except Exception:
                    continue

            if modal_gone:
                logger.info("LinkedIn Apply: modal ferme apres soumission (probable succes)")
                return "confirmed"

            # Indicateurs d'ERREUR
            error_signals = [
                'une erreur est survenue',
                'erreur lors de',
                'veuillez réessayer',
                'veuillez reessayer',
                'something went wrong',
                'please try again',
                'champ obligatoire',
                'required field',
                'champs requis',
            ]
            for signal in error_signals:
                if signal in page_text:
                    try:
                        body_text = driver.find_element(By.TAG_NAME, 'body').text.lower()
                        if signal in body_text:
                            logger.warning(f"LinkedIn Apply: erreur detectee — '{signal}'")
                            return "error"
                    except Exception:
                        pass

            # Erreur CSS LinkedIn
            error_selectors = [
                '.artdeco-inline-feedback--error',
                '.jobs-easy-apply-modal .artdeco-inline-feedback--error',
                '.form-error',
                '[data-test-form-element-error-message]',
            ]
            for sel in error_selectors:
                try:
                    elems = driver.find_elements(By.CSS_SELECTOR, sel)
                    visible_errors = [e for e in elems if e.is_displayed() and e.text.strip()]
                    if visible_errors:
                        error_text = visible_errors[0].text.strip()[:100]
                        logger.warning(f"LinkedIn Apply: erreur CSS — '{sel}': {error_text}")
                        return "error"
                except Exception:
                    continue

            return "unknown"

        except Exception as e:
            logger.warning(f"LinkedIn Apply: erreur verification post-soumission: {e}")
            return "unknown"

    def _get_field_label(self, driver, field_element) -> str:
        """Recupere le label associe a un champ de formulaire"""
        try:
            # Via attribut id + label[for]
            field_id = field_element.get_attribute('id')
            if field_id:
                try:
                    label = driver.find_element(By.CSS_SELECTOR, f'label[for="{field_id}"]')
                    return label.text.strip()
                except Exception:
                    pass

            # Via aria-label
            aria = field_element.get_attribute('aria-label')
            if aria:
                return aria

            # Via aria-labelledby
            labelled_by = field_element.get_attribute('aria-labelledby')
            if labelled_by:
                try:
                    label = driver.find_element(By.ID, labelled_by)
                    return label.text.strip()
                except Exception:
                    pass

            # Via placeholder
            placeholder = field_element.get_attribute('placeholder')
            if placeholder:
                return placeholder

            # Via parent label
            try:
                parent_label = field_element.find_element(By.XPATH, 'ancestor::label')
                return parent_label.text.strip()
            except Exception:
                pass

            # Via label frere precedent
            try:
                sibling = field_element.find_element(By.XPATH, 'preceding-sibling::label')
                return sibling.text.strip()
            except Exception:
                pass

        except Exception:
            pass
        return ""

    def _human_type(self, element, text: str):
        """Tape le texte caractere par caractere avec delai humain"""
        for char in text:
            element.send_keys(char)
            time.sleep(random.uniform(0.04, 0.12))
