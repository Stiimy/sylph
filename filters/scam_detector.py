"""
Filtre anti-arnaque pour les offres d'emploi
Protection des donnees personnelles de l'utilisateur

REGLE D'OR : Aucune info perso n'est envoyee sans validation complete.
"""

import re
import json
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum
from urllib.parse import urlparse
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("job-agent")

# Fichier de quarantaine
import os as _os
_BASE_DIR = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
QUARANTINE_FILE = _os.path.join(_BASE_DIR, "logs", "quarantine.json")
SENT_DATA_LOG = _os.path.join(_BASE_DIR, "logs", "data_sent.json")


class ScamLevel(Enum):
    SAFE = "safe"
    SUSPICIOUS = "suspicious"
    DANGEROUS = "dangerous"
    QUARANTINE = "quarantine"


@dataclass
class ScamCheckResult:
    level: ScamLevel
    reasons: List[str]
    score: int  # 0-100, plus haut = plus risque
    url_whitelisted: bool = False


class ScamDetector:
    """Detecteur d'arnaques avec whitelist stricte et protection des donnees"""

    def __init__(self, config: dict):
        self.config = config
        self.whitelisted_domains = config.get('whitelisted_domains', [])
        self.suspicious_keywords = config.get('suspicious_keywords', [])
        self.redflag_fields = config.get('redflag_fields', [])
        self.min_salary = config.get('min_salary', 500)
        self.max_salary = config.get('max_salary', 2000)
        self.blocked_email_domains = config.get('blocked_email_domains', [])
        self.min_domain_age_days = config.get('min_domain_age_days', 180)
        self.blacklisted_companies = [c.lower() for c in config.get('blacklisted_companies', [])]

        # Charger la quarantaine existante
        self.quarantine = self._load_quarantine()
        self.data_sent_log = self._load_data_log()

    # ============================================================
    # WHITELIST - Verification du domaine
    # ============================================================

    def is_url_whitelisted(self, url: str) -> bool:
        """Verifie si l'URL appartient a un domaine autorise"""
        if not url:
            return False
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            # Retirer le port si present
            domain = domain.split(':')[0]

            for allowed in self.whitelisted_domains:
                if domain == allowed or domain.endswith('.' + allowed):
                    return True

            return False
        except Exception:
            return False

    def get_domain(self, url: str) -> str:
        """Extrait le domaine d'une URL"""
        try:
            parsed = urlparse(url)
            return parsed.netloc.lower().split(':')[0]
        except Exception:
            return ""

    # ============================================================
    # VERIFICATION COMPLETE D'UNE OFFRE
    # ============================================================

    def check_offer(self, offer: dict) -> ScamCheckResult:
        """Analyse complete d'une offre - retourne le niveau de risque"""
        reasons = []
        score = 0
        url = offer.get('url', '')

        # 1. Verification whitelist
        url_whitelisted = self.is_url_whitelisted(url)
        if not url_whitelisted and url:
            domain = self.get_domain(url)
            reasons.append(f"Domaine NON whiteliste: {domain}")
            score += 40

        # 1b. Verification entreprise blacklistee (Aurlom, ISCOD, etc.)
        company = (offer.get('company', '') or '').lower()
        title_lower = (offer.get('title', '') or '').lower()
        for blacklisted in self.blacklisted_companies:
            if blacklisted in company or blacklisted in title_lower:
                reasons.append(f"Entreprise blacklistee: {blacklisted}")
                score += 100  # Score max = bloque direct
                break

        # 2. Verification mots-cles suspects
        text = (offer.get('description', '') + ' ' + offer.get('title', '')).lower()
        for keyword in self.suspicious_keywords:
            if keyword.lower() in text:
                reasons.append(f"Mot-cle suspect: '{keyword}'")
                score += 20

        # 3. Verification du salaire
        salary = self._extract_salary(text)
        if salary:
            if salary < self.min_salary:
                reasons.append(f"Salaire trop bas: {salary}EUR")
                score += 15
            if salary > self.max_salary:
                reasons.append(f"Salaire suspicieux pour alternance: {salary}EUR")
                score += 25

        # 4. Verification email recruteur
        company_email = offer.get('company_email', '')
        if company_email:
            email_domain = company_email.split('@')[-1].lower()
            if email_domain in self.blocked_email_domains:
                reasons.append(f"Email recruteur avec domaine gratuit: {email_domain}")
                score += 30

        # 5. Red flags dans la description
        for redflag in self.redflag_fields:
            if redflag.lower() in text:
                reasons.append(f"RED FLAG: demande de '{redflag}' dans l'offre")
                score += 50

        # 6. Verification demande d'argent
        money_patterns = [
            r'envoy[ez]+.*argent', r'frais.*inscription',
            r'payer.*pour', r'virement.*avant',
            r'achat.*obligatoire', r'investiss'
        ]
        for pattern in money_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                reasons.append(f"Demande d'argent detectee")
                score += 50
                break

        # 7. Verification WHOIS du domaine (si pas whiteliste)
        if not url_whitelisted and url:
            domain = self.get_domain(url)
            whois_safe = self._check_domain_whois(domain)
            if not whois_safe:
                reasons.append(f"Domaine trop recent ou introuvable: {domain}")
                score += 25

        # Determination du niveau
        if score >= 50:
            level = ScamLevel.DANGEROUS
        elif score >= 20:
            level = ScamLevel.SUSPICIOUS
        else:
            level = ScamLevel.SAFE

        # Si suspicious, mettre en quarantaine
        if level == ScamLevel.SUSPICIOUS:
            level = ScamLevel.QUARANTINE
            self._add_to_quarantine(offer, reasons, score)

        return ScamCheckResult(
            level=level,
            reasons=reasons,
            score=score,
            url_whitelisted=url_whitelisted
        )

    # ============================================================
    # DECISION : Peut-on envoyer les infos perso ?
    # ============================================================

    def can_send_personal_data(self, offer: dict) -> tuple[bool, str]:
        """
        Decide si on peut envoyer les infos perso pour cette offre.
        Retourne (True/False, raison)
        
        REGLE : On n'envoie JAMAIS les infos sur un site non whiteliste.
        """
        result = self.check_offer(offer)

        # JAMAIS si le site n'est pas whiteliste
        if not result.url_whitelisted:
            domain = self.get_domain(offer.get('url', ''))
            reason = f"BLOQUE: domaine '{domain}' pas dans la whitelist"
            logger.warning(reason)
            return False, reason

        # JAMAIS si dangerous
        if result.level == ScamLevel.DANGEROUS:
            reason = f"BLOQUE: offre dangereuse (score {result.score}) - {', '.join(result.reasons)}"
            logger.warning(reason)
            return False, reason

        # QUARANTAINE = attente validation manuelle
        if result.level == ScamLevel.QUARANTINE:
            reason = f"QUARANTAINE: offre suspecte, verification manuelle requise - {', '.join(result.reasons)}"
            logger.warning(reason)
            return False, reason

        # OK
        return True, "Offre validee"

    def log_data_sent(self, offer: dict, data_type: str):
        """Log quand des infos perso sont envoyees quelque part"""
        entry = {
            'timestamp': datetime.now().isoformat(),
            'platform': offer.get('platform', 'unknown'),
            'company': offer.get('company', 'unknown'),
            'url': offer.get('url', ''),
            'data_sent': data_type,
            'domain': self.get_domain(offer.get('url', ''))
        }
        self.data_sent_log.append(entry)
        self._save_data_log()
        logger.info(f"[DATA SENT] {data_type} -> {entry['domain']} ({entry['company']})")

    # ============================================================
    # VERIFICATION FORMULAIRE (red flags)
    # ============================================================

    def check_form_fields(self, field_names: List[str]) -> tuple[bool, List[str]]:
        """
        Verifie les champs d'un formulaire avant de le remplir.
        Retourne (safe, red_flags_trouves)
        """
        red_flags = []
        for field in field_names:
            field_lower = field.lower()
            for redflag in self.redflag_fields:
                if redflag.lower() in field_lower:
                    red_flags.append(f"Champ dangereux detecte: '{field}'")

        if red_flags:
            logger.warning(f"RED FLAGS dans le formulaire: {red_flags}")
            return False, red_flags

        return True, []

    # ============================================================
    # QUARANTAINE
    # ============================================================

    def _add_to_quarantine(self, offer: dict, reasons: List[str], score: int):
        """Ajoute une offre en quarantaine"""
        entry = {
            'timestamp': datetime.now().isoformat(),
            'title': offer.get('title', ''),
            'company': offer.get('company', ''),
            'url': offer.get('url', ''),
            'platform': offer.get('platform', ''),
            'reasons': reasons,
            'score': score,
            'status': 'pending'  # pending / approved / rejected
        }
        self.quarantine.append(entry)
        self._save_quarantine()
        logger.info(f"[QUARANTAINE] {entry['title']} @ {entry['company']} (score: {score})")

    def get_quarantine(self) -> List[dict]:
        """Retourne les offres en quarantaine"""
        return [q for q in self.quarantine if q.get('status') == 'pending']

    def approve_quarantine(self, index: int) -> bool:
        """Approuve une offre en quarantaine (apres verification manuelle)"""
        pending = self.get_quarantine()
        if 0 <= index < len(pending):
            pending[index]['status'] = 'approved'
            self._save_quarantine()
            logger.info(f"[QUARANTAINE] Approuvee: {pending[index]['title']}")
            return True
        return False

    def reject_quarantine(self, index: int) -> bool:
        """Rejette une offre en quarantaine"""
        pending = self.get_quarantine()
        if 0 <= index < len(pending):
            pending[index]['status'] = 'rejected'
            self._save_quarantine()
            logger.info(f"[QUARANTAINE] Rejetee: {pending[index]['title']}")
            return True
        return False

    # ============================================================
    # UTILITAIRES
    # ============================================================

    def _extract_salary(self, text: str) -> Optional[float]:
        """Extrait le salaire mensuel d'un texte"""
        patterns = [
            r'(\d{3,5})\s*(?:euros?|EUR)\s*(?:/|\s*par)\s*mois',
            r'(\d{3,5})\s*(?:euros?|EUR)\s*(?:/|\s*par)\s*an',
            r'remuneration[:\s]*(\d{3,5})',
            r'salaire[:\s]*(\d{3,5})',
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                salary = float(match.group(1))
                if 'an' in pattern:
                    salary /= 12
                return salary
        return None

    def _check_domain_whois(self, domain: str) -> bool:
        """Verifie l'age du domaine via WHOIS"""
        if not domain:
            return False

        # Les domaines whitelistes sont toujours OK
        if domain in self.whitelisted_domains:
            return True

        try:
            import whois
            w = whois.whois(domain)
            if w and w.creation_date:
                creation = w.creation_date
                if isinstance(creation, list):
                    creation = creation[0]
                age_days = (datetime.now() - creation).days
                if age_days < self.min_domain_age_days:
                    logger.warning(f"Domaine {domain} trop recent: {age_days} jours")
                    return False
                return True
        except Exception as e:
            logger.debug(f"WHOIS echoue pour {domain}: {e}")

        # Si WHOIS echoue, verifier DNS
        try:
            import dns.resolver
            dns.resolver.resolve(domain, 'A')
            return True
        except Exception:
            pass

        return False

    def _load_quarantine(self) -> list:
        """Charge la quarantaine depuis le fichier"""
        try:
            path = Path(QUARANTINE_FILE)
            if path.exists():
                with open(path) as f:
                    return json.load(f)
        except Exception:
            pass
        return []

    def _save_quarantine(self):
        """Sauvegarde la quarantaine"""
        try:
            path = Path(QUARANTINE_FILE)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'w') as f:
                json.dump(self.quarantine, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Erreur sauvegarde quarantaine: {e}")

    def _load_data_log(self) -> list:
        """Charge le log des donnees envoyees"""
        try:
            path = Path(SENT_DATA_LOG)
            if path.exists():
                with open(path) as f:
                    return json.load(f)
        except Exception:
            pass
        return []

    def _save_data_log(self):
        """Sauvegarde le log des donnees envoyees"""
        try:
            path = Path(SENT_DATA_LOG)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'w') as f:
                json.dump(self.data_sent_log, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Erreur sauvegarde data log: {e}")

    def is_safe(self, offer: dict) -> bool:
        """Retourne True si l'offre est safe"""
        result = self.check_offer(offer)
        return result.level == ScamLevel.SAFE


def create_detector(config: dict) -> ScamDetector:
    """Factory function"""
    return ScamDetector(config.get('scam_detection', {}))
