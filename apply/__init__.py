"""
Module apply - Candidature automatique
"""

from .base import BaseApplicator, ApplicationResult
from .hellowork import HelloWorkApplicator
from .francetravail import FranceTravailApplicator
from .indeed import IndeedApplicator
from .linkedin import LinkedInApplicator
from .wttj import WTTJApplicator
from .apec import APECApplicator
from .motivation import generate_cover_letter

__all__ = [
    'BaseApplicator', 'ApplicationResult',
    'HelloWorkApplicator', 'FranceTravailApplicator', 'IndeedApplicator',
    'LinkedInApplicator', 'WTTJApplicator', 'APECApplicator',
    'generate_cover_letter'
]
