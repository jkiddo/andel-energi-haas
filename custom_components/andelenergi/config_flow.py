"""Config flow for Andel Energi integration."""
import logging

import voluptuous as vol

from homeassistant import config_entries, core, exceptions

from .api import AndelEnergiApi, AndelEnergiAuthError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required("email"): str,
        vol.Required("password"): str,
    }
)


def _login_and_get_addresses(email: str, password: str) -> list[dict]:
    """Synchronous helper: login and fetch addresses in one executor call."""
    api = AndelEnergiApi(email, password)
    try:
        api.login()
        return api.get_addresses()
    finally:
        api.close()


async def validate_input(hass: core.HomeAssistant, data: dict) -> dict:
    """Validate credentials and return available addresses with metering points."""
    try:
        addresses = await hass.async_add_executor_job(
            _login_and_get_addresses, data["email"], data["password"]
        )
    except AndelEnergiAuthError as err:
        raise InvalidAuth() from err
    except Exception as err:
        raise CannotConnect() from err

    metering_points = []
    for address in addresses:
        for delivery in address.get("deliveries", []):
            mp_id = delivery["metering_point_id"]
            label = f"{address['display_address']} ({mp_id})"
            metering_points.append({"id": mp_id, "label": label})

    if not metering_points:
        raise NoMeteringPoints()

    return {"metering_points": metering_points}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Andel Energi."""

    VERSION = 1

    def __init__(self):
        self._user_data: dict | None = None
        self._metering_points: list[dict] | None = None

    async def async_step_user(self, user_input=None):
        """Step 1: Collect email and password."""
        errors = {}
        if user_input is not None:
            try:
                result = await validate_input(self.hass, user_input)
                self._user_data = user_input
                self._metering_points = result["metering_points"]

                if len(self._metering_points) == 1:
                    return await self._create_entry(self._metering_points[0]["id"])

                return await self.async_step_metering_point()

            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except NoMeteringPoints:
                errors["base"] = "no_metering_points"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_metering_point(self, user_input=None):
        """Step 2: Select metering point (if multiple)."""
        if user_input is not None:
            return await self._create_entry(user_input["metering_point"])

        mp_options = {
            mp["id"]: mp["label"] for mp in self._metering_points
        }

        return self.async_show_form(
            step_id="metering_point",
            data_schema=vol.Schema(
                {vol.Required("metering_point"): vol.In(mp_options)}
            ),
        )

    async def _create_entry(self, metering_point_id: str):
        """Create the config entry."""
        await self.async_set_unique_id(metering_point_id)
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=f"Andel Energi {metering_point_id}",
            data={
                "email": self._user_data["email"],
                "password": self._user_data["password"],
                "metering_point": metering_point_id,
            },
        )


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(exceptions.HomeAssistantError):
    """Error to indicate there is invalid auth."""


class NoMeteringPoints(exceptions.HomeAssistantError):
    """Error to indicate no metering points were found."""
