"""
Dispatcher ATS externe — detecte le type d'ATS depuis l'URL
et route vers le bon module d'auto-apply.

ATS supportes:
- SuccessFactors (contactrh.com, successfactors.com, sapsf.com) -> Selenium
- SmartRecruiters (smartrecruiters.com) -> Selenium

ATS non supportes (retourne None):
- Workday (anti-bot agressif, compte requis)
- Oracle HCM / Taleo (equest.com, aplitrak.com -> redirect proxies)
- Sites custom (Thales, AXA, L'Oreal, etc.)
"""

from .ats.successfactors import SuccessFactorsApplicator, is_successfactors_url
from .ats.smartrecruiters import SmartRecruitersApplicator, is_smartrecruiters_url
import logging

logger = logging.getLogger("job-agent")

# ATS connus mais non supportes (juste pour le logging)
UNSUPPORTED_ATS = {
    'workday.com': 'Workday',
    'myworkdayjobs.com': 'Workday',
    'equest.com': 'eQuest (redirect proxy)',
    'aplitrak.com': 'Aplitrak (redirect proxy)',
    'taleo.net': 'Oracle Taleo',
    'oracle.com/careers': 'Oracle HCM',
    'lever.co': 'Lever',
    'greenhouse.io': 'Greenhouse',
    'breezy.hr': 'Breezy HR',
    'recruitee.com': 'Recruitee',
    'ashbyhq.com': 'Ashby',
    'teamtailor.com': 'Teamtailor',
}


class ExternalATSDispatcher:
    """Detecte le type d'ATS et delegue l'auto-apply au bon module.

    Usage:
        dispatcher = ExternalATSDispatcher(profile, browser, ai_client)
        result = dispatcher.try_apply(url, offer)
        # result = {'success': True/False, 'details': '...'} ou None si ATS non supporte
    """

    def __init__(self, profile: dict, browser=None, ai_client=None):
        self.profile = profile
        self.browser = browser
        self.ai_client = ai_client

        # Instancier les applicators ATS
        self._sf = SuccessFactorsApplicator(profile, browser, ai_client)
        self._sr = SmartRecruitersApplicator(profile, browser, ai_client)

    def detect_ats(self, url: str) -> str:
        """Detecte le type d'ATS depuis l'URL.

        Returns:
            'successfactors', 'smartrecruiters', 'unsupported:{name}', ou 'unknown'
        """
        if not url:
            return 'unknown'

        url_lower = url.lower()

        if is_successfactors_url(url):
            return 'successfactors'

        if is_smartrecruiters_url(url):
            return 'smartrecruiters'

        # Checker les ATS non supportes
        for domain, name in UNSUPPORTED_ATS.items():
            if domain in url_lower:
                return f'unsupported:{name}'

        return 'unknown'

    def try_apply(self, url: str, offer: dict) -> dict:
        """Tente d'auto-apply sur un ATS externe.

        Args:
            url: URL externe vers l'ATS
            offer: dict de l'offre

        Returns:
            dict avec:
                success: bool — True si candidature envoyee
                details: str — message descriptif
                ats_type: str — type d'ATS detecte
                supported: bool — True si l'ATS est supporte (meme si echec)
        """
        ats_type = self.detect_ats(url)
        title = offer.get('title', '')
        company = offer.get('company', '')

        if ats_type == 'successfactors':
            if not self.browser:
                return {
                    'success': False,
                    'details': 'SuccessFactors: pas de browser disponible',
                    'ats_type': ats_type,
                    'supported': True,
                }
            logger.info(f"ATS detecte: SuccessFactors pour '{title}' @ {company}")
            result = self._sf.apply(url, offer)
            return {**result, 'ats_type': ats_type, 'supported': True}

        elif ats_type == 'smartrecruiters':
            if not self.browser:
                return {
                    'success': False,
                    'details': 'SmartRecruiters: pas de browser disponible',
                    'ats_type': ats_type,
                    'supported': True,
                }
            logger.info(f"ATS detecte: SmartRecruiters pour '{title}' @ {company}")
            result = self._sr.apply(url, offer)
            return {**result, 'ats_type': ats_type, 'supported': True}

        elif ats_type.startswith('unsupported:'):
            ats_name = ats_type.split(':', 1)[1]
            logger.debug(f"ATS non supporte: {ats_name} pour '{title}' @ {company}")
            return {
                'success': False,
                'details': f'ATS non supporte: {ats_name}',
                'ats_type': ats_type,
                'supported': False,
            }

        else:
            logger.debug(f"ATS inconnu pour '{title}' @ {company}: {url}")
            return {
                'success': False,
                'details': f'ATS inconnu: {url}',
                'ats_type': 'unknown',
                'supported': False,
            }
