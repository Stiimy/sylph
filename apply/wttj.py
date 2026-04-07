"""
Candidature sur Welcome to the Jungle (WTTJ).

WTTJ ne permet PAS la candidature automatique directe:
- reCAPTCHA v3 sur le formulaire interne
- Auth requise pour postuler en interne

MAIS: 39/40 offres redirigent vers des ATS externes.
Strategie:
1. Extraire l'URL de candidature (interne WTTJ ou externe) via l'API
2. Si ATS externe supporte (SuccessFactors, SmartRecruiters) -> auto-apply
3. Sinon -> EXTERNAL pour notification Telegram
"""

from .base import BaseApplicator, ApplicationResult, ApplyStatus
from .external_ats import ExternalATSDispatcher
import requests
import logging
import re

logger = logging.getLogger("job-agent")

# API WTTJ pour les details d'une offre
WTTJ_API_BASE = "https://api.welcometothejungle.com/api/v1"


class WTTJApplicator(BaseApplicator):
    """Applicator WTTJ — extrait le lien de candidature et tente l'auto-apply ATS.

    Flow:
    1. Extraire l'apply_url via l'API WTTJ
    2. Si ATS externe -> passer au dispatcher ATS pour auto-apply
    3. Si auto-apply reussit -> retourner SUCCESS
    4. Sinon -> retourner EXTERNAL (notification Telegram)
    """

    def __init__(self, profile: dict, browser=None, requester=None, ai_client=None, config=None):
        super().__init__(profile, browser, requester, ai_client)
        self._config = config or {}
        self._session = requests.Session()
        self._session.headers.update({
            'Referer': 'https://www.welcometothejungle.com/',
            'Origin': 'https://www.welcometothejungle.com',
            'Accept': 'application/json',
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/121.0.0.0 Safari/537.36'
            ),
        })
        # Dispatcher ATS pour auto-apply sur sites externes
        self._ats_dispatcher = ExternalATSDispatcher(profile, browser, ai_client)

    def apply(self, offer: dict) -> ApplicationResult:
        """Extrait l'URL de candidature et tente l'auto-apply ATS.

        Si l'ATS est supporte et l'auto-apply reussit -> SUCCESS.
        Sinon -> EXTERNAL (notification Telegram).
        """
        url = offer.get('url', '')
        title = offer.get('title', '')
        company = offer.get('company', '')

        # Extraire org_slug et job_slug de l'URL
        # Format: /fr/companies/{org_slug}/jobs/{job_slug}
        match = re.search(r'/companies/([^/]+)/jobs/([^/?#]+)', url)
        if not match:
            return ApplicationResult(
                status=ApplyStatus.EXTERNAL,
                platform="wttj",
                offer_title=title,
                company=company,
                url=url,
                external_url=url,
                details=f"WTTJ: postuler manuellement -> {url}"
            )

        org_slug = match.group(1)
        job_slug = match.group(2)

        # Tenter de recuperer les details via l'API pour trouver apply_url
        apply_url = url  # fallback
        is_external = False
        try:
            api_url = f"{WTTJ_API_BASE}/organizations/{org_slug}/jobs/{job_slug}"
            resp = self._session.get(api_url, timeout=10)

            if resp.status_code == 200:
                data = resp.json()
                job_data = data.get('job', data)

                # Verifier si c'est un ATS externe
                ext_url = job_data.get('apply_url', '')
                if ext_url:
                    apply_url = ext_url
                    is_external = True
                    logger.info(f"WTTJ: ATS externe detecte pour '{title}': {ext_url}")
                else:
                    logger.info(f"WTTJ: candidature interne pour '{title}'")
            else:
                logger.debug(f"WTTJ API: HTTP {resp.status_code} pour {org_slug}/{job_slug}")

        except Exception as e:
            logger.debug(f"WTTJ API: erreur pour '{title}': {e}")

        # Si ATS externe detecte, tenter l'auto-apply
        if is_external and self.browser:
            try:
                ats_result = self._ats_dispatcher.try_apply(apply_url, offer)
                ats_type = ats_result.get('ats_type', 'unknown')

                if ats_result.get('success'):
                    logger.info(f"WTTJ: auto-apply ATS reussi ({ats_type}) pour '{title}' @ {company}")
                    return ApplicationResult(
                        status=ApplyStatus.SUCCESS,
                        platform="wttj",
                        offer_title=title,
                        company=company,
                        url=url,
                        external_url=apply_url,
                        details=f"WTTJ -> {ats_type}: candidature auto-envoyee"
                    )

                elif ats_result.get('supported'):
                    # ATS supporte mais echec -> logger et fallback EXTERNAL
                    logger.warning(
                        f"WTTJ: auto-apply ATS echoue ({ats_type}) pour '{title}': "
                        f"{ats_result.get('details', '')}"
                    )

                # Si ATS non supporte, on tombe dans le fallback EXTERNAL ci-dessous

            except Exception as e:
                logger.warning(f"WTTJ: erreur auto-apply ATS pour '{title}': {e}")

        # Fallback: retourner EXTERNAL pour notification Telegram
        return ApplicationResult(
            status=ApplyStatus.EXTERNAL,
            platform="wttj",
            offer_title=title,
            company=company,
            url=url,
            external_url=apply_url,
            details=f"WTTJ: postuler manuellement -> {apply_url}"
        )
