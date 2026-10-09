# Changelog

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
