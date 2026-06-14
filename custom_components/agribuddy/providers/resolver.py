"""PlantResolver: orchestrates multiple providers with priority fallback.

Resolution strategy:
    1. Search CSV dataset first (fast, authoritative, free)
    2. If no results or variety not found, fall back to AI provider
    3. Cache resolved results so subsequent lookups are instant
"""

from __future__ import annotations

import logging
from typing import Any

from .base import CompanionPlant, PlantingCalendar, PlantProvider, PlantVariety

_LOGGER = logging.getLogger(__name__)


class PlantResolver:
    """Multi-provider plant data resolver with priority fallback and caching.

    Providers are tried in order. The first provider to return results wins.
    Resolved varieties are cached in memory for the session lifetime.
    """

    def __init__(self, providers: list[PlantProvider]) -> None:
        self._providers = providers
        self._variety_cache: dict[str, PlantVariety] = {}

    @property
    def provider_names(self) -> list[str]:
        """List registered provider names in priority order."""
        return [p.provider_name for p in self._providers]

    async def search(self, query: str) -> list[PlantVariety]:
        """Search across all providers in priority order.

        Returns results from the first provider that has matches.
        Does NOT merge across providers — the primary provider's results
        are authoritative when available.
        """
        for provider in self._providers:
            try:
                results = await provider.search(query)
                if results:
                    _LOGGER.debug(
                        "PlantResolver: search '%s' resolved by %s (%d results)",
                        query,
                        provider.provider_name,
                        len(results),
                    )
                    return results
            except Exception as err:
                _LOGGER.warning(
                    "PlantResolver: provider %s failed for search '%s': %s",
                    provider.provider_name,
                    query,
                    err,
                )
                continue

        _LOGGER.info("PlantResolver: no results for '%s' from any provider", query)
        return []

    async def get_variety(self, variety_id: str) -> PlantVariety | None:
        """Get a specific variety, checking cache first, then providers in order."""
        if variety_id in self._variety_cache:
            return self._variety_cache[variety_id]

        for provider in self._providers:
            try:
                result = await provider.get_variety(variety_id)
                if result:
                    self._variety_cache[variety_id] = result
                    _LOGGER.debug(
                        "PlantResolver: variety '%s' resolved by %s",
                        variety_id,
                        provider.provider_name,
                    )
                    return result
            except Exception as err:
                _LOGGER.warning(
                    "PlantResolver: provider %s failed for variety '%s': %s",
                    provider.provider_name,
                    variety_id,
                    err,
                )
                continue

        return None

    async def get_planting_calendar(
        self, variety_id: str, usda_zone: int
    ) -> PlantingCalendar | None:
        """Get planting calendar from the first provider that supports it."""
        for provider in self._providers:
            try:
                result = await provider.get_planting_calendar(variety_id, usda_zone)
                if result:
                    return result
            except Exception as err:
                _LOGGER.warning(
                    "PlantResolver: provider %s failed for calendar '%s' zone %d: %s",
                    provider.provider_name,
                    variety_id,
                    usda_zone,
                    err,
                )
                continue
        return None

    async def get_companions(self, variety_id: str) -> list[CompanionPlant]:
        """Get companion plants from the first provider that supports it."""
        for provider in self._providers:
            try:
                result = await provider.get_companions(variety_id)
                if result:
                    return result
            except Exception as err:
                _LOGGER.warning(
                    "PlantResolver: provider %s failed for companions '%s': %s",
                    provider.provider_name,
                    variety_id,
                    err,
                )
                continue
        return []

    def cache_variety(self, variety: PlantVariety) -> None:
        """Manually insert a variety into the cache (e.g., after AI resolution)."""
        self._variety_cache[variety.variety_id] = variety

    def clear_cache(self) -> None:
        """Clear the in-memory variety cache."""
        self._variety_cache.clear()
