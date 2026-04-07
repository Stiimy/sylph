"""
Module ATS — Auto-apply sur les systemes de tracking de candidature externes.

Chaque sous-module gere un type d'ATS specifique:
- successfactors: SAP SuccessFactors / contactrh.com
- smartrecruiters: SmartRecruiters (API)
"""

from .successfactors import SuccessFactorsApplicator
from .smartrecruiters import SmartRecruitersApplicator

__all__ = ['SuccessFactorsApplicator', 'SmartRecruitersApplicator']
