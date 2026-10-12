"""
Hybrid Heatpump Energy Forecast - Home Assistant app

Hour-by-hour forecast (48 h) of heat demand, heat pump electricity and gas use
for a hybrid heating system (air/water heat pump + gas boiler), published as
Home Assistant sensors (with an hourly cumulative series usable by Predbat).

Model per hour:
  heat demand = heat_loss * (setpoint - T_out) - internal gains - solar gain
  (with a simple thermal-mass simulation of the indoor temperature)
  T_out >= bivalence  -> heat pump up to hp_max_thermal_kw, boiler tops up
  T_out <  bivalence  -> boiler only
  heat pump electricity = heat / COP(T_out), COP linear between -7 and +7 °C
  gas = boiler heat / boiler efficiency

The bivalence temperature can be learned from real switches recorded by the
"Hybrid gas switch logger" blueprint (input_text history), see README.
"""
import json
import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

VERSION = "2.0.2"
print(f"Hybrid Heatpump Energy Forecast v{VERSION} starting..", flush=True)

OPTIONS_PATH = "/data/options.json"
FORECAST_LOG = "/config/forecast_log.json" if os.path.isdir("/config") else "/data/forecast_log.json"

with open(OPTIONS_PATH, "r") as f:
    cfg = json.load(f)


def opt(key, default=None):
    v = cfg.get(key)
    return default if v in (None, "") else v


# ---------------- connection ----------------
# Inside Home Assistant OS the app talks to Core through the Supervisor proxy
# (homeassistant_api: true) - no long-lived token needed. ha_url/ha_token are
# only for running the script outside Home Assistant.
if opt("ha_url") and opt("ha_token"):
    HA_URL = opt("ha_url").rstrip("/")
    TOKEN = opt("ha_token")
    WS_URL = HA_URL.replace("http", "ws", 1) + "/api/websocket"
else:
    HA_URL = "http://supervisor/core"
    TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
    WS_URL = "ws://supervisor/core/websocket"

HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

BOILER_EFF = float(opt("boiler_efficiency", 0.92))
SENSOR_PREFIX = opt("sensor_prefix", "hybrid")
INDOOR_ENTITY = opt("indoor_temp_entity")
HP_TODAY_ENTITY = opt("hp_energy_today_entity")          # daily HP electricity, resets at midnight
GAS_TODAY_ENTITY = opt("gas_energy_today_entity")        # daily gas kWh, resets at midnight
RATIO_ENTITY = opt("energy_cost_ratio_entity")           # e.g. number.thermostat_energy_cost_ratio
SWITCH_HISTORY_ENTITY = opt("switch_history_entity", "input_text.hybrid_gas_switch_history")
CREATE_HELPERS = bool(cfg.get("create_helpers", True))

# Model parameters: (key, helper entity, legacy helper entity, default, min, max, step, unit)
# Defaults were fitted on one Belgian house (Oct 2025 - Oct 2026) - calibrate for yours.
PARAMS = [
    ("setpoint",   "input_number.hybrid_indoor_setpoint",    "input_number.indoor_setpoint",              20.4, 10, 26, 0.1, "°C"),
    ("heat_loss",  "input_number.hybrid_heat_loss",          "input_number.heat_loss",                    0.38, 0.05, 2, 0.01, "kW/K"),
    ("bivalence",  "input_number.hybrid_bivalence_temp",     "input_number.bivalence_temp",               6.2, -20, 20, 0.1, "°C"),
    ("hp_max",     "input_number.hybrid_hp_max_thermal_kw",  "input_number.hp_max_thermal_kw",            5.0, 1, 30, 0.1, "kW"),
    ("cop_p7",     "input_number.hybrid_hp_cop_plus7",       "input_number.hp_cop_plus7",                 3.55, 1, 7, 0.01, None),
    ("cop_m7",     "input_number.hybrid_hp_cop_minus7",      "input_number.hp_cop_minus7",                3.0, 1, 6, 0.01, None),
    ("capacity",   "input_number.hybrid_thermal_capacity",   "input_number.thermal_capacity_kwh_per_k",   20.0, 1, 100, 0.5, "kWh/K"),
    ("recovery",   "input_number.hybrid_recovery_hours",     "input_number.recovery_hours",               4.0, 1, 24, 0.5, "h"),
    ("gains",      "input_number.hybrid_internal_gains_kw",  "input_number.internal_gains_kw",            0.5, 0, 5, 0.05, "kW"),
    ("solar_m2",   "input_number.hybrid_solar_gain_m2",      "input_number.solar_gain_m2",                3.0, 0, 30, 0.1, "m²"),
    ("boiler_max", "input_number.hybrid_boiler_max_kw",      "input_number.boiler_max_kw",                24.0, 0, 60, 0.5, "kW"),
]

# Helpers used by the gas switch logger blueprint (created when missing).
LOGGER_HELPERS = [
    ("input_text", {"name": "hybrid_gas_switch_history", "min": 0, "max": 255, "mode": "text",
                    "icon": "mdi:history"}, None),
    ("input_boolean", {"name": "hybrid_on_gas", "icon": "mdi:fire"}, None),
    ("input_datetime", {"name": "hybrid_last_gas_step", "has_date": True, "has_time": True,
                        "icon": "mdi:clock-outline"}, None),
    ("input_number", {"name": "hybrid_gas_switch_temp", "min": -20, "max": 30, "step": 0.1,
                      "unit_of_measurement": "°C", "mode": "box",
                      "icon": "mdi:thermometer-chevron-down"}, None),
    ("input_number", {"name": "hybrid_hp_return_temp", "min": -20, "max": 30, "step": 0.1,
                      "unit_of_measurement": "°C", "mode": "box",
                      "icon": "mdi:thermometer-chevron-up"}, None),
]


def log(msg: str = ""):
    print(msg, flush=True)


# ---------------- Home Assistant API ----------------
def ha_get(path: str, **kw):
    r = requests.get(f"{HA_URL}/api/{path}", headers=HEADERS, timeout=kw.pop("timeout", 10), **kw)
    r.raise_for_status()
    return r.json()


def all_states() -> dict:
    """One call for every entity: {entity_id: state_object}."""
    return {s["entity_id"]: s for s in ha_get("states", timeout=20)}


def num(states: dict, entity_id, default=None):
    s = states.get(entity_id) if entity_id else None
    try:
        return float(s["state"])
    except (TypeError, KeyError, ValueError):
        return default


def set_sensor(entity_id: str, state, attrs: dict):
    try:
        requests.post(f"{HA_URL}/api/states/{entity_id}", headers=HEADERS,
                      json={"state": state, "attributes": attrs}, timeout=10).raise_for_status()
    except Exception as e:
        log(f"  ! sensor error {entity_id}: {e}")


def call_service(domain: str, service: str, data: dict):
    try:
        requests.post(f"{HA_URL}/api/services/{domain}/{service}", headers=HEADERS,
                      json=data, timeout=10).raise_for_status()
    except Exception as e:
        log(f"  ! service {domain}.{service} failed: {e}")


def day_max_from_history(entity_id: str, day_start: datetime):
    """Highest value of a daily counter during one local day (HA history API)."""
    try:
        end = day_start + timedelta(days=1)
        data = ha_get(f"history/period/{day_start.isoformat()}", timeout=20,
                      params={"end_time": end.isoformat(), "filter_entity_id": entity_id,
                              "minimal_response": "", "no_attributes": ""})
        vals = []
        for series in data:
            for s in series:
                try:
                    vals.append(float(s["state"]))
                except (KeyError, ValueError, TypeError):
                    pass
        return max(vals) if vals else None
    except Exception as e:
        log(f"  ! history for {entity_id} not readable ({e})")
        return None


# ---------------- helper creation (websocket) ----------------
def create_missing_helpers(states: dict):
    """Create the model / logger helpers that do not exist yet (neither the
    hybrid_* name nor the legacy name), then set their default value."""
    todo = []
    for key, eid, legacy, default, lo, hi, step, unit in PARAMS:
        if eid in states or legacy in states:
            continue
        payload = {"name": eid.split(".", 1)[1], "min": lo, "max": hi, "step": step, "mode": "box",
                   "icon": "mdi:tune-variant"}
        if unit:
            payload["unit_of_measurement"] = unit
        todo.append(("input_number", payload, default))
    for domain, payload, default in LOGGER_HELPERS:
        if f"{domain}.{payload['name']}" not in states:
            todo.append((domain, dict(payload), default))
    if not todo:
        return
    try:
        import websocket   # websocket-client
        ws = websocket.create_connection(WS_URL, timeout=15)
        json.loads(ws.recv())                                       # auth_required
        ws.send(json.dumps({"type": "auth", "access_token": TOKEN}))
        if json.loads(ws.recv()).get("type") != "auth_ok":
            log("  ! helper creation: websocket authentication failed")
            ws.close()
            return
        for n, (domain, payload, default) in enumerate(todo, start=1):
            ws.send(json.dumps({"id": n, "type": f"{domain}/create", **payload}))
            while True:                                              # skip unrelated messages
                resp = json.loads(ws.recv())
                if resp.get("id") == n:
                    break
            if resp.get("success"):
                eid = f"{domain}.{payload['name']}"
                log(f"Helper     : created {eid}" + (f" = {default}" if default is not None else ""))
                if default is not None and domain == "input_number":
                    time.sleep(0.5)
                    call_service("input_number", "set_value", {"entity_id": eid, "value": default})
            else:
                log(f"  ! could not create {domain}.{payload['name']}: {resp.get('error')}")
        ws.close()
    except Exception as e:
        log(f"  ! helper creation failed ({e}); create the helpers by hand, see README")


# ---------------- weather ----------------
def fetch_weather(lat, lon, tz_name, now: datetime):
    """48 hourly (start, temperature, radiation W/m2) from the current hour,
    aligned on Open-Meteo's own timestamps."""
    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={"latitude": lat, "longitude": lon,
                "hourly": "temperature_2m,shortwave_radiation",
                "forecast_days": 3, "timezone": tz_name},
        timeout=15,
    )
    r.raise_for_status()
    hourly = r.json()["hourly"]
    tz = ZoneInfo(tz_name)
    this_hour = now.replace(minute=0, second=0, microsecond=0)
    out = []
    for t, temp, rad in zip(hourly["time"], hourly["temperature_2m"], hourly["shortwave_radiation"]):
        start = datetime.fromisoformat(t).replace(tzinfo=tz)
        if start < this_hour or temp is None:
            continue
        out.append((start, float(temp), float(rad or 0.0)))
        if len(out) == 48:
            break
    return out


# ---------------- learned bivalence ----------------
def learned_bivalence(history: str, ratio):
    """Median switch-to-gas temperature of the last 5 real switches at this ratio.
    History format (newest first): '5.9@1.5,8.1@1.5p,...' (p = gas only assisting)."""
    temps, other_ratio, assists = [], 0, 0
    for item in (history or "").split(","):
        item = item.strip()
        if "@" not in item:
            continue
        t_txt, r_txt = item.split("@", 1)
        if r_txt.endswith("p"):
            assists += 1
            continue
        try:
            t, r = float(t_txt), float(r_txt)
        except ValueError:
            continue
        if ratio is not None and abs(r - ratio) > 0.05:
            other_ratio += 1
            continue
        temps.append(t)
    temps = temps[:5]
    if len(temps) < 3:
        return None, temps, other_ratio, assists
    srt = sorted(temps)
    mid = len(srt) // 2
    med = srt[mid] if len(srt) % 2 else (srt[mid - 1] + srt[mid]) / 2
    return med, temps, other_ratio, assists


# ---------------- forecast memory (forecast vs actual) ----------------
def load_forecast_log() -> dict:
    try:
        with open(FORECAST_LOG, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_forecast_log(data: dict):
    try:
        keep = sorted(data)[-30:]
        with open(FORECAST_LOG, "w") as f:
            json.dump({k: data[k] for k in keep}, f, indent=1)
    except Exception as e:
        log(f"  ! could not save {FORECAST_LOG}: {e}")


def fmt_day(d: dict) -> str:
    if not d["hours"]:
        return "no hours"
    temps = d["temps"]
    cop = (d["hp_heat"] / d["elec"]) if d["elec"] > 0 else 0.0
    return (f"{d['hours']:>2} h | outdoor {min(temps):5.1f} .. {max(temps):5.1f} °C, "
            f"mean {sum(temps) / len(temps):5.1f} °C, sun {d['rad'] / 1000:4.1f} kWh/m² | "
            f"heat {d['heat']:6.1f} kWh = HP {d['hp_heat']:5.1f} + boiler {d['gas_heat']:5.1f} | "
            f"elec {d['elec']:5.2f} kWh (COP {cop:3.1f}, {d['hp_hours']} h on) | "
            f"gas {d['gas']:6.1f} kWh ({d['gas_hours']} h on)")


# ---------------- the forecast ----------------
def resolve_params(states: dict):
    """Value and source of every model parameter."""
    p, src = {}, {}
    for key, eid, legacy, default, *_ in PARAMS:
        for cand in (eid, legacy):
            v = num(states, cand)
            if v is not None:
                p[key], src[key] = v, cand
                break
        else:
            p[key], src[key] = default, "default"
    return p, src


def run_forecast(ha_config: dict):
    t_start = time.monotonic()
    states = all_states()
    tz_name = opt("timezone") or ha_config.get("time_zone") or "Europe/Brussels"
    now = datetime.now(ZoneInfo(tz_name))
    log("")
    log(f"=== Hybrid forecast run {now:%Y-%m-%d %H:%M} (v{VERSION}) ===")

    p, src = resolve_params(states)
    lat = num(states, "input_number.latitude", ha_config.get("latitude"))
    lon = num(states, "input_number.longitude", ha_config.get("longitude"))

    ratio = num(states, RATIO_ENTITY)
    history = (states.get(SWITCH_HISTORY_ENTITY) or {}).get("state", "")
    learned, sw_temps, sw_other, sw_assist = learned_bivalence(history, ratio)
    bivalence = learned if learned is not None else p["bivalence"]
    if learned is not None:
        biv_src = (f"learned {learned:.1f} °C = median of last {len(sw_temps)} switches to gas"
                   + (f" at ratio {ratio:.1f}" if ratio is not None else "")
                   + f": {', '.join(f'{t:.1f}' for t in sw_temps)}")
    else:
        biv_src = (f"{p['bivalence']:.1f} °C from {src['bivalence']} (only {len(sw_temps)} recorded "
                   f"switch(es){f' at ratio {ratio:.1f}' if ratio is not None else ''}; 3 needed to learn)")
    if sw_other or sw_assist:
        biv_src += f" | ignored: {sw_other} at other ratio, {sw_assist} gas-assist"

    hp_act = num(states, HP_TODAY_ENTITY, 0.0)
    gas_act = num(states, GAS_TODAY_ENTITY)
    indoor = num(states, INDOOR_ENTITY, p["setpoint"])

    H, setpoint, gains, solar_m2 = p["heat_loss"], p["setpoint"], p["gains"], p["solar_m2"]
    cop_m7, cop_p7, hp_max, boiler_max = p["cop_m7"], p["cop_p7"], p["hp_max"], p["boiler_max"]
    capacity, recovery = p["capacity"], p["recovery"]

    def cop(t):
        return max(1.5, cop_m7 + (t + 7) * (cop_p7 - cop_m7) / 14)

    defaults = [k for k, s in src.items() if s == "default"]
    balance = setpoint - gains / H if H > 0 else setpoint
    log(f"Parameters : heat loss {H:.2f} kW/K | setpoint {setpoint:.1f} °C | gains {gains:.2f} kW + sun "
        f"{solar_m2:.1f} m² | balance temp {balance:.1f} °C (no heating above, without sun)")
    log(f"             HP max {hp_max:.1f} kW, COP {cop_m7:.2f} @-7 °C .. {cop_p7:.2f} @+7 °C "
        f"(at 10 °C: {cop(10):.2f}) | boiler max {boiler_max:.0f} kW, efficiency {BOILER_EFF:.2f} | "
        f"thermal mass {capacity:.0f} kWh/K, recovery {recovery:.1f} h")
    if defaults:
        log(f"             built-in defaults used for: {', '.join(defaults)}")
    log(f"Bivalence  : {biv_src}")
    gas_txt = f"{gas_act:.1f} kWh" if gas_act is not None else "n/a"
    log(f"Now        : indoor {indoor:.2f} °C ({INDOOR_ENTITY or 'no sensor, using setpoint'}) | "
        f"today so far: HP {hp_act:.2f} kWh elec, gas {gas_txt}")

    weather = fetch_weather(lat, lon, tz_name, now)
    if not weather:
        raise RuntimeError("Open-Meteo returned no usable hours")
    log(f"Weather    : Open-Meteo {lat:.2f},{lon:.2f}, {len(weather)} h from {weather[0][0]:%a %H:%M} | "
        f"now {weather[0][1]:.1f} °C, {weather[0][2]:.0f} W/m²")

    def empty_day():
        return {"hours": 0, "temps": [], "rad": 0.0, "heat": 0.0, "hp_heat": 0.0, "gas_heat": 0.0,
                "elec": 0.0, "gas": 0.0, "hp_hours": 0, "gas_hours": 0}
    day_today, day_tom = empty_day(), empty_day()
    tomorrow = now.date() + timedelta(days=1)
    peak = (0.0, None)
    temp_hourly, elec_48h, gas_48h = [], [{"last_updated": now.isoformat(), "energy": hp_act}], \
        [{"last_updated": now.isoformat(), "energy": 0.0}]
    elec_cum, gas_cum = hp_act, 0.0
    T_in = indoor

    for h, (start, T_out, rad) in enumerate(weather):
        ts = start + timedelta(hours=1)
        frac = max(0.0, min(1.0, (ts - now).total_seconds() / 3600)) if h == 0 else 1.0
        free_kw = gains + solar_m2 * rad / 1000.0
        heat_loss = H * max(0.0, T_in - T_out)
        hp_heat = gas_heat = elec = gas = 0.0
        if T_in < setpoint:
            maintain = max(0.0, H * (setpoint - T_out) - free_kw)
            rec = (setpoint - T_in) * capacity / max(1.0, recovery)
            need = max(maintain, heat_loss - free_kw + rec)
            if T_out < bivalence:
                gas_heat = min(boiler_max, need)
            else:
                hp_heat = min(hp_max, need)
                gas_heat = min(boiler_max, need - hp_heat)
            elec = hp_heat / cop(T_out)
            gas = gas_heat / BOILER_EFF if BOILER_EFF else gas_heat
        T_in += (hp_heat + gas_heat + free_kw - heat_loss) / capacity * frac
        elec *= frac
        gas *= frac

        d = day_today if start.date() == now.date() else day_tom if start.date() == tomorrow else None
        if d is not None:
            d["hours"] += 1
            d["temps"].append(T_out)
            d["rad"] += rad * frac
            d["heat"] += (hp_heat + gas_heat) * frac
            d["hp_heat"] += hp_heat * frac
            d["gas_heat"] += gas_heat * frac
            d["elec"] += elec
            d["gas"] += gas
            d["hp_hours"] += hp_heat > 0.05
            d["gas_hours"] += gas_heat > 0.05
        if frac > 0 and elec / frac > peak[0]:
            peak = (elec / frac, start)
        elec_cum += elec
        gas_cum += gas
        elec_48h.append({"last_updated": ts.isoformat(), "energy": round(elec_cum, 2)})
        gas_48h.append({"last_updated": ts.isoformat(), "energy": round(gas_cum, 2)})
        temp_hourly.append({"last_updated": start.isoformat(), "temperature": round(T_out, 2),
                            "radiation": round(rad)})

    log(f"Today rest : {fmt_day(day_today)}")
    total_gas = f"{(gas_act or 0) + day_today['gas']:.1f}" if gas_act is not None else "n/a"
    log(f"Today total: HP elec {hp_act + day_today['elec']:.2f} kWh (so far {hp_act:.2f} + rest "
        f"{day_today['elec']:.2f}) | gas {total_gas} kWh")
    log(f"Tomorrow   : {fmt_day(day_tom)}")
    if peak[1] is not None:
        log(f"Peak hour  : {peak[1]:%a %H:%M} with {peak[0]:.2f} kWh electricity")
    log(f"48 h total : HP elec {elec_cum - hp_act:.2f} kWh, gas {gas_cum:.1f} kWh | "
        f"simulated indoor at end {T_in:.2f} °C")

    # forecast vs actual
    flog = load_forecast_log()
    flog[tomorrow.isoformat()] = {
        "elec": round(day_tom["elec"], 2), "gas": round(day_tom["gas"], 1), "heat": round(day_tom["heat"], 1),
        "mean_temp": round(sum(day_tom["temps"]) / len(day_tom["temps"]), 1) if day_tom["temps"] else None,
        "bivalence": round(bivalence, 1), "made": now.isoformat(timespec="minutes"),
    }
    yday = now.date() - timedelta(days=1)
    entry = flog.get(yday.isoformat())
    if entry is not None and (HP_TODAY_ENTITY or GAS_TODAY_ENTITY):
        if "actual_elec" not in entry:
            yday_start = datetime.combine(yday, datetime.min.time(), tzinfo=ZoneInfo(tz_name))
            entry["actual_elec"] = day_max_from_history(HP_TODAY_ENTITY, yday_start) if HP_TODAY_ENTITY else None
            entry["actual_gas"] = day_max_from_history(GAS_TODAY_ENTITY, yday_start) if GAS_TODAY_ENTITY else None
        ae, ag = entry.get("actual_elec"), entry.get("actual_gas")
        txt_e = (f"elec forecast {entry['elec']:.1f} / actual {ae:.1f} kWh ({entry['elec'] - ae:+.1f})"
                 if ae is not None else f"elec forecast {entry['elec']:.1f} / actual n/a")
        txt_g = (f"gas forecast {entry['gas']:.0f} / actual {ag:.0f} kWh ({entry['gas'] - ag:+.0f})"
                 if ag is not None else f"gas forecast {entry['gas']:.0f} / actual n/a")
        log(f"Yesterday  : {txt_e} | {txt_g} (forecast made {entry.get('made', '?')})")
        errs = [v["elec"] - v["actual_elec"] for v in flog.values() if v.get("actual_elec") is not None]
        if len(errs) >= 3:
            log(f"Accuracy   : last {len(errs)} days elec bias {sum(errs) / len(errs):+.2f} kWh/day, "
                f"MAE {sum(abs(e) for e in errs) / len(errs):.2f} kWh/day")
    save_forecast_log(flog)

    model = {"heat_loss_kw_per_c": H, "setpoint": setpoint, "bivalence": round(bivalence, 1),
             "bivalence_source": "learned" if learned is not None else src["bivalence"],
             "cop_plus7": cop_p7, "cop_minus7": cop_m7, "hp_max_kw": hp_max,
             "internal_gains_kw": gains, "solar_gain_m2": solar_m2, "boiler_max_kw": boiler_max,
             "boiler_efficiency": BOILER_EFF, "balance_temp": round(balance, 1),
             "energy_cost_ratio": ratio, "version": VERSION}

    sp = SENSOR_PREFIX
    kwh = {"unit_of_measurement": "kWh", "device_class": "energy"}
    set_sensor(f"sensor.{sp}_electricity_today", round(day_today["elec"], 2),
               {**kwh, "friendly_name": "Hybrid heat pump electricity today (remaining)"})
    set_sensor(f"sensor.{sp}_electricity_tomorrow", round(day_tom["elec"], 2),
               {**kwh, "friendly_name": "Hybrid heat pump electricity tomorrow"})
    set_sensor(f"sensor.{sp}_gas_today", round(day_today["gas"], 2),
               {**kwh, "friendly_name": "Hybrid gas today (remaining)"})
    set_sensor(f"sensor.{sp}_gas_tomorrow", round(day_tom["gas"], 2),
               {**kwh, "friendly_name": "Hybrid gas tomorrow"})
    set_sensor(f"sensor.{sp}_heat_demand_today", round(day_today["heat"], 2),
               {**kwh, "friendly_name": "Hybrid heat demand today (remaining, thermal)"})
    set_sensor(f"sensor.{sp}_heat_demand_tomorrow", round(day_tom["heat"], 2),
               {**kwh, "friendly_name": "Hybrid heat demand tomorrow (thermal)"})
    set_sensor(f"sensor.{sp}_electricity_48h", round(elec_cum, 2),
               {**kwh, "friendly_name": "Hybrid heat pump electricity 48 h (cumulative)",
                "hourly": elec_48h, "model": model})
    set_sensor(f"sensor.{sp}_gas_48h", round(gas_cum, 2),
               {**kwh, "friendly_name": "Hybrid gas 48 h (cumulative)", "hourly": gas_48h})
    set_sensor(f"sensor.{sp}_simulated_indoor_temperature", round(T_in, 2),
               {"unit_of_measurement": "°C", "device_class": "temperature",
                "friendly_name": "Hybrid simulated indoor temperature"})
    set_sensor(f"sensor.{sp}_forecast_temperature_48h", temp_hourly[0]["temperature"],
               {"unit_of_measurement": "°C", "device_class": "temperature",
                "friendly_name": "Hybrid forecast outdoor temperature", "hourly": temp_hourly})
    log(f"Published  : 10 sensors in {time.monotonic() - t_start:.1f} s")


def seconds_until_next_hour(tz_name: str) -> float:
    now = datetime.now(ZoneInfo(tz_name))
    nxt = (now + timedelta(hours=1)).replace(minute=0, second=5, microsecond=0)
    return max(1.0, (nxt - now).total_seconds())


def main():
    ha_config = {}
    for attempt in range(30):                      # Core may still be starting
        try:
            ha_config = ha_get("config")
            break
        except Exception as e:
            log(f"  ! Home Assistant not reachable yet ({e}), retrying in 20 s")
            time.sleep(20)
    tz_name = opt("timezone") or ha_config.get("time_zone") or "Europe/Brussels"
    log(f"Options    : HA {HA_URL}, timezone {tz_name}, boiler efficiency {BOILER_EFF}, "
        f"indoor {INDOOR_ENTITY or '-'}, HP today {HP_TODAY_ENTITY or '-'}, gas today {GAS_TODAY_ENTITY or '-'}, "
        f"cost ratio {RATIO_ENTITY or '-'}, switch history {SWITCH_HISTORY_ENTITY}")
    log(f"Forecast log: {FORECAST_LOG}")
    for value, name, effect in (
            (INDOOR_ENTITY, "indoor_temp_entity", "simulation starts at the setpoint"),
            (HP_TODAY_ENTITY, "hp_energy_today_entity",
             "today's total and the 48 h cumulative series start at 0, no forecast-vs-actual for electricity"),
            (GAS_TODAY_ENTITY, "gas_energy_today_entity", "no forecast-vs-actual for gas"),
            (RATIO_ENTITY, "energy_cost_ratio_entity",
             "switch temperatures are used regardless of the energy cost ratio they were recorded at")):
        if not value:
            log(f"  ! option {name} not set: {effect}")
    if CREATE_HELPERS:
        try:
            create_missing_helpers(all_states())
        except Exception as e:
            log(f"  ! helper check failed: {e}")
    while True:
        try:
            run_forecast(ha_config)
        except Exception as e:
            log(f"Forecast error: {e}")
        wait = seconds_until_next_hour(tz_name)
        log(f"Next run in {int(wait) // 60} min {int(wait) % 60} s")
        time.sleep(wait)


if __name__ == "__main__":
    main()
