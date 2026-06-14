"""FarmOS JSON:API client for Agribuddy.

Handles OAuth2 authentication and CRUD operations for:
    - Taxonomy terms (plant_type vocabulary) — stores plant reference data
    - Plant assets — represents actual plantings
    - Logs — records events (seeding, observation, harvest, etc.)

Uses the password grant with client_id=farm (farmOS default consumer) for
first-party integration. Tokens auto-refresh when expired.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import aiohttp

from .providers.base import PlantVariety

_LOGGER = logging.getLogger(__name__)

TOKEN_EXPIRY_BUFFER = 30  # seconds before actual expiry to trigger refresh


class FarmOSAuthError(Exception):
    """Authentication with FarmOS failed."""


class FarmOSApiError(Exception):
    """General FarmOS API error."""


class FarmOSClient:
    """Async client for the FarmOS JSON:API.

    Manages OAuth2 token lifecycle and provides typed methods for
    plant-related operations.
    """

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        session: aiohttp.ClientSession,
        client_id: str = "farm",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._session = session
        self._client_id = client_id
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._token_expires_at: float = 0

    # ── OAuth2 Token Management ───────────────────────────────────────────────

    async def authenticate(self) -> None:
        """Obtain initial access token via password grant."""
        url = f"{self._base_url}/oauth/token"
        data = {
            "grant_type": "password",
            "username": self._username,
            "password": self._password,
            "client_id": self._client_id,
            "scope": "farm_manager",
        }
        async with self._session.post(url, data=data) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise FarmOSAuthError(
                    f"FarmOS auth failed (HTTP {resp.status}): {text[:200]}"
                )
            token_data = await resp.json()
            self._store_token(token_data)
        _LOGGER.info("FarmOS: authenticated successfully as '%s'", self._username)

    async def _ensure_token(self) -> None:
        """Ensure we have a valid access token, refreshing if needed."""
        if self._access_token and time.time() < self._token_expires_at:
            return
        if self._refresh_token:
            await self._refresh()
        else:
            await self.authenticate()

    async def _refresh(self) -> None:
        """Refresh the access token."""
        url = f"{self._base_url}/oauth/token"
        data = {
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token,
            "client_id": self._client_id,
        }
        async with self._session.post(url, data=data) as resp:
            if resp.status != 200:
                _LOGGER.warning("FarmOS: token refresh failed, re-authenticating")
                self._refresh_token = None
                await self.authenticate()
                return
            token_data = await resp.json()
            self._store_token(token_data)
        _LOGGER.debug("FarmOS: token refreshed successfully")

    def _store_token(self, token_data: dict) -> None:
        """Store token data from an OAuth response."""
        self._access_token = token_data["access_token"]
        self._refresh_token = token_data.get("refresh_token")
        expires_in = int(token_data.get("expires_in", 300))
        self._token_expires_at = time.time() + expires_in - TOKEN_EXPIRY_BUFFER

    # ── HTTP Helpers ──────────────────────────────────────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        json_data: dict | None = None,
        params: dict | None = None,
    ) -> dict | list | None:
        """Make an authenticated request to the FarmOS API."""
        await self._ensure_token()
        url = f"{self._base_url}{path}"
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/vnd.api+json",
            "Content-Type": "application/vnd.api+json",
        }
        async with self._session.request(
            method, url, json=json_data, params=params, headers=headers
        ) as resp:
            if resp.status == 401:
                # Token expired mid-request, retry once
                self._access_token = None
                await self._ensure_token()
                headers["Authorization"] = f"Bearer {self._access_token}"
                async with self._session.request(
                    method, url, json=json_data, params=params, headers=headers
                ) as retry_resp:
                    return await self._handle_response(retry_resp)
            return await self._handle_response(resp)

    async def _handle_response(self, resp: aiohttp.ClientResponse) -> dict | list | None:
        """Parse JSON:API response or raise on error."""
        if resp.status == 204:
            return None
        if resp.status >= 400:
            text = await resp.text()
            raise FarmOSApiError(
                f"FarmOS API error (HTTP {resp.status}): {text[:300]}"
            )
        return await resp.json()

    async def _get(self, path: str, params: dict | None = None) -> dict | None:
        return await self._request("GET", path, params=params)

    async def _post(self, path: str, data: dict) -> dict | None:
        return await self._request("POST", path, json_data=data)

    async def _patch(self, path: str, data: dict) -> dict | None:
        return await self._request("PATCH", path, json_data=data)

    # ── Health Check ──────────────────────────────────────────────────────────

    async def test_connection(self) -> dict:
        """Test the connection and return farm info from /api."""
        await self._ensure_token()
        result = await self._get("/api")
        return result.get("meta", {}).get("farm", {}) if result else {}

    # ── Taxonomy Terms (plant_type) ───────────────────────────────────────────

    async def find_plant_type(self, name: str) -> dict | None:
        """Find a plant_type taxonomy term by name. Returns the JSON:API resource or None."""
        params = {"filter[name]": name}
        result = await self._get("/api/taxonomy_term/plant_type", params=params)
        if result and result.get("data"):
            data = result["data"]
            if isinstance(data, list) and data:
                return data[0]
        return None

    async def create_plant_type(self, variety: PlantVariety) -> dict:
        """Create a plant_type taxonomy term from a canonical PlantVariety.

        Maps canonical fields to FarmOS taxonomy term fields. Only uses
        fields that exist on the plant_type bundle (name, description,
        maturity_days). Full reference data is stored in the description
        as a JSON block until custom fields are added.
        """
        import json

        # Store reference data in description alongside human-readable text
        reference_json = json.dumps(variety.to_dict())
        description_text = variety.description or variety.name
        description_with_ref = (
            f"{description_text}\n\n"
            f"<!-- agribuddy_ref: {reference_json} -->"
        )

        attributes = {
            "name": variety.name,
            "description": {
                "value": description_with_ref,
                "format": "default",
            },
        }

        if variety.days_to_harvest_min is not None:
            attributes["maturity_days"] = variety.days_to_harvest_min

        payload = {
            "data": {
                "type": "taxonomy_term--plant_type",
                "attributes": attributes,
            }
        }

        result = await self._post("/api/taxonomy_term/plant_type", payload)
        term = result.get("data", {}) if result else {}
        _LOGGER.info(
            "FarmOS: created plant_type term '%s' (id=%s)",
            variety.name,
            term.get("id", "unknown"),
        )
        return term

    async def update_plant_type(self, term_id: str, variety: PlantVariety) -> dict:
        """Update an existing plant_type taxonomy term."""
        import json

        reference_json = json.dumps(variety.to_dict())
        description_text = variety.description or variety.name
        description_with_ref = (
            f"{description_text}\n\n"
            f"<!-- agribuddy_ref: {reference_json} -->"
        )

        attributes = {
            "name": variety.name,
            "description": {
                "value": description_with_ref,
                "format": "default",
            },
        }
        if variety.days_to_harvest_min is not None:
            attributes["maturity_days"] = variety.days_to_harvest_min

        payload = {
            "data": {
                "type": "taxonomy_term--plant_type",
                "id": term_id,
                "attributes": attributes,
            }
        }

        result = await self._patch(f"/api/taxonomy_term/plant_type/{term_id}", payload)
        return result.get("data", {}) if result else {}

    async def ensure_plant_type(self, variety: PlantVariety) -> dict:
        """Find or create a plant_type term for the given variety.

        Returns the JSON:API resource dict for the term.
        """
        existing = await self.find_plant_type(variety.name)
        if existing:
            term_id = existing.get("id")
            _LOGGER.debug(
                "FarmOS: plant_type '%s' already exists (id=%s), updating",
                variety.name,
                term_id,
            )
            return await self.update_plant_type(term_id, variety)
        return await self.create_plant_type(variety)

    # ── Plant Assets ──────────────────────────────────────────────────────────

    async def create_plant_asset(
        self,
        name: str,
        plant_type_id: str,
        location_id: str | None = None,
        notes: str = "",
    ) -> dict:
        """Create a plant asset linked to a plant_type taxonomy term.

        Args:
            name: Display name for this planting (e.g., "Cherokee Purple - Bed 3")
            plant_type_id: UUID of the plant_type taxonomy term
            location_id: Optional UUID of a land asset (garden bed, field)
            notes: Optional notes
        """
        relationships = {
            "plant_type": {
                "data": [
                    {
                        "type": "taxonomy_term--plant_type",
                        "id": plant_type_id,
                    }
                ]
            }
        }

        attributes = {"name": name, "status": "active"}
        if notes:
            attributes["notes"] = {"value": notes, "format": "default"}

        payload = {
            "data": {
                "type": "asset--plant",
                "attributes": attributes,
                "relationships": relationships,
            }
        }

        result = await self._post("/api/asset/plant", payload)
        asset = result.get("data", {}) if result else {}
        _LOGGER.info(
            "FarmOS: created plant asset '%s' (id=%s, plant_type=%s)",
            name,
            asset.get("id", "unknown"),
            plant_type_id,
        )
        return asset

    # ── Logs ──────────────────────────────────────────────────────────────────

    async def create_log(
        self,
        log_type: str,
        name: str,
        asset_ids: list[str] | None = None,
        timestamp: str | None = None,
        notes: str = "",
        status: str = "done",
    ) -> dict:
        """Create a log entry in FarmOS.

        Args:
            log_type: One of: activity, observation, input, harvest, seeding, etc.
            name: Log name/description
            asset_ids: UUIDs of assets this log references
            timestamp: ISO timestamp (defaults to now if not provided)
            notes: Additional notes
            status: 'pending', 'done', or 'abandoned'
        """
        attributes = {"name": name, "status": status}
        if timestamp:
            attributes["timestamp"] = timestamp
        if notes:
            attributes["notes"] = {"value": notes, "format": "default"}

        relationships = {}
        if asset_ids:
            relationships["asset"] = {
                "data": [
                    {"type": "asset--plant", "id": aid} for aid in asset_ids
                ]
            }

        payload = {
            "data": {
                "type": f"log--{log_type}",
                "attributes": attributes,
            }
        }
        if relationships:
            payload["data"]["relationships"] = relationships

        result = await self._post(f"/api/log/{log_type}", payload)
        log = result.get("data", {}) if result else {}
        _LOGGER.debug(
            "FarmOS: created %s log '%s' (id=%s)",
            log_type,
            name,
            log.get("id", "unknown"),
        )
        return log

    # ── Convenience: Full Plant Registration ──────────────────────────────────

    async def register_plant(
        self,
        variety: PlantVariety,
        plant_name: str,
        location_name: str = "",
        notes: str = "",
    ) -> dict:
        """Full workflow: ensure plant_type exists, create plant asset.

        This is the main entry point called by Agribuddy when a user adds
        a plant. It:
            1. Creates/updates the plant_type taxonomy term with reference data
            2. Creates a plant asset linked to that term
            3. Returns the created asset

        Returns a dict with 'plant_type' and 'asset' keys containing the
        JSON:API resources.
        """
        plant_type = await self.ensure_plant_type(variety)
        plant_type_id = plant_type.get("id")

        if not plant_type_id:
            raise FarmOSApiError(
                f"Failed to create/find plant_type for '{variety.name}'"
            )

        asset = await self.create_plant_asset(
            name=plant_name,
            plant_type_id=plant_type_id,
            notes=notes,
        )

        return {
            "plant_type": plant_type,
            "asset": asset,
            "plant_type_id": plant_type_id,
            "asset_id": asset.get("id"),
        }
