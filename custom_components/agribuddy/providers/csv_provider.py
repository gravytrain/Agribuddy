"""CSV-based plant reference provider using the plant-variety-database.

Loads CSV data from the bundled data/ directory into memory at startup.
Provides fast local search with no API calls or rate limits.

Dataset: https://github.com/bripatch/plant-variety-database
License: CC BY 4.0
"""

from __future__ import annotations

import csv
import logging
import os
from pathlib import Path
from typing import Any

from .base import CompanionPlant, PlantingCalendar, PlantProvider, PlantVariety

_LOGGER = logging.getLogger(__name__)

# Default data path relative to this file's package
_DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _parse_range_int(value: str) -> tuple[int | None, int | None]:
    """Parse a range string like '70-75' or '72' into (min, max) ints."""
    if not value or not value.strip():
        return None, None
    value = value.strip()
    if "-" in value:
        parts = value.split("-", 1)
        try:
            return int(parts[0].strip()), int(parts[1].strip())
        except (ValueError, IndexError):
            pass
    try:
        v = int(value)
        return v, v
    except ValueError:
        return None, None


def _parse_range_float(value: str) -> tuple[float | None, float | None]:
    """Parse a range string like '6.2-6.8' into (min, max) floats."""
    if not value or not value.strip():
        return None, None
    value = value.strip()
    if "-" in value:
        parts = value.split("-", 1)
        try:
            return float(parts[0].strip()), float(parts[1].strip())
        except (ValueError, IndexError):
            pass
    try:
        v = float(value)
        return v, v
    except ValueError:
        return None, None


def _parse_bool(value: str) -> bool:
    """Parse 'true'/'false' string to bool."""
    return value.strip().lower() == "true"


def _safe_int(value: str) -> int | None:
    """Parse int or return None."""
    if not value or not value.strip():
        return None
    try:
        return int(value.strip())
    except ValueError:
        return None


def _row_to_variety(row: dict[str, str]) -> PlantVariety:
    """Convert one CSV row into a canonical PlantVariety."""
    harvest_min, harvest_max = _parse_range_int(row.get("days_to_harvest", ""))
    germ_min, germ_max = _parse_range_int(row.get("days_to_germination", ""))
    ph_min, ph_max = _parse_range_float(row.get("soil_ph", ""))

    return PlantVariety(
        variety_id=row.get("slug", ""),
        name=row.get("name", ""),
        category=row.get("category", ""),
        scientific_name=row.get("scientific_name", ""),
        description=row.get("description", ""),
        image_url=None,
        days_to_harvest_min=harvest_min,
        days_to_harvest_max=harvest_max,
        days_to_germination_min=germ_min,
        days_to_germination_max=germ_max,
        sun_requirement=row.get("sun_requirement", ""),
        water_requirement=row.get("water_requirement", ""),
        soil_type=row.get("soil_type", ""),
        soil_ph_min=ph_min,
        soil_ph_max=ph_max,
        plant_spacing=row.get("plant_spacing", ""),
        plant_height=row.get("plant_height", ""),
        usda_zone_min=_safe_int(row.get("usda_zone_min", "")),
        usda_zone_max=_safe_int(row.get("usda_zone_max", "")),
        growing_season=row.get("growing_season", ""),
        sowing_method=row.get("sowing_method", ""),
        growing_difficulty=row.get("growing_difficulty", ""),
        is_container_friendly=_parse_bool(row.get("is_container_friendly", "")),
        disease_resistance=row.get("disease_resistance", ""),
        common_pests=row.get("common_pests", ""),
        common_diseases=row.get("common_diseases", ""),
        toxicity=None,
        is_invasive=False,
        color=row.get("color", ""),
        size=row.get("size", ""),
        shape=row.get("shape", ""),
        flavor_profile=row.get("flavor_profile", ""),
        culinary_uses=row.get("culinary_uses", ""),
        is_heirloom=_parse_bool(row.get("is_heirloom", "")),
        is_hybrid=_parse_bool(row.get("is_hybrid", "")),
        source="csv",
        source_url=row.get("url", None),
        confidence=1.0,
    )


class CsvProvider(PlantProvider):
    """Plant reference data provider backed by local CSV files.

    Loads the entire dataset into memory (~2000 varieties). Searches are
    performed via simple substring matching on name, category, and
    scientific_name fields.
    """

    def __init__(self, data_dir: str | Path | None = None) -> None:
        self._data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
        self._varieties: dict[str, PlantVariety] = {}
        self._search_index: list[tuple[str, str]] = []
        self._calendar: dict[str, dict[int, PlantingCalendar]] = {}
        self._companions: dict[str, list[CompanionPlant]] = {}
        self._loaded = False

    @property
    def provider_name(self) -> str:
        return "csv"

    def load(self) -> None:
        """Load CSV data into memory. Call once at startup."""
        self._load_varieties()
        self._load_planting_calendar()
        self._load_companions()
        self._loaded = True
        _LOGGER.info(
            "CsvProvider loaded: %d varieties, %d calendar entries, %d companion entries",
            len(self._varieties),
            sum(len(v) for v in self._calendar.values()),
            sum(len(v) for v in self._companions.values()),
        )

    def _load_varieties(self) -> None:
        """Load varieties.csv into the in-memory index."""
        path = self._data_dir / "varieties.csv"
        if not path.exists():
            _LOGGER.warning("CsvProvider: varieties.csv not found at %s", path)
            return
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                variety = _row_to_variety(row)
                if not variety.variety_id:
                    continue
                self._varieties[variety.variety_id] = variety
                search_text = (
                    f"{variety.name} {variety.category} {variety.scientific_name}"
                ).lower()
                self._search_index.append((variety.variety_id, search_text))

    def _load_planting_calendar(self) -> None:
        """Load planting_calendar.csv."""
        path = self._data_dir / "planting_calendar.csv"
        if not path.exists():
            _LOGGER.debug("CsvProvider: planting_calendar.csv not found, skipping")
            return
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                slug = row.get("variety_slug", "")
                zone = _safe_int(row.get("usda_zone", ""))
                if not slug or zone is None:
                    continue
                cal = PlantingCalendar(
                    variety_id=slug,
                    usda_zone=zone,
                    indoor_sow_start=row.get("indoor_sow_start") or None,
                    indoor_sow_end=row.get("indoor_sow_end") or None,
                    outdoor_transplant_start=row.get("outdoor_transplant_start") or None,
                    outdoor_transplant_end=row.get("outdoor_transplant_end") or None,
                    direct_sow_start=row.get("direct_sow_start") or None,
                    direct_sow_end=row.get("direct_sow_end") or None,
                    harvest_start=row.get("harvest_start") or None,
                    harvest_end=row.get("harvest_end") or None,
                )
                self._calendar.setdefault(slug, {})[zone] = cal

    def _load_companions(self) -> None:
        """Load companion_plants.csv."""
        path = self._data_dir / "companion_plants.csv"
        if not path.exists():
            _LOGGER.debug("CsvProvider: companion_plants.csv not found, skipping")
            return
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                slug = row.get("variety_slug", "")
                if not slug:
                    continue
                comp = CompanionPlant(
                    variety_id=slug,
                    companion_name=row.get("companion_name", ""),
                    relationship=row.get("relationship", ""),
                    reason=row.get("reason", ""),
                )
                self._companions.setdefault(slug, []).append(comp)

    async def search(self, query: str) -> list[PlantVariety]:
        """Search varieties by substring match on name/category/scientific_name.

        Returns results sorted by relevance (exact name match first, then
        name-starts-with, then contains).
        """
        if not self._loaded:
            self.load()

        query_lower = query.lower().strip()
        if not query_lower:
            return []

        exact: list[PlantVariety] = []
        starts_with: list[PlantVariety] = []
        contains: list[PlantVariety] = []

        for variety_id, search_text in self._search_index:
            variety = self._varieties[variety_id]
            name_lower = variety.name.lower()

            if name_lower == query_lower:
                exact.append(variety)
            elif name_lower.startswith(query_lower):
                starts_with.append(variety)
            elif query_lower in search_text:
                contains.append(variety)

        results = exact + starts_with + contains
        return results[:25]

    async def get_variety(self, variety_id: str) -> PlantVariety | None:
        """Retrieve a variety by its slug."""
        if not self._loaded:
            self.load()
        return self._varieties.get(variety_id)

    async def get_planting_calendar(
        self, variety_id: str, usda_zone: int
    ) -> PlantingCalendar | None:
        """Get zone-specific planting calendar for a variety."""
        if not self._loaded:
            self.load()
        zone_map = self._calendar.get(variety_id)
        if zone_map is None:
            return None
        return zone_map.get(usda_zone)

    async def get_companions(self, variety_id: str) -> list[CompanionPlant]:
        """Get companion plants for a variety."""
        if not self._loaded:
            self.load()
        return self._companions.get(variety_id, [])
