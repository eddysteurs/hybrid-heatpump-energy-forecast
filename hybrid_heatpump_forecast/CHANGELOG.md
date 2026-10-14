# Changelog

## 2.1.1
- Fix: forecast-vs-actual took the day's maximum of the daily counters, which
  included the previous day's value carried over at midnight. A day with lower
  use than the day before got the previous day's total as "actual". Now the
  last value before midnight is used.

## 2.1.0
- New option `weather_model`: choose the Open-Meteo model (empty = best_match).
- New option `outdoor_temp_entity`: at start and once a day after 07:00 the log
  compares 7 Open-Meteo models (best_match, KNMI HARMONIE, Météo-France AROME,
  DWD ICON, ECMWF, UKMO, GFS) with the measured outdoor temperature over the last
  3 days, with error and bias for nights (20-08 h) and all hours. Weather
  models are often 2-4 °C too warm on clear, calm nights.

## 2.0.3
- Fix: an indoor sensor above the setpoint (sun, cooking, morning boost in one
  room) made the model forecast no heating at all for many hours. The
  simulation now starts at the setpoint when the room is warmer, and heat
  demand follows "hold the setpoint + proportional recovery" without the
  on/off gate, as a weather-compensated controller does.

## 2.0.2
- Gas switch logger blueprint: the compressor input now also accepts a status
  sensor (any state other than off = running), e.g. EMS-ESP
  `sensor.boiler_compressor_activity` (heating / defrost / off). On some
  Bosch/Buderus hybrids `binary_sensor.boiler_hp_compressor` stays off while the
  compressor runs, so gas that only assisted the heat pump (defrost, morning
  warm-up) was wrongly learned as a switch to gas.
- Calibration notes: lower `bivalence_temp` after lowering the energy cost
  ratio; account for night setback in the setpoint.

## 2.0.1
- The sensor options (indoor temperature, heat pump / gas today, energy cost
  ratio) are now shown on the Configuration tab by default instead of hidden
  under "Show unused optional configuration options".
- The log warns at start for every sensor option that is not set and says what
  is affected (e.g. the 48 h series then starts at 0).

## 2.0.0
- First public version.
- Uses the Supervisor API: no long-lived token or URL needed.
- Location and time zone from Home Assistant when not set.
- Model parameters from `input_number.hybrid_*` helpers, falling back to the
  legacy (unprefixed) names and then to built-in defaults; missing helpers are
  created on start (option `create_helpers`).
- Entity mapping (indoor temperature, heat pump / gas counters, energy cost
  ratio) is configurable.
- Bivalence (switch-to-gas) temperature learned from the gas switch logger
  blueprint: median of the last 5 real switches at the current energy cost ratio.

## 1.8.0
- Learned bivalence from recorded switches.

## 1.7.x
- Readable per-run summary in the log, forecast vs actual in
  `/addon_configs/<app>/forecast_log.json`, no double runs at the top of the hour.

## 1.7.0
- Internal and solar gains, separate boiler capacity, boiler tops up above the
  bivalence point, weather hours aligned on timestamps, "tomorrow" = tomorrow only,
  heat demand sensors. Backtest on 312 days: electricity MAE 2.81 -> 2.37 kWh/day,
  gas MAE 9.3 -> 6.5 kWh/day.
