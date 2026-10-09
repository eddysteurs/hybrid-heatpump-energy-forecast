# Hybrid Heatpump Energy Forecast

Hour-by-hour forecast (48 h) of heat demand, heat pump electricity and gas for a
hybrid heating system (heat pump + gas boiler), based on the Open-Meteo weather
forecast. Full documentation: see the
[README](https://github.com/eddysteurs/hybrid-heatpump-energy-forecast#readme).

## Quick start

1. Fill in the entities you have below (all optional) and start the app.
2. On the first start the app creates its helpers (`input_number.hybrid_*` and the
   switch logger helpers) with default values. Tune them under
   *Settings → Devices & services → Helpers*; they are read every hour.
3. Import the **gas switch logger** blueprint from the repository so the app
   can learn the real switch-to-gas temperature.

## Options

| Option | Description |
|---|---|
| `boiler_efficiency` | Gas boiler efficiency, default 0.92 |
| `create_helpers` | Create missing helpers on start (default on) |
| `indoor_temp_entity` | Indoor temperature sensor |
| `hp_energy_today_entity` | Heat pump electricity today in kWh (resets at midnight) |
| `gas_energy_today_entity` | Gas today in kWh (resets at midnight) |
| `energy_cost_ratio_entity` | Electricity/gas price ratio set in the hybrid controller |
| `switch_history_entity` | History written by the blueprint (default `input_text.hybrid_gas_switch_history`) |
| `sensor_prefix` | Output sensor prefix (default `hybrid`) |
| `timezone` | Leave empty to use Home Assistant's |
| `ha_url` / `ha_token` | Only when running outside Home Assistant OS |

## Output

Sensors `sensor.hybrid_electricity_today|tomorrow|48h`, `sensor.hybrid_gas_today|tomorrow|48h`,
`sensor.hybrid_heat_demand_today|tomorrow`, `sensor.hybrid_forecast_temperature_48h`,
`sensor.hybrid_simulated_indoor_temperature`. The `48h` sensors carry an `hourly`
attribute with the cumulative series.

The log tab shows a summary of every run. Tomorrow's forecast and, a day later,
the actual use are kept in `forecast_log.json` in this app's folder of the
`addon_configs` share.
