# Andel Energi for Home Assistant

A custom Home Assistant integration for [Andel Energi](https://andelenergi.dk) customers in Denmark. Provides electricity consumption tracking, real-time spot prices, green energy percentage, and long-term statistics for the HA Energy Dashboard.

## Features

| Sensor | Description | Update interval |
|--------|-------------|-----------------|
| **Daily Total** | Most recent complete day's consumption (kWh) | 60 min |
| **Monthly Total** | Most recent complete month's consumption (kWh) | 60 min |
| **Current Price** | Current electricity spot price (DKK/kWh) incl. transport & taxes | 15 min |
| **Green Energy** | Current renewable energy percentage in the grid (%) | 15 min |
| **Statistic** | Cumulative hourly consumption for the HA Energy Dashboard | 60 min |

### Sensor details

**Daily Total** (`sensor.andelenergi_daily_total`)
- State: latest complete day's total consumption in kWh
- Attributes: `daily_readings` — last 7 days of daily consumption

**Monthly Total** (`sensor.andelenergi_monthly_total`)
- State: latest complete month's total consumption in kWh
- Attributes: `monthly_readings` — all months of the current year

**Current Price** (`sensor.andelenergi_current_price`)
- State: current price in DKK/kWh (with transport & taxes)
- Attributes: `price_with_transport_and_taxes`, `price_without_transport_and_taxes`, `currency`, `time`, `forecast` (hourly price breakdown)

**Green Energy** (`sensor.andelenergi_green_energy`)
- State: current green/renewable energy percentage
- Attributes: `time`, `text`

**Statistic** (`sensor.andelenergi_statistic`)
- Imports hourly consumption as long-term statistics, compatible with the HA Energy Dashboard
- Data is typically delayed 1-3 days depending on your grid operator (DSO)

## Installation

### HACS (recommended)

1. Add this repository as a custom repository in HACS
2. Search for "Andel Energi" and install
3. Restart Home Assistant
4. Go to **Settings > Devices & Services > Add Integration > Andel Energi**

### Manual

1. Copy the `custom_components/andelenergi` folder to your Home Assistant `config/custom_components/` directory
2. Restart Home Assistant
3. Go to **Settings > Devices & Services > Add Integration > Andel Energi**

## Configuration

The integration uses a config flow. You will need:

- **Email** — your andelenergi.dk login email
- **Password** — your andelenergi.dk password

If your account has multiple addresses/metering points, you will be prompted to select which one to add. You can add the integration multiple times for multiple metering points.

## API documentation

This integration was built by reverse-engineering two sources:

1. **Web app** (`andelenergi.dk/min-side`) — HAR capture of the browser session. Uses `api.andelenergi.dk/service/web/` endpoints.
2. **Android app** (v1.33.1, decompiled with jadx) — Uses `api.andelenergi.dk/service/app/` endpoints with additional widget data (prices, green energy) not exposed in the web UI.

See [`openapi.yaml`](openapi.yaml) for the full OpenAPI 3.0 specification of all discovered endpoints.

### Authentication flow

```
1. GET  /service/web/v1/csrf           → { nonce }
2. POST /service/web/v1/auth/login     → { access_token, id_token, refresh_token, ... }
   Body: { email, password }
3. All subsequent requests include:
   - Authorization: Bearer {access_token}
   - X-CSRF-Token: {nonce}
   - IdToken: {id_token}
4. On 401 → POST /service/web/v1/auth/refresh to get new tokens
```

The Android app authenticates differently — it uses AWS Cognito SRP directly via the Amplify SDK, then calls `service/app/` endpoints. This integration uses the simpler web login flow, which appears to work with both `service/web/` and `service/app/` endpoints.

## Automation examples

**Run dishwasher when electricity is cheapest:**

```yaml
automation:
  - alias: "Notify cheapest electricity hour"
    trigger:
      - platform: state
        entity_id: sensor.andelenergi_current_price
    condition:
      - condition: numeric_state
        entity_id: sensor.andelenergi_current_price
        below: 1.0
    action:
      - service: notify.mobile_app
        data:
          title: "Cheap electricity now"
          message: "Price is {{ states('sensor.andelenergi_current_price') }} DKK/kWh"
```

**Run appliances when grid is greenest:**

```yaml
automation:
  - alias: "Green energy alert"
    trigger:
      - platform: numeric_state
        entity_id: sensor.andelenergi_green_energy
        above: 80
    action:
      - service: switch.turn_on
        target:
          entity_id: switch.washing_machine
```

## License

MIT

## Credits

Inspired by [homeassistant-eloverblik](https://github.com/JonasPed/homeassistant-eloverblik) by @JonasPed.
