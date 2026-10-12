# Calibrating the model for your house

The defaults were fitted on one house (Flanders, Belgium, Oct 2025 – Oct 2026,
heat pump about 5 kW thermal, radiators designed for 60 °C, buffer vessel).
For your house, fit at least `heat_loss`, the gains and the COP. You need
daily data for a heating season; long-term statistics in Home Assistant or a
time-series database (InfluxDB / VictoriaMetrics) both work.

Work with **daily** values: daily mean outdoor temperature, daily heat pump
electricity, daily gas (kWh), and if available the heat pump's own counters
(heat delivered, compressor electricity).

## 1. Heat loss and gains: from gas-only days

On days when only the boiler heats (heat pump off, usually the coldest days),
the heat delivered is simply `gas_kWh × boiler_efficiency`. No COP is involved,
which makes these days the cleanest measurement of the house itself.

1. Take all days with heat pump electricity ≈ 0 and gas > 20 kWh.
2. Convert to mean heat power: `P = gas_kWh × efficiency / 24` (kW).
3. Fit a straight line `P = a + b × T_outdoor` (spreadsheet: `LINEST`/trendline).
4. `heat_loss = −b` (kW/K). The **balance temperature** (no heating needed) is
   `T_balance = a / heat_loss`.
5. `internal_gains_kw ≈ heat_loss × (setpoint − T_balance)`, minus a bit for the
   average sun on those (winter) days.

Reference house: 37 gas-only days → heat loss 0.43 kW/K, balance temperature
16.7 °C. The final hourly fit (step 4) settled on 0.38 kW/K with 0.5 kW gains
plus solar gains.

## 2. COP: from the heat pump's own counters

If your controller exposes heat delivered and compressor electricity (EMS-ESP:
`sensor.boiler_total_energy_supplied_heating` and
`sensor.boiler_energy_consumption_compressor_heating`), compute per day
`COP = heat / electricity` and average per 2 °C outdoor band.

Watch out for **standby consumption**: the reference heat pump used ~2.4 kWh/day
even on days it delivered no heat. For the forecast (total electricity) use the
COP including standby; for deciding *when the heat pump is cheaper than gas*
use the COP excluding standby (you pay the standby anyway).

Reference house:

| daily mean outdoor | COP incl. standby | COP excl. standby |
|---|---|---|
| 4–6 °C | 2.46 | 3.26 |
| 6–8 °C | 2.73 | 3.18 |
| 8–10 °C | 2.94 | 3.37 |
| 10–12 °C | 3.00 | 3.55 |
| 12–14 °C | 3.11 | 4.00 |

Set `hp_cop_plus7` and `hp_cop_minus7` so the straight line matches your
measured values where the heat pump actually runs.

## 3. Solar gain and fine-tuning: with the accuracy line

Start with `solar_gain_m2` = 3 m² (roughly 10–20 % of the south-facing glass).
After a couple of weeks look at the `Accuracy` line in the app log and at
`forecast_log.json`:

- Forecast too **high** on sunny mild days (spring/autumn) → raise `solar_gain_m2`.
- Too high on all mild days, sunny or not → raise `internal_gains_kw` a little.
- Too low on cold days → raise `heat_loss`.
- Electricity off but heat right → adjust the COP values.

Change one parameter at a time; the helpers are read every hour.

## 4. Bivalence: let the switch logger learn it

Import the blueprint and leave it running. Each real switch to gas is stored
with the outdoor temperature and the energy cost ratio; after 3 switches at the
current ratio the app uses the median of the last 5. Until then it uses
`hybrid_bivalence_temp`. Changing the ratio on the controller automatically
starts a new learning series.

When you change the ratio, also set `hybrid_bivalence_temp` by hand to a first
guess for the new ratio; otherwise the forecast keeps using the old switch
point until 3 new switches are learned. Reference house: at ratio 1.7 the
switch was at 6.2 °C; after lowering to 1.5 the heat pump ran alone through a
night down to 2.4 °C, so the helper was set to 2.0 °C.

Not every gas use is a switch. Hybrid controllers also fire the boiler briefly
**next to** the running heat pump, typically right after a defrost or during
the morning warm-up from a night setback. The logger marks these with `p`
(assist) when the compressor input shows the heat pump running, and they are
not learned. Use a compressor entity that really follows the compressor: on the
reference Bosch, `binary_sensor.boiler_hp_compressor` stayed off all night, while
`sensor.boiler_compressor_activity` showed heating / defrost / off correctly.
If a wrong entry was learned, edit the history helper and add `p` to it.

## 4b. Night setback and the setpoint

`hybrid_indoor_setpoint` is one value for the whole day. With a night setback,
use the time-weighted average (e.g. 15 h at 20.5 °C + 9 h at 19.5 °C ≈ 20.1 °C).

## 5. Choosing the energy cost ratio of the hybrid controller

Bosch / Buderus / Nefit hybrid controllers (and similar) ask for the ratio
*electricity price / gas price* and switch to gas when they estimate that the
heat pump has become more expensive. Running the heat pump is cheaper when

```
COP  >  (electricity price / gas price) × boiler efficiency
```

Use **all-in variable prices** (energy + network charges + excise and levies per
kWh). VAT cancels out when both carry the same rate, and fixed charges don't matter.

### Effective electricity price

- **Time-of-use tariffs**: weight the period prices by the hours the heat pump
  runs. A heat pump that keeps a buffer warm runs around the clock, so weight by hours.
- **Home battery**: if most grid electricity is bought in the cheap period and
  the battery covers the rest, use mostly the cheap price, plus the battery
  losses (~10 %) on the share that passes through the battery, and optionally
  battery wear. On cold days the battery may not cover all of it: the marginal
  kWh then comes at the expensive price.
- **Capacity tariff** (e.g. Flanders): a heat pump that raises the monthly
  peak adds a little (≈ 0.8 c/kWh in the reference case).

### Compare with what the controller does

The controller decides with **its own estimate** of the COP. In the reference
house the controller handed over to gas at **6.0–6.2 °C** (its own outdoor
sensor) with ratio 1.7, while the measured COP there was ≈ 3.2. So its estimate was
far more pessimistic than reality. With an effective price ratio of ≈ 2.1
(battery, super off-peak), the heat pump was ~40 % cheaper than gas at that point
(5.3 vs 8.7 c per kWh of heat). In such a case the right move is to **lower**
the ratio setting so the heat pump keeps running in colder weather, and to watch
the switch logger to see where it now hands over. Aim for the outdoor
temperature where your *measured* COP drops to the break-even COP.

| Reference case (Oct 2026, excl. VAT) | Value |
|---|---|
| Electricity, mostly super off-peak via battery | ≈ 17.1 c/kWh |
| Gas | 8.04 c/kWh |
| Price ratio | ≈ 2.1 |
| Break-even COP (boiler 92 %) | ≈ 2.0 |
| Measured COP at the switch point | ≈ 3.2 |
| Ratio setting | 1.7 → lowered to 1.5 |
