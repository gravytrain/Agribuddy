"""Daystrom REST API client for Agribuddy.

Thin async HTTP client that wraps Daystrom's REST endpoints.
All plant/event/plot data lives in Daystrom (MariaDB); this
integration is just the HA-facing input layer.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)


class DaystromError(Exception):
    """General Daystrom API error."""


class DaystromClient:
    """Async client for the Daystrom farm data API."""

    def __init__(self, base_url: str, session: aiohttp.ClientSession, api_key: str = "") -> None:
        self._base_url = base_url.rstrip("/")
        self._session = session
        self._api_key = api_key

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._api_key:
            headers["X-API-Key"] = self._api_key
        return headers

    async def _request(
        self, method: str, path: str, json_data: dict | None = None, params: dict | None = None
    ) -> dict | None:
        url = f"{self._base_url}{path}"
        async with self._session.request(
            method, url, json=json_data, params=params, headers=self._headers()
        ) as resp:
            if resp.status == 204:
                return None
            if resp.status >= 400:
                text = await resp.text()
                raise DaystromError(f"Daystrom API error (HTTP {resp.status}): {text[:300]}")
            return await resp.json()

    async def health(self) -> dict:
        result = await self._request("GET", "/api/health")
        return result or {}

    # ── Plants ────────────────────────────────────────────────────────────

    async def get_plants(self, status: str = "active", plot_id: str = "") -> list[dict]:
        params: dict[str, str] = {}
        if status:
            params["status"] = status
        if plot_id:
            params["plotId"] = plot_id
        result = await self._request("GET", "/api/plants", params=params)
        return result.get("data", []) if result else []

    async def get_plant(self, plant_id: str) -> dict | None:
        try:
            result = await self._request("GET", f"/api/plants/{plant_id}")
            return result.get("data") if result else None
        except DaystromError:
            return None

    async def add_plant(
        self,
        name: str,
        species_id: str = "",
        start_type: str = "seed",
        start_date: str = "",
        location: str = "",
        plot_id: str = "",
        species_data: dict | None = None,
    ) -> dict:
        payload: dict[str, Any] = {
            "name": name,
            "startType": start_type,
            "startDate": start_date,
        }
        if species_id:
            payload["speciesId"] = species_id
        if location:
            payload["location"] = location
        if plot_id:
            payload["plotId"] = plot_id
        if species_data:
            payload["speciesData"] = species_data

        result = await self._request("POST", "/api/plants", json_data=payload)
        return result.get("data", {}) if result else {}

    async def update_plant(self, plant_id: str, **kwargs: Any) -> dict:
        payload: dict[str, Any] = {}
        key_map = {
            "name": "name",
            "start_type": "startType",
            "start_date": "startDate",
            "location": "location",
            "plot_id": "plotId",
            "status": "status",
            "species_data": "speciesData",
            "overrides": "overrides",
        }
        for py_key, api_key in key_map.items():
            if py_key in kwargs and kwargs[py_key] is not None:
                payload[api_key] = kwargs[py_key]

        result = await self._request("PATCH", f"/api/plants/{plant_id}", json_data=payload)
        return result.get("data", {}) if result else {}

    async def remove_plant(self, plant_id: str) -> bool:
        try:
            await self._request("DELETE", f"/api/plants/{plant_id}")
            return True
        except DaystromError:
            return False

    # ── Events ────────────────────────────────────────────────────────────

    async def log_event(
        self,
        plant_id: str,
        event_type: str,
        note: str = "",
        event_date: str | None = None,
        auto: bool = False,
    ) -> dict | None:
        payload: dict[str, Any] = {"type": event_type, "note": note, "auto": auto}
        if event_date:
            payload["date"] = event_date
        result = await self._request("POST", f"/api/plants/{plant_id}/events", json_data=payload)
        return result.get("data") if result else None

    async def remove_event(self, plant_id: str, event_id: str) -> bool:
        try:
            await self._request("DELETE", f"/api/plants/{plant_id}/events/{event_id}")
            return True
        except DaystromError:
            return False

    # ── Plots ─────────────────────────────────────────────────────────────

    async def get_plots(self) -> list[dict]:
        result = await self._request("GET", "/api/plots")
        return result.get("data", []) if result else []

    async def get_plot(self, plot_id: str) -> dict | None:
        try:
            result = await self._request("GET", f"/api/plots/{plot_id}")
            return result.get("data") if result else None
        except DaystromError:
            return None

    async def create_plot(self, name: str, description: str = "") -> dict:
        payload = {"name": name, "description": description}
        result = await self._request("POST", "/api/plots", json_data=payload)
        return result.get("data", {}) if result else {}

    async def update_plot(self, plot_id: str, name: str | None = None, description: str | None = None) -> dict:
        payload: dict[str, str] = {}
        if name is not None:
            payload["name"] = name
        if description is not None:
            payload["description"] = description
        result = await self._request("PATCH", f"/api/plots/{plot_id}", json_data=payload)
        return result.get("data", {}) if result else {}

    async def delete_plot(self, plot_id: str) -> bool:
        try:
            await self._request("DELETE", f"/api/plots/{plot_id}")
            return True
        except DaystromError:
            return False
