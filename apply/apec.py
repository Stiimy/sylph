"""
Candidature sur APEC.

APEC ne permet PAS la candidature automatique:
- Compte APEC (Cadre/JD) requis pour postuler
- CGU interdisent explicitement l'automatisation
- Pas d'endpoint API pour les candidatures

Strategie: retourner EXTERNAL avec l'URL pour notification Telegram.
"""

from .base import BaseApplicator, ApplicationResult, ApplyStatus
import logging

logger = logging.getLogger("job-agent")


class APECApplicator(BaseApplicator):
    """Applicator APEC — retourne le lien pour candidature manuelle.

    Ne postule PAS automatiquement (interdit par CGU + auth requise).
    Retourne EXTERNAL avec l'URL pour que Telegram notifie l'utilisateur.
    """

    def __init__(self, profile: dict, browser=None, requester=None, ai_client=None, config=None):
        super().__init__(profile, browser, requester, ai_client)
        self._config = config or {}

    def apply(self, offer: dict) -> ApplicationResult:
        """Retourne EXTERNAL avec l'URL de l'offre APEC."""
        url = offer.get('url', '')
        title = offer.get('title', '')
        company = offer.get('company', '')

        return ApplicationResult(
            status=ApplyStatus.EXTERNAL,
            platform="apec",
            offer_title=title,
            company=company,
            url=url,
            external_url=url,
            details=f"APEC: postuler manuellement (compte requis) -> {url}"
        )
