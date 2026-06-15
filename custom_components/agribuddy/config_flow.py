"""Config flow for Agribuddy — Daystrom server + weather entity."""
from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import EntitySelector, EntitySelectorConfig

from .const import (
    CONF_AI_API_BASE,
    CONF_AI_API_KEY,
    CONF_AI_MODEL,
    CONF_DAYSTROM_API_KEY,
    CONF_DAYSTROM_URL,
    CONF_UPDATE_INTERVAL,
    CONF_WEATHER_ENTITY,
    DEFAULT_NAME,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

_ENTITY_SELECTOR = EntitySelector(EntitySelectorConfig())


class AgribuddyConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 6

    def __init__(self) -> None:
        self._daystrom_url: str = ""
        self._daystrom_api_key: str = ""
        self._weather_entity: str = ""
        self._ai_api_base: str = ""
        self._ai_api_key: str = ""
        self._ai_model: str = ""

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        """Step 1: Daystrom server connection."""
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        errors: dict[str, str] = {}
        if user_input is not None:
            url = (user_input.get(CONF_DAYSTROM_URL) or "").strip().rstrip("/")
            api_key = (user_input.get(CONF_DAYSTROM_API_KEY) or "").strip()

            if not url:
                errors["base"] = "daystrom_url_empty"
            else:
                # Test connection
                try:
                    from homeassistant.helpers.aiohttp_client import async_get_clientsession
                    from .daystrom_client import DaystromClient

                    session = async_get_clientsession(self.hass)
                    client = DaystromClient(base_url=url, session=session, api_key=api_key)
                    health = await client.health()
                    if health.get("status") != "ok":
                        errors["base"] = "daystrom_connect_failed"
                    else:
                        self._daystrom_url = url
                        self._daystrom_api_key = api_key
                        return await self.async_step_weather()
                except Exception as err:
                    _LOGGER.warning("Daystrom connection test failed: %s", err)
                    errors["base"] = "daystrom_connect_failed"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_DAYSTROM_URL): str,
                vol.Optional(CONF_DAYSTROM_API_KEY, default=""): str,
            }),
            errors=errors,
        )

    async def async_step_weather(self, user_input: dict | None = None) -> FlowResult:
        """Step 2: Pick weather entity."""
        if user_input is not None:
            self._weather_entity = user_input[CONF_WEATHER_ENTITY]
            return await self.async_step_ai_provider()
        return self.async_show_form(
            step_id="weather",
            data_schema=vol.Schema({
                vol.Required(CONF_WEATHER_ENTITY): _ENTITY_SELECTOR,
            }),
        )

    async def async_step_ai_provider(self, user_input: dict | None = None) -> FlowResult:
        """Step 3: AI fallback provider (optional)."""
        if user_input is not None:
            self._ai_api_base = (user_input.get(CONF_AI_API_BASE) or "").strip()
            self._ai_api_key = (user_input.get(CONF_AI_API_KEY) or "").strip()
            self._ai_model = (user_input.get(CONF_AI_MODEL) or "").strip()

            return self.async_create_entry(
                title=DEFAULT_NAME,
                data={
                    CONF_DAYSTROM_URL: self._daystrom_url,
                    CONF_DAYSTROM_API_KEY: self._daystrom_api_key,
                    CONF_WEATHER_ENTITY: self._weather_entity,
                    CONF_AI_API_BASE: self._ai_api_base,
                    CONF_AI_API_KEY: self._ai_api_key,
                    CONF_AI_MODEL: self._ai_model,
                },
                options={CONF_UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL},
            )

        return self.async_show_form(
            step_id="ai_provider",
            data_schema=vol.Schema({
                vol.Optional(CONF_AI_API_BASE, default=""): str,
                vol.Optional(CONF_AI_API_KEY, default=""): str,
                vol.Optional(CONF_AI_MODEL, default=""): str,
            }),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return AgribuddyOptionsFlow(config_entry)


class AgribuddyOptionsFlow(OptionsFlow):
    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        if user_input is not None:
            merged_data = dict(self._entry.data)
            for key in [CONF_DAYSTROM_URL, CONF_DAYSTROM_API_KEY, CONF_WEATHER_ENTITY,
                        CONF_AI_API_BASE, CONF_AI_API_KEY, CONF_AI_MODEL]:
                if key in user_input:
                    merged_data[key] = user_input[key]
            self.hass.config_entries.async_update_entry(self._entry, data=merged_data)
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(CONF_DAYSTROM_URL, default=self._entry.data.get(CONF_DAYSTROM_URL, "")): str,
                vol.Optional(CONF_DAYSTROM_API_KEY, default=self._entry.data.get(CONF_DAYSTROM_API_KEY, "")): str,
                vol.Required(CONF_WEATHER_ENTITY, default=self._entry.data.get(CONF_WEATHER_ENTITY, "")): _ENTITY_SELECTOR,
                vol.Required(CONF_UPDATE_INTERVAL, default=self._entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)):
                    vol.All(vol.Coerce(int), vol.Range(min=60, max=10080)),
                vol.Optional(CONF_AI_API_BASE, default=self._entry.data.get(CONF_AI_API_BASE, "")): str,
                vol.Optional(CONF_AI_API_KEY, default=self._entry.data.get(CONF_AI_API_KEY, "")): str,
                vol.Optional(CONF_AI_MODEL, default=self._entry.data.get(CONF_AI_MODEL, "")): str,
            }),
        )
