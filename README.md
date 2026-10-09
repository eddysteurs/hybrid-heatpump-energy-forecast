# Hybrid Heatpump Energy Forecast for Home Assistant

A Home Assistant **app** (add-on) plus an **automation blueprint** that forecast,
hour by hour for the next 48 hours, how much **heat** your house needs and how
much of it your **hybrid heating system** (air/water heat pump + gas boiler)
will deliver with **electricity** and with **gas**.

- Uses the free [Open-Meteo](https://open-meteo.com) forecast (temperature and
  solar radiation), no API key needed.
- Physics-based model (heat loss, internal and solar gains, thermal mass, COP
  curve, boiler efficiency) with parameters you can tune live from Home Assistant helpers.
- **Learns the real switch-over temperature** of your hybrid controller: the
  blueprint records every switch to gas from your gas meter, and the app uses
  the median of the last switches as its bivalence temperature.
- Publishes sensors for today, tomorrow and a cumulative 48 h hourly series
  (usable as an extra load forecast, e.g. for battery planning with Predbat).
- Keeps a forecast-vs-actual log and prints a readable summary every hour.

> **HACS?** HACS distributes integrations, cards and themes, not Home Assistant
> apps. This repository is an **app repository**: you add it to the app store
> in Home Assistant itself (see Installation). The blueprint is imported with
> the button below.

---

## Contents

- [What you get](#what-you-get)
- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Helpers (model parameters)](#helpers-model-parameters)
- [Output sensors](#output-sensors)
- [The log](#the-log)
- [Calibrating for your house](#calibrating-for-your-house)
- [Limitations](#limitations)
- [Upgrading from 1.x](#upgrading-from-1x)

## What you get

| Part | Path | What it does |
|---|---|---|
| App | [`hybrid_heatpump_forecast/`](hybrid_heatpump_forecast) | Runs every hour, publishes the forecast sensors, creates missing helpers |
| Blueprint | [`blueprints/automation/hybrid_gas_switch_logger.yaml`](blueprints/automation/hybrid_gas_switch_logger.yaml) | Records each switch to gas / back to heat pump with the outdoor temperature |
| Docs | [`docs/calibration.md`](docs/calibration.md) | How to fit the parameters to your house and choose the energy cost ratio |

## How it works

For every hour of the next 48 hours:

```
free heat      = internal gains + solar_gain_m2 × radiation
heat demand    = heat_loss × (setpoint − T_outdoor) − free heat      (≥ 0)
                 + recovery when the (simulated) indoor temperature is below setpoint
T_outdoor ≥ bivalence → heat pump up to hp_max_thermal_kw, boiler tops up the rest
T_outdoor <  bivalence → boiler only (up to boiler_max_kw)
electricity    = heat pump heat / COP(T_outdoor)     COP linear between −7 °C and +7 °C
gas            = boiler heat / boiler efficiency
```

The **bivalence temperature** is where the hybrid controller hands over to gas.
That depends on the controller's own logic (for Bosch/Buderus/Nefit hybrids:
the *energy cost ratio* setting), so instead of guessing it, the
**gas switch logger** blueprint watches the gas meter:

- a second gas meter step within 20 min → the heating switched to gas: store the
  outdoor temperature, the energy cost ratio and whether the compressor was still
  running (then gas is only *assisting*, marked `p`);
- no new gas meter reading for 45 min → back on the heat pump.

The history (`input_text.hybrid_gas_switch_history`, newest first, e.g.
`5.9@1.5,8.1@1.5p,6.0@1.5`) is read by the app: with at least 3 real switches
at the **current** ratio it uses the median of the last 5 as bivalence;
otherwise the `hybrid_bivalence_temp` helper.

### Results in the author's house

Backtest over 312 days (hourly Open-Meteo history against the measured daily
use) of the original model versus this one:

| | electricity error (MAE) | gas error (MAE) |
|---|---|---|
| original model | 2.81 kWh/day | 9.3 kWh/day |
| this model | 2.37 kWh/day | 6.5 kWh/day |

Measured heat pump COP (heat delivered / compressor electricity, EMS-ESP counters)
in that house, for reference:

| daily mean outdoor | COP incl. standby | COP excl. ~2.4 kWh/day standby |
|---|---|---|
| 4–6 °C | 2.46 | 3.26 |
| 6–8 °C | 2.73 | 3.18 |
| 8–10 °C | 2.94 | 3.37 |
| 10–12 °C | 3.00 | 3.55 |

## Requirements

- **Home Assistant OS or Supervised** (apps need the Supervisor).
  `aarch64` and `amd64` are supported.
- Internet access from Home Assistant to `api.open-meteo.com`.
- A hybrid heating system: heat pump + gas boiler, where the gas is used for
  space heating only (if the boiler also makes hot water, the switch logger will
  also log hot-water runs; see [Limitations](#limitations)).

### Sensors

| Purpose | Required? | Example (author's setup) | Notes |
|---|---|---|---|
| Gas meter, cumulative | for the switch logger | `sensor.p1_meter_…_total_gas` (HomeWizard P1) | any increasing gas meter in m³ or kWh (P1/DSMR, HomeWizard, …) |
| Outdoor temperature of the hybrid controller | for the switch logger | `sensor.boiler_outside_temperature` (EMS-ESP) | use the controller's own sensor: that is what it switches on |
| Compressor running | optional | `binary_sensor.boiler_hp_compressor` (EMS-ESP) | marks gas that only assists the heat pump |
| Energy cost ratio of the controller | optional | `number.thermostat_energy_cost_ratio` (EMS-ESP) | switches are stored per ratio, so changing it relearns |
| Heat pump electricity **today** (kWh, resets at midnight) | optional | `sensor.dag_warmtepomp_verwarming` | e.g. a *Utility Meter* helper (daily cycle) on the heat pump's energy sensor; used for "today total", the 48 h series and forecast-vs-actual |
| Gas **today** in kWh (resets at midnight) | optional | `sensor.daily_gas_in_kwh_dag` | e.g. a daily Utility Meter on the gas meter × calorific value (≈ 10.5–11.4 kWh/m³) |
| Indoor temperature | optional | `sensor.kitchen_temperature` | start point of the thermal simulation |

### Integrations used in the reference setup

- **[EMS-ESP](https://emsesp.org)** for Bosch / Buderus / Nefit hybrids
  (outdoor temperature, compressor, energy cost ratio, heat/electricity counters).
  Other brands work too: map the equivalent entities.
- A **P1 / DSMR** or **HomeWizard** integration for the gas meter.
- Optional: **[Predbat](https://github.com/springfall2008/batpred)** or another
  planner that can read an hourly cumulative series.

## Installation

1. **Add this repository to the app store**

   [![Add repository](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Feddysteurs%2Fhybrid-heatpump-energy-forecast)

   or *Settings → Apps → App store → ⋮ → Repositories* and add
   `https://github.com/eddysteurs/hybrid-heatpump-energy-forecast`.

2. **Install "Hybrid Heatpump Energy Forecast"**, open its *Configuration* tab and
   fill in the entities you have (all optional, see [Configuration](#configuration)).
   Start it. On the first start it creates the helpers it needs (option
   `create_helpers`) and publishes the first forecast; check the *Log* tab.

3. **Import the blueprint**

   [![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Feddysteurs%2Fhybrid-heatpump-energy-forecast%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fhybrid_gas_switch_logger.yaml)

   and create an automation from it: pick your gas meter, the controller's
   outdoor temperature and (optional) compressor and energy cost ratio entities.
   The helper inputs default to the helpers the app created.

4. **Calibrate** the model parameters for your house: see
   [docs/calibration.md](docs/calibration.md). The defaults are the values
   fitted on the author's house and are only a starting point.

## Configuration

| Option | Default | Description |
|---|---|---|
| `boiler_efficiency` | `0.92` | Gas boiler efficiency (heat out / gas in) |
| `create_helpers` | `true` | Create missing helpers on start |
| `indoor_temp_entity` | – | Indoor temperature sensor |
| `hp_energy_today_entity` | – | Daily heat pump electricity (kWh, resets at midnight) |
| `gas_energy_today_entity` | – | Daily gas (kWh, resets at midnight) |
| `energy_cost_ratio_entity` | – | Controller's electricity/gas price ratio |
| `switch_history_entity` | `input_text.hybrid_gas_switch_history` | History written by the blueprint |
| `sensor_prefix` | `hybrid` | Output sensors are `sensor.<prefix>_…` |
| `timezone` | HA time zone | |
| `ha_url`, `ha_token` | – | Only when running outside Home Assistant OS |

Location (for the weather forecast) comes from your Home Assistant settings.

## Helpers (model parameters)

Read every run, so you can tune them live (no restart). Created automatically
when missing; the legacy names of version 1.x are still accepted.

| Helper | Default | Unit | Meaning |
|---|---|---|---|
| `input_number.hybrid_heat_loss` | 0.38 | kW/K | heat loss coefficient of the house (incl. ventilation) |
| `input_number.hybrid_indoor_setpoint` | 20.4 | °C | indoor temperature the model heats to |
| `input_number.hybrid_internal_gains_kw` | 0.5 | kW | heat from people and appliances |
| `input_number.hybrid_solar_gain_m2` | 3.0 | m² | effective window area: solar gain = m² × radiation |
| `input_number.hybrid_bivalence_temp` | 6.2 | °C | switch-to-gas temperature until enough switches are learned |
| `input_number.hybrid_hp_max_thermal_kw` | 5.0 | kW | maximum heat output of the heat pump |
| `input_number.hybrid_hp_cop_plus7` | 3.55 | – | COP at +7 °C outdoor |
| `input_number.hybrid_hp_cop_minus7` | 3.0 | – | COP at −7 °C outdoor |
| `input_number.hybrid_boiler_max_kw` | 24 | kW | maximum boiler output |
| `input_number.hybrid_thermal_capacity` | 20 | kWh/K | thermal mass of the house |
| `input_number.hybrid_recovery_hours` | 4 | h | how fast the model recovers a too-low indoor temperature |

Helpers used by the switch logger blueprint:

| Helper | Type | Content |
|---|---|---|
| `input_text.hybrid_gas_switch_history` | text, max 255 | switches to gas, newest first: `5.9@1.5`, `8.1@1.5p` |
| `input_boolean.hybrid_on_gas` | toggle | on while the heating runs on gas |
| `input_datetime.hybrid_last_gas_step` | date + time | last gas meter step |
| `input_number.hybrid_gas_switch_temp` | °C | outdoor temperature at the last switch to gas |
| `input_number.hybrid_hp_return_temp` | °C | outdoor temperature at the last return to the heat pump |

If `create_helpers` cannot create them (e.g. an old Home Assistant version),
create them by hand under *Settings → Devices & services → Helpers* with exactly these names.

## Output sensors

| Sensor | Unit | Content |
|---|---|---|
| `sensor.hybrid_electricity_today` | kWh | heat pump electricity for the rest of today |
| `sensor.hybrid_electricity_tomorrow` | kWh | heat pump electricity tomorrow (00:00–24:00) |
| `sensor.hybrid_gas_today` / `_tomorrow` | kWh | gas, same periods |
| `sensor.hybrid_heat_demand_today` / `_tomorrow` | kWh | heat delivered to the house (thermal), same periods |
| `sensor.hybrid_electricity_48h` | kWh | cumulative; attribute `hourly` = list of `{last_updated, energy}` starting at today's actual use; attribute `model` = parameters used |
| `sensor.hybrid_gas_48h` | kWh | cumulative gas, attribute `hourly` |
| `sensor.hybrid_forecast_temperature_48h` | °C | attribute `hourly` with temperature and radiation per hour |
| `sensor.hybrid_simulated_indoor_temperature` | °C | simulated indoor temperature after 48 h |

Heat demand is thermal energy: electricity = heat / COP, so heat demand is
typically 3–4 × the heat pump electricity.

## The log

Every run prints a summary (app *Log* tab), for example:

```
=== Hybrid forecast run 2026-10-09 12:57 (v2.0.0) ===
Parameters : heat loss 0.38 kW/K | setpoint 20.4 °C | gains 0.50 kW + sun 3.0 m² | balance temp 19.1 °C (no heating above, without sun)
             HP max 5.0 kW, COP 3.00 @-7 °C .. 3.55 @+7 °C (at 10 °C: 3.67) | boiler max 24 kW, efficiency 0.92 | thermal mass 20 kWh/K, recovery 4.0 h
Bivalence  : 6.2 °C from input_number.bivalence_temp (only 0 recorded switch(es) at ratio 1.5; 3 needed to learn)
Now        : indoor 20.78 °C (sensor.kitchen_temperature) | today so far: HP 6.92 kWh elec, gas 0.0 kWh
Weather    : Open-Meteo 51.20,4.40, 48 h from Fri 12:00 | now 10.9 °C, 13 W/m²
Today rest : 12 h | outdoor 10.9 .. 15.6 °C, mean 13.8 °C, sun 0.1 kWh/m² | heat 13.3 kWh = HP 13.3 + boiler 0.0 | elec 3.44 kWh (COP 3.9, 8 h on) | gas 0.0 kWh (0 h on)
Tomorrow   : 24 h | outdoor 10.0 .. 13.7 °C, mean 11.6 °C, sun 1.4 kWh/m² | heat 64.1 kWh = HP 64.1 + boiler 0.0 | elec 17.24 kWh (COP 3.7, 24 h on) | gas 0.0 kWh (0 h on)
```

Once switches are recorded the `Bivalence` line reads e.g.
`learned 4.9 °C = median of last 4 switches to gas at ratio 1.5: 5.9, 4.6, 4.8, 5.1`.
From the second day on, a `Yesterday` line compares the forecast with the actual
use, and after 3 days an `Accuracy` line shows the running bias and error.

Tomorrow's forecast is also kept in `forecast_log.json` (last 30 days) in the
app's config folder (`/addon_configs/<app slug>/` on the Samba share), together
with the actual use once that day is over.

## Calibrating for your house

See **[docs/calibration.md](docs/calibration.md)**: fitting heat loss and gains
from gas-only days, measuring the real COP from the heat pump's counters, tuning
the solar factor with the accuracy line, and choosing the energy cost ratio of
the hybrid controller (including the effect of a home battery and time-of-use tariffs).

## Limitations

- One heating zone, one weather point; no separate hot-water model.
- The switch logger assumes **all gas is space heating**. With a gas combi boiler
  for hot water, tap events will also be logged as switches.
- The COP is a straight line between −7 and +7 °C (extrapolated outside, minimum 1.5);
  flow temperature, defrost and part-load cycling are not modelled separately.
- The forecast is only as good as the weather forecast and the parameters.

## Upgrading from 1.x

Version 2 reads the new `input_number.hybrid_*` helpers but still accepts the
1.x names (`input_number.heat_loss`, `input_number.bivalence_temp`, …), so an
existing setup keeps working. It talks to Home Assistant through the Supervisor,
so `ha_url` / `ha_token` can be removed.

## License

MIT, see [LICENSE](LICENSE).
