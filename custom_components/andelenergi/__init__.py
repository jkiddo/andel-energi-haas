"""The Andel Energi integration."""
import logging
from datetime import timedelta

from homeassistant.util import Throttle
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .api import AndelEnergiApi, AndelEnergiAuthError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]

MIN_TIME_BETWEEN_UPDATES = timedelta(minutes=60)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up Andel Energi from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    email = entry.data["email"]
    password = entry.data["password"]
    metering_point = entry.data["metering_point"]

    api = AndelEnergiApi(email, password)
    await hass.async_add_executor_job(api.login)

    hass.data[DOMAIN][entry.entry_id] = HassAndelEnergi(api, metering_point)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        client = hass.data[DOMAIN].pop(entry.entry_id)
        client.close()

    return unload_ok


class HassAndelEnergi:
    """Wrapper around the Andel Energi API for Home Assistant."""

    def __init__(self, api: AndelEnergiApi, metering_point: str):
        self._api = api
        self._metering_point = metering_point

        self._hourly_data: list[dict] | None = None
        self._daily_data: list[dict] | None = None
        self._monthly_data: list[dict] | None = None
        self._daily_attrs: dict | None = None
        self._monthly_attrs: dict | None = None

        # Widget data (from app API)
        self._current_price: dict | None = None
        self._green_percentage: dict | None = None
        self._price_forecast: list[dict] | None = None

    def close(self):
        """Close the underlying API session."""
        self._api.close()

    @property
    def metering_point(self) -> str:
        return self._metering_point

    @property
    def daily_readings(self) -> list[dict] | None:
        return self._daily_data

    @property
    def monthly_readings(self) -> list[dict] | None:
        return self._monthly_data

    @property
    def hourly_readings(self) -> list[dict] | None:
        return self._hourly_data

    @property
    def daily_attributes(self) -> dict:
        return self._daily_attrs or {}

    @property
    def monthly_attributes(self) -> dict:
        return self._monthly_attrs or {}

    @property
    def current_price(self) -> dict | None:
        return self._current_price

    @property
    def green_percentage(self) -> dict | None:
        return self._green_percentage

    @property
    def price_forecast(self) -> list[dict] | None:
        return self._price_forecast

    @staticmethod
    def _get_latest_value(readings: list[dict] | None) -> float | None:
        """Get the most recent non-null reading value."""
        if not readings:
            return None
        for reading in reversed(readings):
            if reading.get("value") is not None:
                return round(reading["value"], 3)
        return None

    @property
    def latest_daily_total(self) -> float | None:
        return self._get_latest_value(self._daily_data)

    @property
    def latest_monthly_total(self) -> float | None:
        return self._get_latest_value(self._monthly_data)

    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    def update_consumption(self):
        """Fetch consumption data from Andel Energi."""
        _LOGGER.debug("Fetching consumption data from Andel Energi")
        try:
            hourly = self._api.get_consumption(
                self._metering_point, aggregation="hour"
            )
            self._hourly_data = [
                r for r in hourly.get("readings", []) if r.get("value") is not None
            ]

            daily = self._api.get_consumption(
                self._metering_point, aggregation="day"
            )
            self._daily_data = daily.get("readings", [])

            monthly = self._api.get_consumption(
                self._metering_point, aggregation="month"
            )
            self._monthly_data = monthly.get("readings", [])

            # Pre-compute attribute dicts so extra_state_attributes doesn't re-filter
            recent_daily = [
                r for r in self._daily_data if r.get("value") is not None
            ][-7:]
            self._daily_attrs = {
                "daily_readings": [
                    {"date": r["date_time"], "value": r["value"]}
                    for r in recent_daily
                ]
            } if recent_daily else {}

            non_null_monthly = [
                r for r in self._monthly_data if r.get("value") is not None
            ]
            self._monthly_attrs = {
                "monthly_readings": [
                    {"month": r["date_time"], "value": r["value"]}
                    for r in non_null_monthly
                ]
            } if non_null_monthly else {}

        except AndelEnergiAuthError:
            _LOGGER.warning(
                "Authentication failed while fetching consumption data. "
                "Check your email and password."
            )
        except Exception:
            _LOGGER.exception("Error fetching consumption data from Andel Energi")

        _LOGGER.debug("Done fetching consumption data from Andel Energi")

    MIN_TIME_BETWEEN_WIDGET_UPDATES = timedelta(minutes=15)

    @Throttle(MIN_TIME_BETWEEN_WIDGET_UPDATES)
    def update_widgets(self):
        """Fetch current price and green energy data from Andel Energi app API."""
        _LOGGER.debug("Fetching widget data from Andel Energi")
        try:
            combined = self._api.get_combined_widget(self._metering_point)
            self._current_price = combined.get("currentPrice")
            self._green_percentage = combined.get("currentGreenPercentage")
        except Exception:
            _LOGGER.debug(
                "Could not fetch combined widget data (app API may not be "
                "available with web credentials)"
            )

        try:
            price_full = self._api.get_price_full(self._metering_point)
            self._price_forecast = price_full.get("items", [])
        except Exception:
            _LOGGER.debug("Could not fetch price forecast data")

        _LOGGER.debug("Done fetching widget data from Andel Energi")
