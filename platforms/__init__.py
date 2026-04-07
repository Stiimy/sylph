"""Plateformes d'emploi"""

from .base import Platform, JobOffer
from .indeed import IndeedPlatform
from .hellowork import HelloWorkPlatform
from .francetravail import FranceTravailPlatform
from .linkedin import LinkedInPlatform
from .wttj import WTTJPlatform
from .apec import APECPlatform

__all__ = [
    'Platform',
    'JobOffer',
    'IndeedPlatform',
    'HelloWorkPlatform',
    'FranceTravailPlatform',
    'LinkedInPlatform',
    'WTTJPlatform',
    'APECPlatform',
]
