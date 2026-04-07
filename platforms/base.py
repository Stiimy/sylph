"""Module de base pour les plateformes"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from datetime import datetime


@dataclass
class JobOffer:
    """Represente une offre d'emploi"""
    title: str
    company: str
    location: str
    description: str
    url: str
    platform: str
    salary: Optional[str] = None
    company_email: Optional[str] = None
    posted_date: Optional[datetime] = None
    requirements: Optional[List[str]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'title': self.title,
            'company': self.company,
            'location': self.location,
            'description': self.description,
            'url': self.url,
            'platform': self.platform,
            'salary': self.salary,
            'company_email': self.company_email,
            'posted_date': self.posted_date.isoformat() if self.posted_date else None,
            'requirements': self.requirements or []
        }


class Platform(ABC):
    """Classe de base pour les plateformes d'emploi"""

    def __init__(self, config: dict, driver=None):
        self.config = config
        self.driver = driver
        self.name = self.__class__.__name__.replace('Platform', '').lower()

    @abstractmethod
    def search(self, keywords: List[str], location: str) -> List[JobOffer]:
        """Recherche des offres"""
        pass

    @abstractmethod
    def apply(self, offer: JobOffer, profile: dict) -> bool:
        """Postule a une offre"""
        pass

    def is_enabled(self) -> bool:
        """Verifie si la plateforme est activee"""
        return self.config.get('enabled', False)
