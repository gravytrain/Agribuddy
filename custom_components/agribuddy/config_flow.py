"""Config flow for Agribuddy — plant API key, weather entity, optional
FarmOS and AI provider configuration."""
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
    CONF_API_KEY,
    CONF_FARMOS_PASSWORD,
    CONF_FARMOS_URL,
    CONF_FARMOS_USERNAME,
    CONF_UPDATE_INTERVAL,
    CONF_WEATHER_ENTITY,
    DEFAULT_NAME,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    VERDANTLY_SIGNUP_URL,
)

_LOGGER = logging.getLogger(__name__)


# Any-entity picker — covers the full domain space (weather, sensor, MQTT,
# template, etc.) so users can pick whatever entity surfaces current weather.
_ENTITY_SELECTOR = EntitySelector(EntitySelectorConfig())


class AgribuddyConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 5

    def __init__(self) -> None:
        self._api_key: str = ""
        self._weather_entity: str = ""
        self._farmos_url: str = ""
        self._farmos_username: str = ""
        self._farmos_password: str = ""
        self._ai_api_base: str = ""
        self._ai_api_key: str = ""
        self._ai_model: str = ""

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        """Step 1: Verdantly Gardening API key (from RapidAPI). Optional."""
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        errors: dict[str, str] = {}
        if user_input is not None:
            self._api_key = (user_input.get(CONF_API_KEY) or "").strip()
            return await self.async_step_weather()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Optional(CONF_API_KEY, default=""): str}),
            errors=errors,
            description_placeholders={
                "signup_url": VERDANTLY_SIGNUP_URL,
            },
        )

    async def async_step_weather(self, user_input: dict | None = None) -> FlowResult:
        """Step 2: Pick any entity that represents the current weather."""
        if user_input is not None:
            self._weather_entity = user_input[CONF_WEATHER_ENTITY]
            return await self.async_step_farmos()
        return self.async_show_form(
            step_id="weather",
            data_schema=vol.Schema({
                vol.Required(CONF_WEATHER_ENTITY): _ENTITY_SELECTOR,
            }),
        )

    async def async_step_farmos(self, user_input: dict | None = None) -> FlowResult:
        """Step 3: FarmOS connection (optional)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._farmos_url = (user_input.get(CONF_FARMOS_URL) or "").strip().rstrip("/")
            self._farmos_username = (user_input.get(CONF_FARMOS_USERNAME) or "").strip()
            self._farmos_password = user_input.get(CONF_FARMOS_PASSWORD) or ""

            if self._farmos_url and self._farmos_username and self._farmos_password:
                try:
                    from homeassistant.helpers.aiohttp_client import (
                        async_get_clientsession,
                    )
                    from .farmos_client import FarmOSClient

                    session = async_get_clientsession(self.hass)
                    client = FarmOSClient(
                        base_url=self._farmos_url,
                        username=self._farmos_username,
                        password=self._farmos_password,
                        session=session,
                    )
                    await client.authenticate()
                    await client.test_connection()
                except Exception as err:
                    _LOGGER.warning("FarmOS connection test failed: %s", err)
                    errors["base"] = "farmos_connect_failed"

            if not errors:
                return await self.async_step_ai_provider()

        return self.async_show_form(
            step_id="farmos",
            data_schema=vol.Schema({
                vol.Optional(CONF_FARMOS_URL, default=""): str,
                vol.Optional(CONF_FARMOS_USERNAME, default=""): str,
                vol.Optional(CONF_FARMOS_PASSWORD, default=""): str,
            }),
            errors=errors,
        )

    async def async_step_ai_provider(self, user_input: dict | None = None) -> FlowResult:
        """Step 4: AI fallback provider (optional)."""
        if user_input is not None:
            self._ai_api_base = (user_input.get(CONF_AI_API_BASE) or "").strip()
            self._ai_api_key = (user_input.get(CONF_AI_API_KEY) or "").strip()
            self._ai_model = (user_input.get(CONF_AI_MODEL) or "").strip()

            return self.async_create_entry(
                title=DEFAULT_NAME,
                data={
                    CONF_API_KEY: self._api_key,
                    CONF_WEATHER_ENTITY: self._weather_entity,
                    CONF_FARMOS_URL: self._farmos_url,
                    CONF_FARMOS_USERNAME: self._farmos_username,
                    CONF_FARMOS_PASSWORD: self._farmos_password,
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
            new_weather = user_input.get(CONF_WEATHER_ENTITY)
            if new_weather and new_weather != self._entry.data.get(CONF_WEATHER_ENTITY):
                merged_data = dict(self._entry.data)
                merged_data[CONF_WEATHER_ENTITY] = new_weather
                self.hass.config_entries.async_update_entry(
                    self._entry, data=merged_data,
                )

            # Persist FarmOS/AI settings into entry.data so they survive reload
            farmos_ai_keys = [
                CONF_FARMOS_URL, CONF_FARMOS_USERNAME, CONF_FARMOS_PASSWORD,
                CONF_AI_API_BASE, CONF_AI_API_KEY, CONF_AI_MODEL,
            ]
            merged_data = dict(self._entry.data)
            for key in farmos_ai_keys:
                if key in user_input:
                    merged_data[key] = user_input[key]
            self.hass.config_entries.async_update_entry(
                self._entry, data=merged_data,
            )

            return self.async_create_entry(title="", data=user_input)

        current_interval = self._entry.options.get(
            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
        )
        current_weather = self._entry.options.get(
            CONF_WEATHER_ENTITY,
            self._entry.data.get(CONF_WEATHER_ENTITY, ""),
        )
        current_farmos_url = self._entry.data.get(CONF_FARMOS_URL, "")
        current_farmos_user = self._entry.data.get(CONF_FARMOS_USERNAME, "")
        current_farmos_pass = self._entry.data.get(CONF_FARMOS_PASSWORD, "")
        current_ai_base = self._entry.data.get(CONF_AI_API_BASE, "")
        current_ai_key = self._entry.data.get(CONF_AI_API_KEY, "")
        current_ai_model = self._entry.data.get(CONF_AI_MODEL, "")

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(CONF_UPDATE_INTERVAL, default=current_interval):
                    vol.All(vol.Coerce(int), vol.Range(min=60, max=10080)),
                vol.Required(CONF_WEATHER_ENTITY, default=current_weather):
                    _ENTITY_SELECTOR,
                vol.Optional(CONF_FARMOS_URL, default=current_farmos_url): str,
                vol.Optional(CONF_FARMOS_USERNAME, default=current_farmos_user): str,
                vol.Optional(CONF_FARMOS_PASSWORD, default=current_farmos_pass): str,
                vol.Optional(CONF_AI_API_BASE, default=current_ai_base): str,
                vol.Optional(CONF_AI_API_KEY, default=current_ai_key): str,
                vol.Optional(CONF_AI_MODEL, default=current_ai_model): str,
            }),
        )

