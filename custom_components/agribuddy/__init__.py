"""Agribuddy integration setup."""

from __future__ import annotations

import logging
from datetime import date

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    ATTR_EVENT_DATE,
    ATTR_EVENT_ID,
    ATTR_EVENT_NOTE,
    ATTR_EVENT_TYPE,
    ATTR_LOCATION,
    ATTR_PLANT_ID,
    ATTR_PLANT_NAME,
    ATTR_SPECIES_ID,
    ATTR_START_DATE,
    ATTR_START_TYPE,
    CONF_AI_API_BASE,
    CONF_AI_API_KEY,
    CONF_AI_MODEL,
    CONF_DAYSTROM_API_KEY,
    CONF_DAYSTROM_URL,
    CONF_UPDATE_INTERVAL,
    CONF_WEATHER_ENTITY,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MANUAL_EVENT_TYPES,
    SERVICE_ADD_PLANT,
    SERVICE_LOG_EVENT,
    SERVICE_REMOVE_EVENT,
    SERVICE_REMOVE_PLANT,
    SERVICE_UPDATE_OVERRIDES,
    SERVICE_UPDATE_PLANT,
    START_TYPES,
)
from .coordinator import AgribuddyCoordinator
from .daystrom_client import DaystromClient
from .http_api import async_register_views
from .providers import CsvProvider, PlantResolver
from .providers.ai_provider import AiProvider

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


# ── Service schemas ───────────────────────────────────────────────────────────

_ADD_PLANT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PLANT_NAME): cv.string,
        vol.Required(ATTR_SPECIES_ID): vol.Any(cv.string, vol.Coerce(int)),
        vol.Optional(ATTR_START_TYPE, default="seed"): vol.In(START_TYPES),
        vol.Optional(ATTR_START_DATE): cv.date,
        vol.Optional(ATTR_LOCATION, default=""): cv.string,
        vol.Optional("plot_id"): cv.string,
        vol.Optional("species_data"): dict,
    }
)

_REMOVE_PLANT_SCHEMA = vol.Schema(
    {vol.Required(ATTR_PLANT_ID): cv.string}
)

_LOG_EVENT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PLANT_ID): cv.string,
        vol.Required(ATTR_EVENT_TYPE): vol.In(MANUAL_EVENT_TYPES),
        vol.Optional(ATTR_EVENT_NOTE, default=""): cv.string,
        vol.Optional(ATTR_EVENT_DATE): cv.date,
    }
)

_REMOVE_EVENT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PLANT_ID): cv.string,
        vol.Required(ATTR_EVENT_ID): cv.string,
    }
)

_UPDATE_OVERRIDES_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PLANT_ID): cv.string,
        vol.Optional("overrides"): dict,
    }
)

_UPDATE_PLANT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PLANT_ID): cv.string,
        vol.Optional(ATTR_PLANT_NAME): cv.string,
        vol.Optional(ATTR_START_TYPE): vol.In(START_TYPES),
        vol.Optional(ATTR_START_DATE): cv.date,
        vol.Optional(ATTR_LOCATION): cv.string,
        vol.Optional("plot_id"): cv.string,
    }
)


# ── Setup ─────────────────────────────────────────────────────────────────────

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Agribuddy from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    session = async_get_clientsession(hass)

    # ── Daystrom client (required) ───────────────────────────────────────
    daystrom_url = entry.data.get(CONF_DAYSTROM_URL, "")
    daystrom_api_key = entry.data.get(CONF_DAYSTROM_API_KEY, "")

    if not daystrom_url:
        _LOGGER.error("Agribuddy: Daystrom URL not configured")
        return False

    daystrom = DaystromClient(
        base_url=daystrom_url, session=session, api_key=daystrom_api_key
    )

    try:
        health = await daystrom.health()
        _LOGGER.info(
            "Agribuddy: connected to Daystrom v%s at %s",
            health.get("version", "unknown"),
            daystrom_url,
        )
    except Exception as err:
        _LOGGER.error("Agribuddy: cannot reach Daystrom at %s: %s", daystrom_url, err)
        return False

    # ── Plant reference providers (CSV + optional AI) ────────────────────
    csv_provider = CsvProvider()
    csv_provider.load()
    providers = [csv_provider]

    ai_base = entry.data.get(CONF_AI_API_BASE, "")
    ai_key = entry.data.get(CONF_AI_API_KEY, "")
    ai_model = entry.data.get(CONF_AI_MODEL, "")
    if ai_base and ai_key and ai_model:
        ai_provider = AiProvider(api_base=ai_base, api_key=ai_key, model=ai_model)
        providers.append(ai_provider)
        _LOGGER.info("Agribuddy: AI fallback provider configured (%s)", ai_model)

    resolver = PlantResolver(providers=providers)
    _LOGGER.info("Agribuddy: PlantResolver initialized with providers: %s", resolver.provider_names)

    # ── Coordinator ──────────────────────────────────────────────────────
    update_min = entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
    weather_entity = entry.options.get(
        CONF_WEATHER_ENTITY, entry.data.get(CONF_WEATHER_ENTITY, "")
    )

    coordinator = AgribuddyCoordinator(
        hass,
        daystrom=daystrom,
        weather_entity=weather_entity,
        update_interval_minutes=update_min,
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        "daystrom": daystrom,
        "resolver": resolver,
        "coordinator": coordinator,
        "weather_entity": weather_entity,
    }

    # ── HTTP endpoints for the Lovelace card ─────────────────────────────
    async_register_views(hass)

    # ── Register services ────────────────────────────────────────────────
    _register_services(hass, entry)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Agribuddy."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_daystrom(hass: HomeAssistant) -> DaystromClient | None:
    for v in hass.data.get(DOMAIN, {}).values():
        if isinstance(v, dict) and "daystrom" in v:
            return v["daystrom"]
    return None


def _get_coordinator(hass: HomeAssistant) -> AgribuddyCoordinator | None:
    for v in hass.data.get(DOMAIN, {}).values():
        if isinstance(v, dict) and "coordinator" in v:
            return v["coordinator"]
    return None


def _fire_data_changed(hass: HomeAssistant, **kwargs) -> None:
    hass.bus.async_fire(f"{DOMAIN}_data_changed", kwargs)


# ── Service registration ──────────────────────────────────────────────────────

def _register_services(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Register all Agribuddy services."""

    async def handle_add_plant(call: ServiceCall) -> None:
        daystrom = _get_daystrom(hass)
        if not daystrom:
            _LOGGER.error("Agribuddy: Daystrom client not available")
            return

        d = call.data.get(ATTR_START_DATE)
        start_date = d.isoformat() if isinstance(d, date) else d or date.today().isoformat()

        plant = await daystrom.add_plant(
            name=call.data[ATTR_PLANT_NAME],
            species_id=str(call.data[ATTR_SPECIES_ID]),
            start_type=call.data.get(ATTR_START_TYPE, "seed"),
            start_date=start_date,
            location=call.data.get(ATTR_LOCATION, ""),
            plot_id=call.data.get("plot_id", ""),
            species_data=call.data.get("species_data"),
        )

        coordinator = _get_coordinator(hass)
        if coordinator:
            await coordinator.async_request_refresh()
        _fire_data_changed(hass, kind="plant_added", plant_id=plant.get("id"))

    async def handle_remove_plant(call: ServiceCall) -> None:
        daystrom = _get_daystrom(hass)
        if not daystrom:
            return
        await daystrom.remove_plant(call.data[ATTR_PLANT_ID])
        coordinator = _get_coordinator(hass)
        if coordinator:
            await coordinator.async_request_refresh()
        _fire_data_changed(hass, kind="plant_removed", plant_id=call.data[ATTR_PLANT_ID])

    async def handle_log_event(call: ServiceCall) -> None:
        daystrom = _get_daystrom(hass)
        if not daystrom:
            return
        d = call.data.get(ATTR_EVENT_DATE)
        event_date = d.isoformat() if isinstance(d, date) else d

        event = await daystrom.log_event(
            plant_id=call.data[ATTR_PLANT_ID],
            event_type=call.data[ATTR_EVENT_TYPE],
            note=call.data.get(ATTR_EVENT_NOTE, ""),
            event_date=event_date,
        )
        if event is None:
            _LOGGER.warning("Agribuddy: log_event failed for plant %s", call.data[ATTR_PLANT_ID])
            return

        coordinator = _get_coordinator(hass)
        if coordinator:
            await coordinator.async_request_refresh()
        _fire_data_changed(
            hass,
            kind="event_logged",
            plant_id=call.data[ATTR_PLANT_ID],
            event_id=event.get("id"),
            event_type=call.data[ATTR_EVENT_TYPE],
        )

    async def handle_remove_event(call: ServiceCall) -> None:
        daystrom = _get_daystrom(hass)
        if not daystrom:
            return
        await daystrom.remove_event(call.data[ATTR_PLANT_ID], call.data[ATTR_EVENT_ID])
        coordinator = _get_coordinator(hass)
        if coordinator:
            await coordinator.async_request_refresh()
        _fire_data_changed(
            hass, kind="event_removed",
            plant_id=call.data[ATTR_PLANT_ID],
            event_id=call.data[ATTR_EVENT_ID],
        )

    async def handle_update_overrides(call: ServiceCall) -> None:
        daystrom = _get_daystrom(hass)
        if not daystrom:
            return
        overrides = call.data.get("overrides") or {}
        await daystrom.update_plant(call.data[ATTR_PLANT_ID], overrides=overrides)
        coordinator = _get_coordinator(hass)
        if coordinator:
            await coordinator.async_request_refresh()
        _fire_data_changed(hass, kind="overrides_updated", plant_id=call.data[ATTR_PLANT_ID])

    async def handle_update_plant(call: ServiceCall) -> None:
        daystrom = _get_daystrom(hass)
        if not daystrom:
            return
        kwargs = {}
        if ATTR_PLANT_NAME in call.data:
            kwargs["name"] = call.data[ATTR_PLANT_NAME]
        if ATTR_START_TYPE in call.data:
            kwargs["start_type"] = call.data[ATTR_START_TYPE]
        if ATTR_START_DATE in call.data:
            d = call.data[ATTR_START_DATE]
            kwargs["start_date"] = d.isoformat() if isinstance(d, date) else d
        if ATTR_LOCATION in call.data:
            kwargs["location"] = call.data[ATTR_LOCATION]
        if "plot_id" in call.data:
            kwargs["plot_id"] = call.data["plot_id"]

        await daystrom.update_plant(call.data[ATTR_PLANT_ID], **kwargs)
        coordinator = _get_coordinator(hass)
        if coordinator:
            await coordinator.async_request_refresh()
        _fire_data_changed(hass, kind="plant_updated", plant_id=call.data[ATTR_PLANT_ID])

    # Register all services
    hass.services.async_register(DOMAIN, SERVICE_ADD_PLANT, handle_add_plant, schema=_ADD_PLANT_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_REMOVE_PLANT, handle_remove_plant, schema=_REMOVE_PLANT_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_LOG_EVENT, handle_log_event, schema=_LOG_EVENT_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_REMOVE_EVENT, handle_remove_event, schema=_REMOVE_EVENT_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_UPDATE_OVERRIDES, handle_update_overrides, schema=_UPDATE_OVERRIDES_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_UPDATE_PLANT, handle_update_plant, schema=_UPDATE_PLANT_SCHEMA)
