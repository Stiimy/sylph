"""
Base pour le systeme de candidature automatique.
"""

from dataclasses import dataclass, field
from typing import Optional
from enum import Enum
import logging

logger = logging.getLogger("job-agent")


class ApplyStatus(Enum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"          # Deja postule ou pas de formulaire
    EXTERNAL = "external"        # Redirige vers un site externe
    CAPTCHA = "captcha"          # Bloque par captcha
    LOGIN_REQUIRED = "login"     # Connexion requise


@dataclass
class ApplicationResult:
    """Resultat d'une tentative de candidature"""
    status: ApplyStatus
    platform: str
    offer_title: str
    company: str
    url: str
    details: str = ""
    external_url: str = ""       # URL externe si redirection
    contact_email: str = ""      # Email de contact si trouve

    @property
    def success(self) -> bool:
        return self.status == ApplyStatus.SUCCESS

    def to_dict(self) -> dict:
        return {
            'status': self.status.value,
            'platform': self.platform,
            'offer_title': self.offer_title,
            'company': self.company,
            'url': self.url,
            'details': self.details,
            'external_url': self.external_url,
            'contact_email': self.contact_email
        }


class BaseApplicator:
    """Classe de base pour les applicators par plateforme"""

    def __init__(self, profile: dict, browser=None, requester=None, ai_client=None):
        self.profile = profile
        self.browser = browser
        self.requester = requester
        self.ai_client = ai_client
        self.name = self.__class__.__name__

    def apply(self, offer: dict) -> ApplicationResult:
        """Postule a une offre. A surcharger par chaque plateforme."""
        raise NotImplementedError

    def _get_profile_field(self, key: str, default: str = "") -> str:
        """Recupere un champ du profil"""
        return self.profile.get(key, default)

    @property
    def full_name(self) -> str:
        return self._get_profile_field('name', '')

    @property
    def first_name(self) -> str:
        name = self.full_name
        parts = name.split()
        # Format "NOM Prenom" -> prenom = Prenom
        return parts[-1] if len(parts) > 1 else parts[0] if parts else ""

    @property
    def last_name(self) -> str:
        name = self.full_name
        parts = name.split()
        # Format "NOM Prenom" -> nom = NOM
        return parts[0] if len(parts) > 1 else ""

    @property
    def email(self) -> str:
        return self._get_profile_field('email', '')

    @property
    def phone(self) -> str:
        return self._get_profile_field('phone', '')

    @property
    def cv_path(self) -> str:
        return self._get_profile_field('cv_path', '')
