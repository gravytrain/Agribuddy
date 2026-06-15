"""DataUpdateCoordinator for Agribuddy.

Reads plant data from Daystrom and weather data from a HA weather entity.
The periodic refresh (default 24h) is a safety net; real-time weather
reactions happen via async_track_state_change_event on the configured
weather entity.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    DEFAULT_FROST_THRESHOLD_C,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    EVENT_FROST_ALERT,
    EVENT_RAIN_DETECTED,
)
from .daystrom_client import DaystromClient

_LOGGER = logging.getLogger(__name__)


class AgribuddyCoordinator(DataUpdateCoordinator):
    """Reads plant data from Daystrom and weather from the configured HA entity."""

    def __init__(
        self,
        hass: HomeAssistant,
        daystrom: DaystromClient,
        weather_entity: str,
        update_interval_minutes: int = DEFAULT_UPDATE_INTERVAL,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=update_interval_minutes),
        )
        self.daystrom = daystrom
        self.weather_entity = weather_entity
        self._frost_alerted_date: str | None = None
        self._rain_logged_date: str | None = None
        self._unsub_state_change = None

        if weather_entity:
            self._unsub_state_change = async_track_state_change_event(
                hass,
                [weather_entity],
                self._on_weather_state_change,
            )
            _LOGGER.info(
                "Agribuddy: subscribed to state changes for weather entity %s",
                weather_entity,
            )

    @callback
    def _on_weather_state_change(self, event: Event) -> None:
        self.hass.async_create_task(self._process_weather_change(event))

    async def _process_weather_change(self, event: Event) -> None:
        """Read the entity and auto-log rain/frost events to Daystrom."""
        weather = self._read_weather_entity()
        if not weather:
            return
        today = date.today().isoformat()
        rain = self._check_rain(weather)
        frost = self._check_frost(weather)

        _LOGGER.debug(
            "Agribuddy: weather state change — condition=%r precipitation=%r "
            "tonight_low=%r → rain=%s frost=%s",
            weather.get("condition"),
            weather.get("precipitation"),
            weather.get("tonight_low"),
            rain,
            frost,
        )

        if rain and self._rain_logged_date != today:
            _LOGGER.info(
                "Agribuddy: rain detected — auto-logging rain event for all active plants"
            )
            await self._log_rain_all_plants()
            self._rain_logged_date = today
            self.hass.bus.async_fire(
                f"{DOMAIN}_data_changed",
                {"kind": "weather_logged", "date": today, "rain": True},
            )

        if frost and self._frost_alerted_date != today:
            await self._maybe_frost_alert(weather, today)

    async def _async_update_data(self) -> dict[str, Any]:
        """Periodic refresh — pull plants from Daystrom and read weather."""
        weather = self._read_weather_entity()
        today = date.today().isoformat()

        plants = await self.daystrom.get_plants(status="active")
        plots = await self.daystrom.get_plots()

        frost_tonight = self._check_frost(weather)
        rain_today = self._check_rain(weather)

        if rain_today and self._rain_logged_date != today:
            await self._log_rain_all_plants()
            self._rain_logged_date = today

        if frost_tonight and self._frost_alerted_date != today:
            await self._maybe_frost_alert(weather, today)

        return {
            "weather": weather,
            "plants": plants,
            "plots": plots,
            "frost_tonight": frost_tonight,
            "rain_today": rain_today,
        }

    async def async_shutdown(self) -> None:
        if self._unsub_state_change is not None:
            try:
                self._unsub_state_change()
            except Exception as err:
                _LOGGER.warning("Agribuddy: failed to detach state listener: %s", err)
            self._unsub_state_change = None
        await super().async_shutdown()

    # ── Weather entity reading ────────────────────────────────────────────────

    def _read_weather_entity(self) -> dict:
        if not self.weather_entity:
            return {}
        state = self.hass.states.get(self.weather_entity)
        if state is None:
            _LOGGER.warning(
                "Agribuddy: weather entity '%s' not found in HA.",
                self.weather_entity,
            )
            return {}
        attrs = state.attributes or {}
        forecast = attrs.get("forecast", []) or []
        tonight_low = None
        if forecast:
            tonight_low = forecast[0].get("templow") or forecast[0].get("temperature")
        return {
            "condition": state.state,
            "temperature": attrs.get("temperature"),
            "humidity": attrs.get("humidity"),
            "pressure": attrs.get("pressure"),
            "wind_speed": attrs.get("wind_speed"),
            "precipitation": attrs.get("precipitation"),
            "forecast": forecast,
            "tonight_low": tonight_low,
            "entity_id": self.weather_entity,
            "temperature_unit": attrs.get("temperature_unit"),
            "wind_speed_unit": attrs.get("wind_speed_unit"),
            "pressure_unit": attrs.get("pressure_unit"),
            "precipitation_unit": attrs.get("precipitation_unit"),
            "humidity_unit": "%",
        }

    @staticmethod
    def _check_frost(weather: dict) -> bool:
        low = weather.get("tonight_low")
        if low is None:
            return False
        try:
            return float(low) <= float(DEFAULT_FROST_THRESHOLD_C)
        except (ValueError, TypeError):
            return False

    @staticmethod
    def _check_rain(weather: dict) -> bool:
        precip = weather.get("precipitation")
        if precip is not None:
            try:
                if float(precip) > 0:
                    return True
            except (ValueError, TypeError):
                pass
        cond = (weather.get("condition") or "").lower().replace("-", "_")
        rain_keywords = ("rain", "drizzle", "shower", "thunder", "pour", "lightning_rainy")
        if any(w in cond for w in rain_keywords):
            return True
        forecast = weather.get("forecast") or []
        if forecast:
            fcast_cond = (forecast[0].get("condition") or "").lower().replace("-", "_")
            if any(w in fcast_cond for w in rain_keywords):
                return True
        return False

    @staticmethod
    def _check_snow(weather: dict) -> bool:
        cond = (weather.get("condition") or "").lower().replace("-", "_")
        snow_keywords = ("snow", "snowy", "sleet", "blizzard", "flurries")
        if any(w in cond for w in snow_keywords):
            return True
        forecast = weather.get("forecast") or []
        if forecast:
            fcast_cond = (forecast[0].get("condition") or "").lower().replace("-", "_")
            if any(w in fcast_cond for w in snow_keywords):
                return True
        return False

    # ── Auto-events ───────────────────────────────────────────────────────────

    async def _log_rain_all_plants(self) -> None:
        """Log a rain_detected event on every active plant via Daystrom."""
        try:
            plants = await self.daystrom.get_plants(status="active")
            for plant in plants:
                plant_id = plant.get("id")
                if plant_id:
                    await self.daystrom.log_event(
                        plant_id=str(plant_id),
                        event_type=EVENT_RAIN_DETECTED,
                        note="Auto-detected from weather entity",
                        auto=True,
                    )
            _LOGGER.info("Agribuddy: rain event logged for %d active plants", len(plants))
        except Exception as err:
            _LOGGER.warning("Agribuddy: failed to auto-log rain events: %s", err)

    async def _maybe_frost_alert(self, weather: dict, today: str) -> None:
        if self._frost_alerted_date == today:
            return
        low = weather.get("tonight_low", "?")
        try:
            plants = await self.daystrom.get_plants(status="active")
            for plant in plants:
                plant_id = plant.get("id")
                if plant_id:
                    await self.daystrom.log_event(
                        plant_id=str(plant_id),
                        event_type=EVENT_FROST_ALERT,
                        note=f"Overnight low forecast: {low}°C",
                        auto=True,
                    )
        except Exception as err:
            _LOGGER.warning("Agribuddy: failed to log frost alerts: %s", err)

        self.hass.async_create_task(
            self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "Agribuddy — Frost Alert",
                    "message": f"Frost risk tonight! Low: {low}°C. Check your plants.",
                    "notification_id": f"{DOMAIN}_frost_{today}",
                },
            )
        )
        self._frost_alerted_date = today
        _LOGGER.warning("Agribuddy: frost alert fired (low: %s°C)", low)

    # ── Accessors ─────────────────────────────────────────────────────────────

    def get_weather(self) -> dict:
        return (self.data or {}).get("weather", {})

    def get_plants(self) -> list:
        return (self.data or {}).get("plants", [])

    def get_plots(self) -> list:
        return (self.data or {}).get("plots", [])

    def is_frost_tonight(self) -> bool:
        return bool((self.data or {}).get("frost_tonight", False))

    def is_rain_today(self) -> bool:
        return bool((self.data or {}).get("rain_today", False))
