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
  GET  /api/agribuddy/plots                 — list grow plots (with embedded plants)
  POST /api/agribuddy/plot_create           — create a grow plot
  GET  /api/agribuddy/plots/<plot_id>       — fetch one plot
  PUT  /api/agribuddy/plots/<plot_id>       — update plot
  DELETE /api/agribuddy/plots/<plot_id>     — remove plot
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date

from aiohttp.web import Response
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import (
    CONF_DAYSTROM_URL,
    CONF_WEATHER_ENTITY,
    DOMAIN,
    EVENT_DEAD,
    EVENT_FERTILIZED,
    EVENT_HARVESTED,
    EVENT_RAIN_DETECTED,
    EVENT_WATERED,
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


# In-memory search cache
_search_cache: dict[str, tuple[float, list, str]] = {}


# ── Plant enrichment ──────────────────────────────────────────────────────────

_WATER_REQUIREMENT_MAP = {
    "frequent": (2, 3),
    "average": (3, 5),
    "moderate": (3, 5),
    "minimum": (5, 10),
    "low": (5, 10),
    "drought tolerant": (7, 14),
    "drought-tolerant": (7, 14),
}


def _days_since(date_str: str | None) -> int | None:
    if not date_str:
        return None
    try:
        d = date.fromisoformat(str(date_str)[:10])
        return (date.today() - d).days
    except (ValueError, TypeError):
        return None


def _coerce_int(val) -> int | None:
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _water_requirement_to_day_range(water_req: str) -> tuple[int, int]:
    if not water_req:
        return 3, 7
    key = water_req.strip().lower()
    return _WATER_REQUIREMENT_MAP.get(key, (3, 7))


def _enrich_plant(plant: dict) -> dict:
    """Add computed display fields the card expects on each plant record."""
    p = dict(plant)
    evts = p.get("events") or []

    # ── Days growing / scheduling ──────────────────────────────────────
    p["days_growing"] = _days_since(p.get("start_date"))
    dg = p["days_growing"]
    p["days_until_planting"] = max(0, -dg) if dg is not None else None
    p["is_scheduled"] = bool(dg is not None and dg < 0)

    # ── Watering tracking ──────────────────────────────────────────────
    last_w = None
    last_f = None
    for e in reversed(evts):
        etype = (e.get("type") or e.get("name") or "").lower()
        edate = e.get("date")
        if not last_w and etype in (EVENT_WATERED, EVENT_RAIN_DETECTED, "rain_detected"):
            last_w = edate
        if not last_f and etype == EVENT_FERTILIZED:
            last_f = edate
        if last_w and last_f:
            break

    never_watered = last_w is None
    baseline = last_w or p.get("start_date") or None

    p["last_watered"] = last_w
    p["last_fertilized"] = last_f
    p["days_since_watered"] = _days_since(baseline) if baseline else None
    p["days_since_fertilized"] = _days_since(last_f)
    p["never_watered"] = bool(never_watered and p.get("start_date"))

    # Water source
    if last_w:
        for e in evts:
            etype = (e.get("type") or e.get("name") or "").lower()
            if e.get("date") == last_w and etype in (EVENT_RAIN_DETECTED, "rain_detected"):
                p["last_water_source"] = "rain"
                break
        else:
            p["last_water_source"] = "manual"
    else:
        p["last_water_source"] = None

    # Sort events
    sorted_evts = sorted(evts, key=lambda e: e.get("date") or "", reverse=True)
    p["events_sorted"] = sorted_evts
    p["recent_events"] = sorted_evts[:100]

    # ── Species-derived fields ─────────────────────────────────────────
    sd = p.get("species_data") or {}
    ov = p.get("overrides") or {}

    # Names
    p["common_name"] = ov.get("common_name") or sd.get("name") or sd.get("common_name") or p.get("name") or ""
    p["scientific_name"] = ov.get("scientific_name") or sd.get("scientific_name") or ""
    p["variety_name"] = sd.get("variety_name") or sd.get("name") or ""
    p["common_names"] = [p["common_name"]] if p["common_name"] else []
    p["plant_name"] = p.get("name") or p["common_name"]

    # Light
    p["light_requirements"] = (
        ov.get("light_requirements") or sd.get("sun_requirement") or sd.get("light_requirements") or ""
    )
    p["sunlight"] = [p["light_requirements"]] if p["light_requirements"] else []

    # Water
    water_req_raw = ov.get("water_use") or sd.get("water_requirement") or sd.get("water_use") or ""
    p["water_use"] = water_req_raw
    p["water_requirement"] = water_req_raw
    default_min, default_max = _water_requirement_to_day_range(water_req_raw)
    ov_min = ov.get("watering_min_days")
    ov_max = ov.get("watering_max_days")
    p["watering_min_days"] = _coerce_int(ov_min) if _coerce_int(ov_min) is not None else default_min
    p["watering_max_days"] = _coerce_int(ov_max) if _coerce_int(ov_max) is not None else default_max
    p["watering_default_min_days"] = default_min
    p["watering_default_max_days"] = default_max
    if p["watering_min_days"] is not None and p["watering_max_days"] is not None:
        p["watering_benchmark_value"] = f"{p['watering_min_days']}-{p['watering_max_days']}"
    elif p["watering_min_days"] is not None:
        p["watering_benchmark_value"] = str(p["watering_min_days"])
    else:
        p["watering_benchmark_value"] = None
    p["watering_benchmark_unit"] = "days"

    # Hardiness zones
    hz_min = ov.get("hardiness_zone_min") or sd.get("usda_zone_min") or sd.get("hardiness_zone_min")
    hz_max = ov.get("hardiness_zone_max") or sd.get("usda_zone_max") or sd.get("hardiness_zone_max")
    p["hardiness_zone_min"] = hz_min
    p["hardiness_zone_max"] = hz_max
    if hz_min is not None and hz_max is not None and hz_min != hz_max:
        p["hardiness_zone_range"] = f"{hz_min}–{hz_max}"
    elif hz_min is not None:
        p["hardiness_zone_range"] = str(hz_min)
    else:
        p["hardiness_zone_range"] = ""

    # Soil
    p["soil_preference"] = ov.get("soil_preference") or sd.get("soil_type") or sd.get("soil_preference") or ""
    p["spacing_requirement"] = ov.get("spacing_requirement") or sd.get("plant_spacing") or sd.get("spacing_requirement") or ""
    p["growth_period"] = ov.get("growth_period") or sd.get("growing_season") or sd.get("growth_period") or ""
    p["care_instructions"] = ov.get("care_instructions") or sd.get("sowing_method") or ""

    # pH
    ph_min = sd.get("soil_ph_min")
    ph_max = sd.get("soil_ph_max")
    p["soil_ph_min"] = ph_min
    p["soil_ph_max"] = ph_max
    if ph_min is not None and ph_max is not None and ph_min != ph_max:
        p["soil_ph_range"] = f"{ph_min}–{ph_max}"
    elif ph_min is not None:
        p["soil_ph_range"] = str(ph_min)
    else:
        p["soil_ph_range"] = ""

    # Harvest range
    h_min = sd.get("days_to_harvest_min")
    h_max = sd.get("days_to_harvest_max")
    p["days_to_harvest_min"] = h_min
    p["days_to_harvest_max"] = h_max
    if h_min is not None and h_max is not None and h_min != h_max:
        p["harvest_range"] = f"{h_min}–{h_max} days"
    elif h_min is not None:
        p["harvest_range"] = f"{h_min} days"
    else:
        p["harvest_range"] = ""

    # Toxicity
    tox = sd.get("toxicity") or {}
    if isinstance(tox, dict):
        p["toxicity_species"] = list(tox.keys())
        benign = {"non-toxic", "nontoxic", "none", "mild", "low", ""}
        concerning = [
            f"{species}: {info.get('level', '?')}"
            for species, info in tox.items()
            if isinstance(info, dict) and (info.get("level") or "").lower() not in benign
        ]
        p["toxicity_display"] = ", ".join(concerning) if concerning else "Non-toxic"
    else:
        p["toxicity_species"] = []
        p["toxicity_display"] = str(tox) if tox else "Non-toxic"

    # Invasive
    p["invasive_alert"] = sd.get("is_invasive") or sd.get("invasive_alert") or False

    # Image
    p["image_url"] = ov.get("image_url") or sd.get("image_url") or ""

    # Description
    p["description"] = ov.get("description") or sd.get("description") or ""

    return p


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

        try:
            plants = await daystrom.get_plants()
            for plant in plants:
                if str(plant.get("species_id", "")) == sid:
                    species_data = plant.get("species_data")
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
    """GET /api/agribuddy/plants — list all plants enriched (proxy to Daystrom)."""

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
            enriched = [_enrich_plant(p) for p in plants]
            return _json({"data": enriched, "count": len(enriched)})
        except DaystromError as err:
            return _json({"error": "daystrom_error", "message": str(err)}, 502)


class AgribuddyPlotsView(HomeAssistantView):
    """GET /api/agribuddy/plots — list grow plots with embedded enriched plants."""

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
            plants = await daystrom.get_plants(status="active")
            enriched_plants = [_enrich_plant(p) for p in plants]

            # Group plants by plot_id
            plants_by_plot: dict[str, list] = {}
            unassigned_plants: list = []
            for p in enriched_plants:
                pid = p.get("plot_id")
                if pid:
                    plants_by_plot.setdefault(pid, []).append(p)
                else:
                    unassigned_plants.append(p)

            # Build response with embedded plants
            result = []
            for plot in plots:
                plot_out = dict(plot)
                plot_out["plants"] = plants_by_plot.get(plot["id"], [])
                plot_out["plant_count"] = len(plot_out["plants"])
                result.append(plot_out)

            # Virtual Unassigned plot
            result.append({
                "id": "_unassigned",
                "name": "Unassigned",
                "description": "Plants not yet assigned to a grow plot",
                "plants": unassigned_plants,
                "plant_count": len(unassigned_plants),
                "virtual": True,
            })

            return _json(result)
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
            # Embed plants for this plot
            plants = await daystrom.get_plants(status="active", plot_id=plot_id)
            plot_out = dict(plot)
            plot_out["plants"] = [_enrich_plant(p) for p in plants]
            plot_out["plant_count"] = len(plot_out["plants"])
            return _json(plot_out)
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
