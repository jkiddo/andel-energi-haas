"""Platform for Andel Energi sensor integration."""
from datetime import datetime, timedelta, timezone
import logging

from homeassistant.const import UnitOfEnergy, PERCENTAGE
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import (
    DOMAIN as RECORDER_DOMAIN,
    async_import_statistics,
    get_last_statistics,
)
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMetaData,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from .__init__ import HassAndelEnergi
from .const import DOMAIN, CURRENCY_DKK_PER_KWH

_LOGGER = logging.getLogger(__name__)


def _parse_numeric(value) -> float | None:
    """Parse a numeric value from the API, handling locale strings like '2,47' or '62%'."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace("%", "").replace(",", ".").strip())
    except (ValueError, TypeError):
        return None


async def async_setup_entry(
    hass: HomeAssistant, config: ConfigEntry, async_add_entities
):
    """Set up the sensor platform."""
    andelenergi = hass.data[DOMAIN][config.entry_id]

    sensors = [
        AndelEnergiDailyTotal(andelenergi),
        AndelEnergiMonthlyTotal(andelenergi),
        AndelEnergiStatistic(andelenergi),
        AndelEnergiCurrentPrice(andelenergi),
        AndelEnergiGreenEnergy(andelenergi),
    ]

    async_add_entities(sensors)


class AndelEnergiDailyTotal(SensorEntity):
    """Sensor showing the most recent complete day's consumption."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    def __init__(self, client: HassAndelEnergi):
        self._data = client
        self._attr_name = "Andel Energi Daily Total"
        self._attr_unique_id = f"{client.metering_point}-daily-total"
        self._attr_native_value = None

    @property
    def extra_state_attributes(self):
        return self._data.daily_attributes

    def update(self):
        self._data.update_consumption()
        self._attr_native_value = self._data.latest_daily_total


class AndelEnergiMonthlyTotal(SensorEntity):
    """Sensor showing the most recent complete month's consumption."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    def __init__(self, client: HassAndelEnergi):
        self._data = client
        self._attr_name = "Andel Energi Monthly Total"
        self._attr_unique_id = f"{client.metering_point}-monthly-total"
        self._attr_native_value = None

    @property
    def extra_state_attributes(self):
        return self._data.monthly_attributes

    def update(self):
        self._data.update_consumption()
        self._attr_native_value = self._data.latest_monthly_total


class AndelEnergiCurrentPrice(SensorEntity):
    """Sensor showing the current electricity spot price.

    Discovered from Android app: GET service/app/v1/widgets/current-combined/{mp_id}
    Returns price with and without transport & taxes.
    """

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = CURRENCY_DKK_PER_KWH
    _attr_icon = "mdi:currency-usd"
    _attr_suggested_display_precision = 2

    def __init__(self, client: HassAndelEnergi):
        self._data = client
        self._attr_name = "Andel Energi Current Price"
        self._attr_unique_id = f"{client.metering_point}-current-price"
        self._attr_native_value = None
        self._cached_attrs: dict = {}

    @property
    def extra_state_attributes(self):
        return self._cached_attrs

    def update(self):
        self._data.update_widgets()
        price = self._data.current_price
        if price:
            self._attr_native_value = _parse_numeric(
                price.get("valueWithTransportAndTaxes")
            )
            attrs = {
                "price_with_transport_and_taxes": price.get(
                    "valueWithTransportAndTaxes"
                ),
                "price_without_transport_and_taxes": price.get(
                    "valueWithoutTransportAndTaxes"
                ),
                "currency": price.get("currency"),
                "time": price.get("time"),
                "text": price.get("text"),
            }
            forecast = self._data.price_forecast
            if forecast:
                attrs["forecast"] = [
                    {
                        "time": item.get("time"),
                        "price_with_taxes": item.get("valueWithTransportAndTaxes"),
                        "price_without_taxes": item.get(
                            "valueWithoutTransportAndTaxes"
                        ),
                        "start": item.get("startDate"),
                        "end": item.get("endDate"),
                        "is_current": item.get("isCurrentTimePeriod", False),
                    }
                    for item in forecast
                ]
            self._cached_attrs = attrs
        else:
            self._attr_native_value = None
            self._cached_attrs = {}


class AndelEnergiGreenEnergy(SensorEntity):
    """Sensor showing the current green/renewable energy percentage.

    Discovered from Android app: GET service/app/v1/widgets/current-combined/{mp_id}
    Returns current percentage of renewable energy in the grid.
    """

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = "mdi:leaf"

    def __init__(self, client: HassAndelEnergi):
        self._data = client
        self._attr_name = "Andel Energi Green Energy"
        self._attr_unique_id = f"{client.metering_point}-green-energy"
        self._attr_native_value = None

    @property
    def extra_state_attributes(self):
        attrs = {}
        green = self._data.green_percentage
        if green:
            attrs["time"] = green.get("time")
            attrs["text"] = green.get("text")
        return attrs

    def update(self):
        self._data.update_widgets()
        green = self._data.green_percentage
        if green:
            self._attr_native_value = _parse_numeric(green.get("value"))
        else:
            self._attr_native_value = None


class AndelEnergiStatistic(SensorEntity):
    """Imports hourly consumption as long-term statistics for the Energy Dashboard.

    Appends new readings that are newer than the last imported statistic.
    Checks every hour so late-arriving data (delayed up to ~5 days) gets
    picked up as soon as the API makes it available.
    """

    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, client: HassAndelEnergi):
        self._attr_name = "Andel Energi Statistic"
        self._attr_unique_id = f"{client.metering_point}-statistic"
        self._client = client
        self._attr_native_value = 0

    async def async_will_remove_from_hass(self) -> None:
        await get_instance(self.hass).async_clear_statistics([self.entity_id])

    async def async_update(self):
        # update_consumption is @Throttle-guarded; safe to call from every sensor
        await self.hass.async_add_executor_job(self._client.update_consumption)

        readings = self._client.hourly_readings
        if not readings:
            _LOGGER.debug("No hourly data available from Andel Energi")
            return

        last_stat = await self._get_last_stat(self.hass)
        await self._insert_statistics(readings, last_stat)
        self._last_update = now

    async def _insert_statistics(self, readings: list[dict], last_stat):
        total = last_stat["sum"] if last_stat else 0
        last_ts = last_stat["start"] if last_stat else 0

        statistics: list[StatisticData] = []

        for reading in sorted(readings, key=lambda r: r["date_time"]):
            value = reading.get("value")
            if value is None:
                continue

            start = datetime.fromisoformat(reading["date_time"])
            # Only append readings newer than what we've already imported
            if start.timestamp() <= last_ts:
                continue

            total += value
            statistics.append(StatisticData(start=start, sum=total))

        metadata = StatisticMetaData(
            name=self._attr_name,
            source=RECORDER_DOMAIN,
            statistic_id=self.entity_id,
            unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            has_mean=False,
            has_sum=True,
        )

        if statistics:
            async_import_statistics(self.hass, metadata, statistics)
            self._attr_native_value = total
            _LOGGER.debug(
                "Imported %d new hourly statistics (last: %s, sum: %.3f)",
                len(statistics),
                statistics[-1].start,
                total,
            )
        else:
            _LOGGER.debug("No new statistics to import from Andel Energi")

    async def _get_last_stat(self, hass: HomeAssistant):
        last_stats = await get_instance(hass).async_add_executor_job(
            get_last_statistics, hass, 1, self.entity_id, True, {"sum"}
        )
        if self.entity_id in last_stats and last_stats[self.entity_id]:
            return last_stats[self.entity_id][0]
        return None
