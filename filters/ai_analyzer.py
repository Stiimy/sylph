"""
Analyseur IA des offres d'emploi.

Utilise Ollama pour:
- Detecter les ecoles/centres de formation deguises en recruteurs
- Evaluer la pertinence d'une offre par rapport au profil
- Identifier les red flags subtils qu'une blacklist ne peut pas choper

Fonctionne en complement du scam_detector (regles statiques).
Si Ollama n'est pas dispo, le pipeline continue sans l'IA.
"""

import logging
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger("job-agent")


@dataclass
class AIAnalysis:
    """Resultat de l'analyse IA d'une offre"""
    is_school: bool           # True si c'est probablement une ecole deguisee
    school_confidence: float  # 0.0 - 1.0
    school_name: str          # Nom de l'ecole detectee (si applicable)
    is_relevant: bool         # True si l'offre correspond au profil
    relevance_score: float    # 0.0 - 1.0
    red_flags: list           # Red flags detectes par l'IA
    summary: str              # Resume de l'analyse en 1-2 phrases
    raw_response: dict        # Reponse brute du modele


COMBINED_ANALYSIS_SYSTEM = """Tu evalues des offres d'alternance pour un candidat IT. Reponds UNIQUEMENT en JSON.

CANDIDAT: BTS CIEL option Cybersecurite. Cherche alternance Bac+3 en region parisienne (IDF).
Il peut occuper TOUS ces postes: technicien support, administrateur systeme, administrateur reseau, technicien helpdesk, technicien informatique, developpeur, devops, cybersecurite, SOC analyst, support IT, technicien systeme et reseau, administrateur infrastructure, support utilisateur, technicien bureautique.
Il ne veut PAS de poste de technicien de proximite / technicien informatique de proximite.
MEME si l'offre mentionne "ingenieur" ou "Bac+5", beaucoup d'alternances acceptent des Bac+3 en pratique.

PERTINENCE - donne un score entre 0.0 et 1.0:
- 0.7 a 1.0 = offre en alternance/apprentissage dans l'IT (informatique, reseau, systeme, dev, cyber, support, helpdesk, devops, cloud, data, infrastructure)
- 0.4 a 0.6 = offre IT mais doute sur le niveau ou la localisation
- 0.0 a 0.3 = PAS de l'IT (RH, commerce, finance, juridique, marketing) OU c'est un CDI/CDD/stage sans alternance

ECOLE DEGUISEE: reponds is_school=true UNIQUEMENT si l'entreprise est un centre de formation / ecole / academy qui publie l'offre pour recruter des etudiants dans son programme. Les grandes entreprises (Thales, Orange, Safran, STORENGY, LFB, Capgemini, AXA, EDF, ENGIE, etc.) ne sont JAMAIS des ecoles.

JSON:
{"is_school":false,"school_name":"","relevance":0.8,"reason":"alternance IT pertinente"}"""


class AIOfferAnalyzer:
    """Analyse les offres d'emploi avec un LLM via Ollama"""

    def __init__(self, ai_client):
        """
        Args:
            ai_client: Instance de OllamaClient (depuis utils.ai)
        """
        self.ai = ai_client

    def analyze_offer(self, offer: dict) -> Optional[AIAnalysis]:
        """Analyse combinee d'une offre: detection ecole + pertinence en 1 seul appel.
        
        Args:
            offer: dict avec au minimum 'title', 'company', 'description', 'url'
            
        Returns:
            AIAnalysis ou None si l'IA n'est pas dispo
        """
        if not self.ai:
            return None

        # Construire le texte de l'offre (reduit pour vitesse)
        offer_text = self._format_offer(offer)
        prompt = f"{offer_text}"

        result = self.ai.analyze_json(prompt, system=COMBINED_ANALYSIS_SYSTEM)
        if not result:
            return None

        # Parser le resultat combine
        is_school = result.get('is_school', False)
        school_name = result.get('school_name', '')
        relevance = float(result.get('relevance', 0.5))
        reason = result.get('reason', '')

        is_relevant = relevance >= 0.3
        red_flags = []
        if is_school:
            red_flags.append(f"Ecole deguisee: {school_name}")
        if not is_relevant:
            red_flags.append(f"Non pertinent: {reason}")

        summary = reason

        return AIAnalysis(
            is_school=is_school,
            school_confidence=0.9 if is_school else 0.0,
            school_name=school_name,
            is_relevant=is_relevant,
            relevance_score=relevance,
            red_flags=red_flags,
            summary=summary,
            raw_response=result
        )

    # Alias pour compatibilite
    analyze_offer_quick = analyze_offer

    def _format_offer(self, offer: dict) -> str:
        """Formate une offre en texte court pour le LLM"""
        parts = []
        parts.append(f"TITRE: {offer.get('title', 'Non specifie')}")
        parts.append(f"ENTREPRISE: {offer.get('company', 'Non specifie')}")

        location = offer.get('location', '')
        if location:
            parts.append(f"LIEU: {location}")

        description = offer.get('description', '')
        if description:
            # Limiter a 500 chars pour vitesse (le titre suffit souvent)
            if len(description) > 500:
                description = description[:500] + "..."
            parts.append(f"DESC: {description}")

        return "\n".join(parts)


def create_analyzer(ai_client) -> Optional[AIOfferAnalyzer]:
    """Factory function. Retourne None si pas de client IA."""
    if not ai_client:
        return None
    return AIOfferAnalyzer(ai_client)
