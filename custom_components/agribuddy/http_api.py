"""Custom HTTP endpoints for Agribuddy card communication.

All plant/plot data is proxied through the Daystrom REST API.
Plant species search uses the local CSV provider (+ optional AI fallback).

Endpoints:
  GET  /api/agribuddy/status                — integration health
  GET  /api/agribuddy/test_connection       — verifies Daystrom connectivity
  GET  /api/agribuddy/search_plants?q=...   — CSV/AI species search
  GET  /api/agribuddy/species/<id>          — species detail from plant cache
  POST /api/agribuddy/update_config         — update weather entity, reload
  GET  /api/agribuddy/plants                — list plants (proxy to Daystrom)
  GET  /api/agribuddy/plots                 — list grow plots
  POST /api/agribuddy/plot_create           — create a grow plot
  GET  /api/agribuddy/plots/<plot_id>       — fetch one plot
  PUT  /api/agribuddy/plots/<plot_id>       — update plot
  DELETE /api/agribuddy/plots/<plot_id>     — remove plot
"""

from __future__ import annotations

import json
import logging
import time

from aiohttp.web import Response
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import (
    CONF_DAYSTROM_URL,
    CONF_WEATHER_ENTITY,
    DOMAIN,
)
from .daystrom_client import DaystromClient, DaystromError
from .providers import PlantResolver
from .providers.base import PlantVariety

_LOGGER = logging.getLogger(__name__)

_HTTP_API_VERSION = "2.0.0"

SEARCH_CACHE_TTL_SECONDS = 30 * 24 * 3600  # 30 days


def async_register_views(hass: HomeAssistant) -> None:
    """Register all Agribuddy HTTP views."""
    _LOGGER.info(
        "Agribuddy: async_register_views called — http_api version %s",
        _HTTP_API_VERSION,
    )
    views = [
        ("AgribuddyStatusView", AgribuddyStatusView),
        ("AgribuddyTestConnectionView", AgribuddyTestConnectionView),
        ("AgribuddySearchView", AgribuddySearchView),
        ("AgribuddySpeciesView", AgribuddySpeciesView),
        ("AgribuddyUpdateConfigView", AgribuddyUpdateConfigView),
        ("AgribuddyPlantsView", AgribuddyPlantsView),
        ("AgribuddyPlotsView", AgribuddyPlotsView),
        ("AgribuddyPlotCreateView", AgribuddyPlotCreateView),
        ("AgribuddyPlotView", AgribuddyPlotView),
    ]
    successes, failures = [], []
    for name, cls in views:
        try:
            hass.http.register_view(cls(hass))
            successes.append(f"{name} → {cls.url}")
        except Exception as err:
            failures.append(f"{name}: {type(err).__name__}: {err}")
            _LOGGER.exception("Agribuddy: register_view(%s) failed", name)
    _LOGGER.info(
        "Agribuddy: HTTP views registered — %d succeeded, %d failed",
        len(successes),
        len(failures),
    )


def _json(data, status=200):
    return Response(
        status=status, content_type="application/json", text=json.dumps(data)
    )


def _get_daystrom(hass: HomeAssistant) -> DaystromClient | None:
    for v in hass.data.get(DOMAIN, {}).values():
        if isinstance(v, dict) and "daystrom" in v:
            return v["daystrom"]
    return None


def _get_resolver(hass: HomeAssistant) -> PlantResolver | None:
    for v in hass.data.get(DOMAIN, {}).values():
        if isinstance(v, dict) and "resolver" in v:
            return v["resolver"]
    return None


def _get_coordinator(hass: HomeAssistant):
    for v in hass.data.get(DOMAIN, {}).values():
        if isinstance(v, dict) and "coordinator" in v:
            return v["coordinator"]
    return None


def _get_entry(hass: HomeAssistant):
    entries = hass.config_entries.async_entries(DOMAIN)
    return entries[0] if entries else None


# In-memory search cache (survives across card reloads within a session)
_search_cache: dict[str, tuple[float, list, str]] = {}


# ── Views ─────────────────────────────────────────────────────────────────────


class AgribuddyStatusView(HomeAssistantView):
    """GET /api/agribuddy/status — integration health snapshot."""

    url = "/api/agribuddy/status"
    name = "api:agribuddy:status"
    requires_auth = True

    def __init__(self, hass):
        self._hass = hass

    async def get(self, request):
        entry = _get_entry(self._hass)
        if entry is None:
            return _json({"configured": False, "message": "No config entry found."})

        daystrom = _get_daystrom(self._hass)
        daystrom_url = entry.data.get(CONF_DAYSTROM_URL, "")
        daystrom_ok = daystrom is not None

        return _json({
            "configured": True,
            "backend": "daystrom",
            "daystrom_url": daystrom_url,
            "daystrom_connected": daystrom_ok,
            "weather_entity": entry.options.get(
                CONF_WEATHER_ENTITY, entry.data.get(CONF_WEATHER_ENTITY, "not set")
            ),
            "http_api_version": _HTTP_API_VERSION,
            "message": "Connected to Daystrom." if daystrom_ok else "Daystrom client not loaded.",
        })


class AgribuddyTestConnectionView(HomeAssistantView):
    """GET /api/agribuddy/test_connection — live Daystrom health check."""

    url = "/api/agribuddy/test_connection"
    name = "api:agribuddy:test_connection"
    requires_auth = True

    def __init__(self, hass):
        self._hass = hass

    async def get(self, request):
        daystrom = _get_daystrom(self._hass)
        if daystrom is None:
            return _json(
                {"ok": False, "error": "not_configured", "message": "Daystrom not configured."},
                404,
            )
        try:
            health = await daystrom.health()
            return _json({
                "ok": True,
                "message": f"Daystrom v{health.get('version', '?')} is healthy.",
                "version": health.get("version"),
            })
        except DaystromError as err:
            return _json({"ok": False, "error": "connect_failed", "message": str(err)}, 502)
        except Exception as err:
            return _json({"ok": False, "error": "unknown", "message": str(err)}, 500)


class AgribuddySearchView(HomeAssistantView):
    """GET /api/agribuddy/search_plants?q=... — search plant species via CSV/AI resolver."""

    url = "/api/agribuddy/search_plants"
    name = "api:agribuddy:search_plants"
    requires_auth = True

    def __init__(self, hass):
        self._hass = hass

    async def get(self, request):
        q = request.rel_url.query.get("q", "").strip()
        if not q:
            return _json(
                {"error": "missing_query", "message": "Provide a ?q= search term."}, 400
            )

        cache_key = q.lower()
        cached = _search_cache.get(cache_key)
        if cached:
            ts, results, source = cached
            if time.time() - ts < SEARCH_CACHE_TTL_SECONDS:
                return _json({
                    "results": results,
                    "_source": source,
                    "_from_cache": True,
                    "_backend_version": _HTTP_API_VERSION,
                })

        resolver = _get_resolver(self._hass)
        if resolver is None:
            return _json({"error": "not_ready", "message": "Resolver not loaded.", "results": []}, 503)

        try:
            varieties = await resolver.search(q)
            if varieties:
                cleaned = [_normalize_plant_variety(v) for v in varieties]
                source = varieties[0].source if varieties else "resolver"
                _search_cache[cache_key] = (time.time(), cleaned, source)
                return _json({
                    "results": cleaned,
                    "_source": source,
                    "_from_cache": False,
                    "_backend_version": _HTTP_API_VERSION,
                })
        except Exception as err:
            _LOGGER.warning("Agribuddy: resolver search for '%s' failed: %s", q, err)

        return _json({
            "error": "no_results",
            "message": f"No results found for '{q}'.",
            "results": [],
        })


def _normalize_plant_variety(v: PlantVariety) -> dict:
    """Convert a PlantVariety into the flat dict shape the card expects."""
    ph_range = ""
    if v.soil_ph_min is not None and v.soil_ph_max is not None and v.soil_ph_min != v.soil_ph_max:
        ph_range = f"{v.soil_ph_min}-{v.soil_ph_max}"
    elif v.soil_ph_min is not None:
        ph_range = str(v.soil_ph_min)

    harvest_range = ""
    if v.days_to_harvest_min is not None and v.days_to_harvest_max is not None:
        if v.days_to_harvest_min != v.days_to_harvest_max:
            harvest_range = f"{v.days_to_harvest_min}-{v.days_to_harvest_max} days"
        else:
            harvest_range = f"{v.days_to_harvest_min} days"
    elif v.days_to_harvest_min is not None:
        harvest_range = f"{v.days_to_harvest_min} days"

    hz_range = ""
    if v.usda_zone_min is not None and v.usda_zone_max is not None and v.usda_zone_min != v.usda_zone_max:
        hz_range = f"{v.usda_zone_min}–{v.usda_zone_max}"
    elif v.usda_zone_min is not None:
        hz_range = str(v.usda_zone_min)

    return {
        "species_id": v.variety_id,
        "id": v.variety_id,
        "variety_id": v.variety_id,
        "common_name": v.name,
        "common_names": [v.name] if v.name else [],
        "variety_name": v.name,
        "scientific_name": v.scientific_name,
        "light_requirements": v.sun_requirement,
        "water_use": v.water_requirement,
        "water_requirement": v.water_requirement,
        "soil_preference": v.soil_type,
        "soil_ph_min": v.soil_ph_min,
        "soil_ph_max": v.soil_ph_max,
        "soil_ph_range": ph_range,
        "plant_spacing": v.plant_spacing,
        "spacing_requirement": v.plant_spacing,
        "plant_height": v.plant_height,
        "hardiness_zone_min": v.usda_zone_min,
        "hardiness_zone_max": v.usda_zone_max,
        "hardiness_zone_range": hz_range,
        "days_to_harvest_min": v.days_to_harvest_min,
        "days_to_harvest_max": v.days_to_harvest_max,
        "harvest_range": harvest_range,
        "growing_season": v.growing_season,
        "sowing_method": v.sowing_method,
        "growing_difficulty": v.growing_difficulty,
        "is_container_friendly": v.is_container_friendly,
        "disease_resistance": v.disease_resistance,
        "common_pests": v.common_pests,
        "common_diseases": v.common_diseases,
        "invasive_alert": v.is_invasive,
        "toxicity": v.toxicity,
        "category": v.category,
        "color": v.color,
        "size": v.size,
        "shape": v.shape,
        "flavor_profile": v.flavor_profile,
        "culinary_uses": v.culinary_uses,
        "is_heirloom": v.is_heirloom,
        "is_hybrid": v.is_hybrid,
        "image_url": v.image_url,
        "description": v.description,
        "source": v.source,
        "source_url": v.source_url,
        "confidence": v.confidence,
        "symbol": "",
        "api_provider": v.source,
    }


class AgribuddySpeciesView(HomeAssistantView):
    """GET /api/agribuddy/species/<id> — species detail from Daystrom plant cache."""

    url = "/api/agribuddy/species/{species_id}"
    name = "api:agribuddy:species"
    requires_auth = True

    def __init__(self, hass):
        self._hass = hass

    async def get(self, request, species_id: str):
        sid = str(species_id)
        daystrom = _get_daystrom(self._hass)
        if daystrom is None:
            return _json({"error": "not_ready"}, 503)

        # Check if any plant has this species_id and return its species_data
        try:
            plants = await daystrom.get_plants()
            for plant in plants:
                if str(plant.get("speciesId", "")) == sid:
                    species_data = plant.get("speciesData")
                    if species_data:
                        return _json(species_data)
        except DaystromError:
            pass

        return _json(
            {"error": "not_cached", "message": f"No species_data cached for '{sid}'."},
            404,
        )


class AgribuddyUpdateConfigView(HomeAssistantView):
    """POST /api/agribuddy/update_config — update settings and reload."""

    url = "/api/agribuddy/update_config"
    name = "api:agribuddy:update_config"
    requires_auth = True

    def __init__(self, hass):
        self._hass = hass

    async def post(self, request):
        try:
            body = await request.json()
        except Exception:
            return _json({"error": "bad_request", "message": "Invalid JSON body."}, 400)

        entry = _get_entry(self._hass)
        if entry is None:
            return _json({"error": "not_configured"}, 404)

        new_data = dict(entry.data)
        new_options = dict(entry.options)
        changed = False

        if body.get("weather_entity"):
            new_data[CONF_WEATHER_ENTITY] = body["weather_entity"]
            new_options[CONF_WEATHER_ENTITY] = body["weather_entity"]
            changed = True

        if not changed:
            return _json({"ok": True, "message": "Nothing to update."})

        self._hass.config_entries.async_update_entry(entry, data=new_data, options=new_options)
        self._hass.async_create_task(
            self._hass.config_entries.async_reload(entry.entry_id)
        )
        return _json({"ok": True, "message": "Settings saved. Integration is reloading."})


class AgribuddyPlantsView(HomeAssistantView):
    """GET /api/agribuddy/plants — list all plants (proxy to Daystrom)."""

    url = "/api/agribuddy/plants"
    name = "api:agribuddy:plants"
    requires_auth = True

    def __init__(self, hass):
        self._hass = hass

    async def get(self, request):
        daystrom = _get_daystrom(self._hass)
        if daystrom is None:
            return _json({"error": "not_ready"}, 503)
        status = request.rel_url.query.get("status", "active")
        plot_id = request.rel_url.query.get("plot_id", "")
        try:
            plants = await daystrom.get_plants(status=status, plot_id=plot_id)
            return _json({"data": plants, "count": len(plants)})
        except DaystromError as err:
            return _json({"error": "daystrom_error", "message": str(err)}, 502)


class AgribuddyPlotsView(HomeAssistantView):
    """GET /api/agribuddy/plots — list grow plots (proxy to Daystrom)."""

    url = "/api/agribuddy/plots"
    name = "api:agribuddy:plots"
    requires_auth = True

    def __init__(self, hass):
        self._hass = hass

    async def get(self, request):
        daystrom = _get_daystrom(self._hass)
        if daystrom is None:
            return _json({"error": "not_ready"}, 503)
        try:
            plots = await daystrom.get_plots()
            return _json(plots)
        except DaystromError as err:
            return _json({"error": "daystrom_error", "message": str(err)}, 502)


class AgribuddyPlotCreateView(HomeAssistantView):
    """POST /api/agribuddy/plot_create — create a grow plot."""

    url = "/api/agribuddy/plot_create"
    name = "api:agribuddy:plot_create"
    requires_auth = True

    def __init__(self, hass):
        self._hass = hass

    async def post(self, request):
        try:
            body = await request.json()
        except Exception:
            return _json({"error": "bad_request", "message": "Invalid JSON."}, 400)

        name = (body.get("name") or "").strip()
        if not name:
            return _json({"error": "missing_name", "message": "Plot name is required."}, 400)

        daystrom = _get_daystrom(self._hass)
        if daystrom is None:
            return _json({"error": "not_ready"}, 503)

        try:
            plot = await daystrom.create_plot(
                name=name, description=str(body.get("description", "") or "")
            )
            coord = _get_coordinator(self._hass)
            if coord:
                await coord.async_request_refresh()
            return _json({"ok": True, "plot": plot})
        except DaystromError as err:
            return _json({"error": "daystrom_error", "message": str(err)}, 502)


class AgribuddyPlotView(HomeAssistantView):
    """GET/PUT/DELETE /api/agribuddy/plots/<plot_id>."""

    url = "/api/agribuddy/plots/{plot_id}"
    name = "api:agribuddy:plot"
    requires_auth = True

    def __init__(self, hass):
        self._hass = hass

    async def get(self, request, plot_id: str):
        daystrom = _get_daystrom(self._hass)
        if daystrom is None:
            return _json({"error": "not_ready"}, 503)
        try:
            plot = await daystrom.get_plot(plot_id)
            if plot is None:
                return _json({"error": "not_found"}, 404)
            return _json(plot)
        except DaystromError as err:
            return _json({"error": "daystrom_error", "message": str(err)}, 502)

    async def put(self, request, plot_id: str):
        try:
            body = await request.json()
        except Exception:
            return _json({"error": "bad_request", "message": "Invalid JSON."}, 400)

        daystrom = _get_daystrom(self._hass)
        if daystrom is None:
            return _json({"error": "not_ready"}, 503)

        try:
            plot = await daystrom.update_plot(
                plot_id,
                name=body.get("name"),
                description=body.get("description"),
            )
            coord = _get_coordinator(self._hass)
            if coord:
                await coord.async_request_refresh()
            return _json({"ok": True, "plot": plot})
        except DaystromError as err:
            return _json({"error": "daystrom_error", "message": str(err)}, 502)

    async def delete(self, request, plot_id: str):
        daystrom = _get_daystrom(self._hass)
        if daystrom is None:
            return _json({"error": "not_ready"}, 503)
        try:
            ok = await daystrom.delete_plot(plot_id)
            if not ok:
                return _json({"error": "not_found"}, 404)
            coord = _get_coordinator(self._hass)
            if coord:
                await coord.async_request_refresh()
            return _json({"ok": True})
        except DaystromError as err:
            return _json({"error": "daystrom_error", "message": str(err)}, 502)
