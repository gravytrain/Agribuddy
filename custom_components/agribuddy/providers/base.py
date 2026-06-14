"""Abstract base and canonical data classes for plant reference providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PlantVariety:
    """Canonical plant variety record. All providers return this shape."""

    # Identity
    variety_id: str
    name: str
    category: str
    scientific_name: str = ""
    description: str = ""
    image_url: str | None = None

    # Growing requirements
    days_to_harvest_min: int | None = None
    days_to_harvest_max: int | None = None
    days_to_germination_min: int | None = None
    days_to_germination_max: int | None = None
    sun_requirement: str = ""
    water_requirement: str = ""
    soil_type: str = ""
    soil_ph_min: float | None = None
    soil_ph_max: float | None = None
    plant_spacing: str = ""
    plant_height: str = ""
    usda_zone_min: int | None = None
    usda_zone_max: int | None = None
    growing_season: str = ""
    sowing_method: str = ""
    growing_difficulty: str = ""
    is_container_friendly: bool = False

    # Resistance & threats
    disease_resistance: str = ""
    common_pests: str = ""
    common_diseases: str = ""

    # Safety & ecology
    toxicity: dict[str, str] | None = None
    is_invasive: bool = False

    # Variety characteristics
    color: str = ""
    size: str = ""
    shape: str = ""
    flavor_profile: str = ""
    culinary_uses: str = ""
    is_heirloom: bool = False
    is_hybrid: bool = False

    # Metadata
    source: str = ""
    source_url: str | None = None
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a flat dictionary for storage/transport."""
        result: dict[str, Any] = {}
        for fld in self.__dataclass_fields__:
            result[fld] = getattr(self, fld)
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlantVariety:
        """Construct from a dictionary, ignoring unknown keys."""
        known_fields = set(cls.__dataclass_fields__.keys())
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)


@dataclass
class PlantingCalendar:
    """Zone-specific planting schedule for a variety."""

    variety_id: str
    usda_zone: int
    indoor_sow_start: str | None = None
    indoor_sow_end: str | None = None
    outdoor_transplant_start: str | None = None
    outdoor_transplant_end: str | None = None
    direct_sow_start: str | None = None
    direct_sow_end: str | None = None
    harvest_start: str | None = None
    harvest_end: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for fld in self.__dataclass_fields__:
            result[fld] = getattr(self, fld)
        return result


@dataclass
class CompanionPlant:
    """Companion planting relationship for a variety."""

    variety_id: str
    companion_name: str
    relationship: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for fld in self.__dataclass_fields__:
            result[fld] = getattr(self, fld)
        return result


class PlantProvider(ABC):
    """Abstract interface for plant reference data providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Short identifier for this provider (e.g., 'csv', 'ai', 'verdantly')."""

    @abstractmethod
    async def search(self, query: str) -> list[PlantVariety]:
        """Search for plant varieties matching the query string.

        Returns a list of PlantVariety objects ranked by relevance.
        """

    @abstractmethod
    async def get_variety(self, variety_id: str) -> PlantVariety | None:
        """Retrieve a specific variety by its ID. Returns None if not found."""

    async def get_planting_calendar(
        self, variety_id: str, usda_zone: int
    ) -> PlantingCalendar | None:
        """Get zone-specific planting calendar. Not all providers support this."""
        return None

    async def get_companions(self, variety_id: str) -> list[CompanionPlant]:
        """Get companion planting relationships. Not all providers support this."""
        return []
