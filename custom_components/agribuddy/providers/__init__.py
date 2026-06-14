"""Plant reference data providers for Agribuddy.

Architecture:
    PlantProvider (abstract) → defines the canonical search/get interface
    CsvProvider             → searches the local plant-variety-database CSVs
    AiProvider              → fallback: generates plant data via LLM
    PlantResolver           → orchestrates: CSV first, AI fallback, caches results
"""

from .base import PlantProvider, PlantVariety, PlantingCalendar, CompanionPlant
from .csv_provider import CsvProvider
from .resolver import PlantResolver

__all__ = [
    "PlantProvider",
    "PlantVariety",
    "PlantingCalendar",
    "CompanionPlant",
    "CsvProvider",
    "PlantResolver",
]
