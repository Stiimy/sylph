"""Plateforme APEC (apec.fr) - Recherche via API interne POST.

APEC est un site pour les cadres, mais il a aussi des offres d'alternance.
L'API de recherche est accessible sans authentification via un POST JSON.

Candidature automatique IMPOSSIBLE:
- Compte APEC requis pour postuler
- CGU interdisent explicitement l'automatisation
- Pas d'endpoint API pour les candidatures

Strategie: recherche + notification Telegram pour candidature manuelle.
"""

from .base import Platform, JobOffer
import requests
import logging
import time
import random

logger = logging.getLogger("job-agent")

SEARCH_URL = "https://www.apec.fr/cms/webservices/rechercheOffre"


class APECPlatform(Platform):
    """Recherche d'offres sur APEC via l'API interne POST.

    Pas besoin de Selenium — HTTP pur via l'API POST interne.
    """

    def __init__(self, config: dict, browser=None):
        super().__init__(config, driver=None)
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Referer': 'https://www.apec.fr/candidat/recherche-emploi.html/emploi',
            'Origin': 'https://www.apec.fr',
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/121.0.0.0 Safari/537.36'
            ),
        })

    def search(self, keywords: list, location: str) -> list:
        """Recherche des offres sur APEC via POST API.

        Parametres cles:
            - motsCles: mots-cles de recherche
            - lieux: code departement (["75"] pour Paris)
            - pagination: range=20, startIndex=0
        """
        offers = []

        # Mapping localisation vers code departement APEC
        dept_code = self._get_dept_code(location)

        for keyword in keywords:
            try:
                logger.info(f"APEC: recherche '{keyword}' a '{location}'")

                # 3 pages max = 60 offres
                for page in range(3):
                    try:
                        payload = {
                            'motsCles': keyword,
                            'lieux': [dept_code] if dept_code else [],
                            'typeClient': 'CADRE',
                            'sorts': [{'type': 'DATE', 'direction': 'DESCENDING'}],
                            'pagination': {
                                'range': 20,
                                'startIndex': page * 20,
                            },
                            'activeFiltre': True,
                            'pointGeolocDeReference': {'distance': 0},
                        }

                        resp = self.session.post(SEARCH_URL, json=payload, timeout=15)

                        if resp.status_code != 200:
                            logger.warning(f"APEC: HTTP {resp.status_code} pour '{keyword}' page {page}")
                            break

                        data = resp.json()
                        results = data.get('resultats', [])

                        if not results:
                            break

                        total = data.get('totalCount', 0)
                        logger.info(f"APEC: page {page+1} — {len(results)} resultats "
                                    f"(total: {total})")

                        for result in results:
                            try:
                                offer = self._parse_result(result)
                                if offer:
                                    offers.append(offer)
                            except Exception as e:
                                logger.debug(f"APEC: erreur parsing resultat: {e}")

                        # Pas de page suivante si on a tout
                        if (page + 1) * 20 >= total:
                            break

                        # Delai entre les pages
                        time.sleep(random.uniform(1.0, 2.0))

                    except requests.RequestException as e:
                        logger.error(f"APEC: erreur requete page {page}: {e}")
                        break

            except Exception as e:
                logger.error(f"APEC: erreur recherche '{keyword}': {e}")

        # Deduplication par URL
        seen = set()
        unique = []
        for o in offers:
            if o.url not in seen:
                seen.add(o.url)
                unique.append(o)

        logger.info(f"APEC: {len(unique)} offres uniques")
        return unique

    def _parse_result(self, result: dict) -> JobOffer | None:
        """Parse un resultat APEC en JobOffer"""
        title = result.get('intitule', '').strip()
        if not title:
            return None

        numero = result.get('numeroOffre', '')
        if not numero:
            return None

        url = f"https://www.apec.fr/candidat/recherche-emploi.html/emploi/detail-offre/{numero}"

        company = result.get('nomCommercial', '') or 'Non specifie'
        location = result.get('lieuTexte', '')
        salary = result.get('salaireTexte', '')
        description = result.get('texteOffre', '') or ''
        if len(description) > 500:
            description = description[:500] + '...'

        # Date de publication
        posted_date = None
        date_str = result.get('datePublication', '')
        if date_str:
            try:
                from datetime import datetime
                # Format ISO: 2026-03-25T10:00:00.000+0000
                posted_date = datetime.fromisoformat(date_str.replace('+0000', '+00:00'))
            except Exception:
                pass

        return JobOffer(
            title=title,
            company=company,
            location=location,
            description=description,
            url=url,
            platform="apec",
            salary=salary if salary else None,
            posted_date=posted_date,
        )

    def apply(self, offer: JobOffer, profile: dict) -> bool:
        """APEC necessite candidature manuelle (compte requis)"""
        logger.info(f"APEC: candidature manuelle requise pour '{offer.title}' -> {offer.url}")
        return False

    def _get_dept_code(self, location: str) -> str:
        """Convertit un nom de lieu en code departement APEC"""
        dept_map = {
            'paris': '75',
            'île-de-france': '75',
            'ile-de-france': '75',
            'lyon': '69',
            'marseille': '13',
            'toulouse': '31',
            'bordeaux': '33',
            'lille': '59',
            'nantes': '44',
            'strasbourg': '67',
            'france': '',
        }
        return dept_map.get(location.lower(), '')
