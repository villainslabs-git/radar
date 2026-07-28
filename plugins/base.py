"""
Plugins Base - Re-export de Provider para que plugins no dependan de core directo si quieren
"""
from core.provider import Provider, FetchResult, RawOpportunity, NormalizedOpportunity
__all__ = ["Provider", "FetchResult", "RawOpportunity", "NormalizedOpportunity"]
