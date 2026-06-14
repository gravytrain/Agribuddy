"""AI-powered plant reference provider (fallback for varieties not in the CSV dataset).

Uses an LLM API to generate structured plant data in the canonical schema.
Supports OpenAI-compatible endpoints (OpenAI, local Ollama, etc.).
"""

from __future__ import annotations

import json
import logging
from typing import Any

import aiohttp

from .base import CompanionPlant, PlantingCalendar, PlantProvider, PlantVariety

_LOGGER = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a plant reference database. When given a plant variety name,
return accurate growing data as JSON. Be factual and conservative — if you're unsure
about a specific value, omit it rather than guessing.

Return ONLY valid JSON matching this exact schema (no markdown, no explanation):
{
    "variety_id": "slug-form-of-name",
    "name": "Display Name",
    "category": "vegetable category (e.g., tomato, pepper, herb, lettuce)",
    "scientific_name": "Genus species",
    "description": "Brief description of the variety",
    "days_to_harvest_min": null or integer,
    "days_to_harvest_max": null or integer,
    "days_to_germination_min": null or integer,
    "days_to_germination_max": null or integer,
    "sun_requirement": "Full sun (6+ hours) / Partial shade / Full shade",
    "water_requirement": "High / Moderate / Low",
    "soil_type": "Preferred soil description",
    "soil_ph_min": null or float,
    "soil_ph_max": null or float,
    "plant_spacing": "e.g., 18-24 inches",
    "plant_height": "e.g., 3-5 feet",
    "usda_zone_min": null or integer (1-13),
    "usda_zone_max": null or integer (1-13),
    "growing_season": "e.g., Warm season annual",
    "sowing_method": "Planting instructions",
    "growing_difficulty": "Easy / Moderate / Difficult",
    "is_container_friendly": true/false,
    "disease_resistance": "Known resistances or empty string",
    "common_pests": "Known pests or empty string",
    "common_diseases": "Known diseases or empty string",
    "is_invasive": true/false,
    "color": "Fruit/flower/foliage color",
    "size": "Fruit/plant size description",
    "shape": "Growth habit or fruit shape",
    "flavor_profile": "Taste description or empty string",
    "culinary_uses": "Cooking uses or empty string",
    "is_heirloom": true/false,
    "is_hybrid": true/false
}"""

SEARCH_SYSTEM_PROMPT = """You are a plant reference database. When given a search query,
return a JSON array of up to 5 matching plant varieties. Each entry should have at minimum:
variety_id (slug), name, category, scientific_name, and a brief description.

Return ONLY a valid JSON array (no markdown, no explanation)."""


class AiProvider(PlantProvider):
    """Plant reference provider that generates data via an LLM API.

    Configured with an OpenAI-compatible endpoint (works with OpenAI,
    Anthropic via proxy, local Ollama, LM Studio, etc.).
    """

    def __init__(
        self,
        api_base: str,
        api_key: str,
        model: str,
        session: aiohttp.ClientSession,
    ) -> None:
        self._api_base = api_base.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._session = session

    @property
    def provider_name(self) -> str:
        return "ai"

    async def _chat_completion(
        self, system: str, user_message: str
    ) -> str | None:
        """Call the LLM chat completion endpoint."""
        url = f"{self._api_base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.3,
        }

        try:
            async with self._session.post(url, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    _LOGGER.warning(
                        "AiProvider: LLM returned HTTP %d: %s", resp.status, text[:200]
                    )
                    return None
                data = await resp.json()
                choices = data.get("choices", [])
                if not choices:
                    return None
                return choices[0].get("message", {}).get("content", "")
        except Exception as err:
            _LOGGER.warning("AiProvider: LLM request failed: %s", err)
            return None

    def _parse_json_response(self, text: str | None) -> Any:
        """Extract JSON from LLM response, handling markdown fences."""
        if not text:
            return None
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = lines[1:]  # drop opening fence
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            _LOGGER.warning("AiProvider: could not parse LLM JSON response")
            return None

    def _dict_to_variety(self, data: dict[str, Any]) -> PlantVariety | None:
        """Convert an AI-generated dict to a PlantVariety with metadata."""
        if not data or not isinstance(data, dict):
            return None
        data["source"] = "ai"
        data["source_url"] = None
        data["confidence"] = 0.8
        try:
            return PlantVariety.from_dict(data)
        except (TypeError, ValueError) as err:
            _LOGGER.warning("AiProvider: could not construct PlantVariety: %s", err)
            return None

    async def search(self, query: str) -> list[PlantVariety]:
        """Search for plant varieties using AI to generate matches."""
        user_msg = (
            f"Search for plant varieties matching: '{query}'. "
            f"Return up to 5 results as a JSON array with fields: "
            f"variety_id, name, category, scientific_name, description, "
            f"sun_requirement, water_requirement, days_to_harvest_min, "
            f"days_to_harvest_max, usda_zone_min, usda_zone_max."
        )
        raw = await self._chat_completion(SEARCH_SYSTEM_PROMPT, user_msg)
        parsed = self._parse_json_response(raw)
        if not isinstance(parsed, list):
            return []

        results: list[PlantVariety] = []
        for item in parsed:
            variety = self._dict_to_variety(item)
            if variety:
                results.append(variety)
        return results

    async def get_variety(self, variety_id: str) -> PlantVariety | None:
        """Generate full variety data for a specific plant."""
        readable_name = variety_id.replace("-", " ").title()
        user_msg = (
            f"Provide complete growing reference data for the plant variety: "
            f"'{readable_name}'. Include all fields in the schema."
        )
        raw = await self._chat_completion(SYSTEM_PROMPT, user_msg)
        parsed = self._parse_json_response(raw)
        if not isinstance(parsed, dict):
            return None
        return self._dict_to_variety(parsed)

    async def get_planting_calendar(
        self, variety_id: str, usda_zone: int
    ) -> PlantingCalendar | None:
        """Generate a planting calendar via AI."""
        readable_name = variety_id.replace("-", " ").title()
        user_msg = (
            f"For '{readable_name}' in USDA zone {usda_zone}, provide a planting calendar. "
            f"Return JSON with fields: indoor_sow_start, indoor_sow_end, "
            f"outdoor_transplant_start, outdoor_transplant_end, direct_sow_start, "
            f"direct_sow_end, harvest_start, harvest_end. "
            f"Values should be month names (e.g., 'March', 'April') or null if not applicable."
        )
        system = (
            "You are a gardening calendar expert. Return ONLY valid JSON "
            "with month names for planting schedules. No markdown or explanation."
        )
        raw = await self._chat_completion(system, user_msg)
        parsed = self._parse_json_response(raw)
        if not isinstance(parsed, dict):
            return None
        return PlantingCalendar(
            variety_id=variety_id,
            usda_zone=usda_zone,
            indoor_sow_start=parsed.get("indoor_sow_start"),
            indoor_sow_end=parsed.get("indoor_sow_end"),
            outdoor_transplant_start=parsed.get("outdoor_transplant_start"),
            outdoor_transplant_end=parsed.get("outdoor_transplant_end"),
            direct_sow_start=parsed.get("direct_sow_start"),
            direct_sow_end=parsed.get("direct_sow_end"),
            harvest_start=parsed.get("harvest_start"),
            harvest_end=parsed.get("harvest_end"),
        )

    async def get_companions(self, variety_id: str) -> list[CompanionPlant]:
        """Generate companion planting data via AI."""
        readable_name = variety_id.replace("-", " ").title()
        user_msg = (
            f"List companion plants for '{readable_name}'. Return a JSON array where "
            f"each entry has: companion_name, relationship ('beneficial' or 'antagonistic'), "
            f"and reason (why this relationship exists). Include both good and bad companions."
        )
        system = (
            "You are a companion planting expert. Return ONLY a valid JSON array. "
            "No markdown or explanation."
        )
        raw = await self._chat_completion(system, user_msg)
        parsed = self._parse_json_response(raw)
        if not isinstance(parsed, list):
            return []

        results: list[CompanionPlant] = []
        for item in parsed:
            if isinstance(item, dict):
                results.append(
                    CompanionPlant(
                        variety_id=variety_id,
                        companion_name=item.get("companion_name", ""),
                        relationship=item.get("relationship", ""),
                        reason=item.get("reason", ""),
                    )
                )
        return results
