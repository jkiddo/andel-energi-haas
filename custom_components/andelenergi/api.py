"""API client for Andel Energi."""
import logging
from datetime import datetime, timezone

import requests

from .const import API_BASE_URL, APP_API_BASE_URL

_LOGGER = logging.getLogger(__name__)


class AndelEnergiApiError(Exception):
    """General API error."""


class AndelEnergiAuthError(AndelEnergiApiError):
    """Authentication error."""


class AndelEnergiApi:
    """Client for the Andel Energi web API."""

    def __init__(self, email: str, password: str):
        self._email = email
        self._password = password
        self._session = requests.Session()
        self._session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": "https://andelenergi.dk",
            "Referer": "https://andelenergi.dk/",
        })
        self._csrf_token: str | None = None
        self._access_token: str | None = None
        self._id_token: str | None = None

    def close(self):
        """Close the underlying HTTP session."""
        self._session.close()

    def _apply_auth_headers(self):
        """Apply current auth tokens to session headers."""
        headers = {}
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        if self._csrf_token:
            headers["X-CSRF-Token"] = self._csrf_token
        if self._id_token:
            headers["IdToken"] = self._id_token
        self._session.headers.update(headers)

    def _refresh_csrf(self):
        """Fetch a fresh CSRF nonce."""
        resp = self._session.get(f"{API_BASE_URL}/v1/csrf")
        resp.raise_for_status()
        self._csrf_token = resp.json()["nonce"]
        if "X-CSRF-Token" in resp.headers:
            self._csrf_token = resp.headers["X-CSRF-Token"]

    def _update_csrf_from_response(self, resp: requests.Response):
        """Update CSRF token from response header if present."""
        if "X-CSRF-Token" in resp.headers:
            self._csrf_token = resp.headers["X-CSRF-Token"]

    def _authenticate(self, url: str, body: dict) -> dict:
        """Shared logic for login and refresh: POST to auth endpoint, store tokens."""
        self._refresh_csrf()
        self._apply_auth_headers()
        resp = self._session.post(url, json=body)
        if resp.status_code in (401, 403):
            raise AndelEnergiAuthError("Invalid email or password")
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data["access_token"]
        self._id_token = data["id_token"]
        self._update_csrf_from_response(resp)
        self._apply_auth_headers()
        return data

    def login(self) -> dict:
        """Authenticate with email and password. Returns user info."""
        return self._authenticate(
            f"{API_BASE_URL}/v1/auth/login",
            {"email": self._email, "password": self._password},
        )

    def refresh_tokens(self) -> dict:
        """Refresh the current session tokens."""
        try:
            return self._authenticate(
                f"{API_BASE_URL}/v1/auth/refresh",
                {"platform": "Website"},
            )
        except AndelEnergiAuthError:
            return self.login()

    def _get(self, url: str, params: dict | None = None) -> requests.Response:
        """Make an authenticated GET request with automatic retry on 401."""
        resp = self._session.get(url, params=params)
        self._update_csrf_from_response(resp)
        if resp.status_code == 401:
            self.refresh_tokens()
            resp = self._session.get(url, params=params)
            self._update_csrf_from_response(resp)
        resp.raise_for_status()
        return resp

    def get_addresses(self) -> list[dict]:
        """Get all addresses and metering points for the user."""
        return self._get(f"{API_BASE_URL}/v1/addresses").json()

    def get_consumption(
        self,
        metering_point_id: str,
        aggregation: str = "hour",
        unit: str = "kWh",
        commodity: str = "power",
    ) -> dict:
        """Get consumption data for a metering point."""
        return self._get(
            f"{API_BASE_URL}/v3/consumption/{metering_point_id}",
            params={
                "aggregation": aggregation,
                "compare": "false",
                "unit": unit,
                "commodity": commodity,
            },
        ).json()

    def get_consumption_for_date(
        self,
        metering_point_id: str,
        date: datetime,
        target_aggregation: str = "hour",
        source_aggregation: str = "day",
        unit: str = "kWh",
        commodity: str = "power",
    ) -> dict:
        """Get consumption at a specific aggregation by drilling down from a date.

        The v3 API returns a default window for direct aggregation calls which
        can be weeks old for hourly data. This method uses the /aggregate
        endpoint to drill into a specific date, mimicking how the web UI works.
        """
        return self._get(
            f"{API_BASE_URL}/v3/consumption/{metering_point_id}/aggregate",
            params={
                "compare": "false",
                "unit": unit,
                "commodity": commodity,
                "current_aggregation": source_aggregation,
                "new_aggregation": target_aggregation,
                "current_date_time": date.isoformat(),
            },
        ).json()

    # --- App API endpoints (discovered from Android app decompilation) ---

    def get_combined_widget(self, metering_point_id: str) -> dict:
        """Get current electricity price and green energy percentage in one call.

        Returns dict with 'currentPrice' and 'currentGreenPercentage' keys.
        currentPrice has: currency, text, time, valueWithTransportAndTaxes,
                         valueWithoutTransportAndTaxes
        currentGreenPercentage has: text, time, value
        """
        return self._get(
            f"{APP_API_BASE_URL}/v1/widgets/current-combined/{metering_point_id}",
        ).json()

    def get_price_full(
        self, metering_point_id: str, aggregation: str = "hour"
    ) -> dict:
        """Get full hourly price data with forecast.

        Returns dict with 'items' list of PriceItem objects, each having:
        time, valueWithTransportAndTaxes, valueWithoutTransportAndTaxes,
        isCurrentTimePeriod, startDate, endDate
        """
        return self._get(
            f"{APP_API_BASE_URL}/v1/widgets/current-price/{metering_point_id}/full",
            params={"aggregation": aggregation},
        ).json()

    def get_green_energy_full(self, metering_point_id: str) -> dict:
        """Get full hourly green energy percentage data.

        Returns dict with 'items' list of GreenEnergyItem objects, each having:
        time, value, isCurrentTimePeriod, startDate, endDate
        """
        return self._get(
            f"{APP_API_BASE_URL}/v1/widgets/current-green-percentage/{metering_point_id}/full",
        ).json()

    def get_co2_and_energy_distribution(self, metering_point_id: str) -> dict:
        """Get CO2 and energy source distribution data."""
        return self._get(
            f"{APP_API_BASE_URL}/v1/co2-and-energy-distribution/page/{metering_point_id}",
        ).json()
