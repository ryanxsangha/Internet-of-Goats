#!/usr/bin/env python3
"""
web-app.py  –  Flask dashboard for piSenseDB + Open-Meteo forecast
"""
from flask import Flask, render_template_string, Response, request
import pandas as pd, matplotlib.pyplot as plt, io, base64, requests, mysql.connector
from datetime import datetime, timedelta, date
import svgwrite, math, json                          
DB = dict(host="192.168.0.132", port=3306,
          user="primaryPi", password="theeIoTofGoats!", database="piSenseDB")

TABLES   = ["sensor_readings1", "sensor_readings2", "sensor_readings3"]
METRICS  = ["temperature", "humidity", "soil_moisture", "wind_speed"]
LABELS   = {"temperature": "°C", "humidity": "%", "wind_speed": "m s⁻¹", "soil_moisture": "U"}
LAT, LON = 37.0, -122.06
TIME_HRS = 24

app = Flask(__name__)
ring_state = ["Pi1", "Pi2", "Pi3"]       


def db_to_frame():
    cnx = mysql.connector.connect(**DB)
    stop, start = datetime.utcnow(), datetime.utcnow() - timedelta(hours=TIME_HRS)
    frames = []
    for idx, tbl in enumerate(TABLES, 1):
        q = (f"SELECT ts, temperature, humidity, wind_speed, soil_moisture "
             f"FROM {tbl} WHERE ts BETWEEN %s AND %s")
        df = pd.read_sql(q, cnx, params=(start, stop), parse_dates=["ts"])
        if not df.empty:
            df["node"] = f"Pi{idx}"
            frames.append(df)
    cnx.close()
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def latest_topology() -> list[str] | None:
    cnx = mysql.connector.connect(**DB)
    cur = cnx.cursor()
    newest_ts, newest_json = None, None
    for tbl in TABLES:
        cur.execute(
            f"SELECT ts, topology_state "
            f"FROM {tbl} WHERE topology_state IS NOT NULL "
            f"ORDER BY ts DESC LIMIT 1"
        )
        row = cur.fetchone()
        if row and (newest_ts is None or row[0] > newest_ts):
            newest_ts, newest_json = row
    cnx.close()
    if newest_json:
        try:
            return json.loads(newest_json)
        except Exception:
            pass
    return None


def normalize_labels(nodes: list[str]) -> list[str]:
    """Convert raw IP:port → Pi#, keep nice human labels unchanged."""
    out = []
    for idx, n in enumerate(nodes, 1):
        out.append(f"Pi{idx}" if ":" in n else n)
    return out


_fc, _ts = None, datetime.min
def forecast_today():
    global _fc, _ts
    if (datetime.utcnow() - _ts).seconds < 3600 and _fc:
        return _fc
    try:
        url = (f"https://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LON}"
               "&daily=temperature_2m_max,weathercode,windspeed_10m_max,relative_humidity_2m_max"
               "&temperature_unit=celsius&windspeed_unit=ms&timezone=auto"
               f"&start_date={date.today()}&end_date={date.today()}")
        d = requests.get(url, timeout=10).json()["daily"]
        _fc = dict(weathercode=d["weathercode"][0], temperature=d["temperature_2m_max"][0],
                   humidity=d["relative_humidity_2m_max"][0], wind_speed=d["windspeed_10m_max"][0],
                   soil_moisture=None)
    except Exception as e:
        print(f"[wx] forecast fetch failed: {e}")
        _fc = {}
    _ts = datetime.utcnow()
    return _fc


WX_EMOJI = {0: "☀️", 1: "⛅", 2: "⛅", 3: "☁️", 45: "🌫️", 48: "🌫️",
            51: "🌦️", 53: "🌦️", 55: "🌧️", 61: "🌧️", 63: "🌧️", 65: "🌧️",
            71: "❄️", 73: "❄️", 75: "❄️", 95: "⛈️"}
def wx_icon(code): return WX_EMOJI.get(code, "🌡️")


def make_bar(df: pd.DataFrame, metric: str, fcst_val):
    if df.empty or df[metric].dropna().empty:
        per_pi = pd.Series(dtype=float)
    else:
        per_pi = df.groupby("node")[metric].mean().sort_index()

    bars, labels = per_pi.tolist(), per_pi.index.tolist()
    bars.append(df[metric].mean()); labels.append("Avg")
    if fcst_val is not None:
        bars.append(fcst_val); labels.append("Forecast")

    plt.figure(figsize=(3.2, 3))
    colors = (["#1e88e5"] * len(per_pi)) + ["#555555"] + (["#ff9900"] if fcst_val is not None else [])
    plt.bar(range(len(bars)), bars, color=colors, width=0.55)
    plt.xticks(range(len(labels)), labels, rotation=25, ha="right")
    plt.ylabel(LABELS[metric]); plt.title(metric.replace("_", " ").title(), fontsize=10); plt.tight_layout()
    buf = io.BytesIO(); plt.savefig(buf, format="png"); plt.close()
    return base64.b64encode(buf.getvalue()).decode()


def ring_svg(nodes: list[str]) -> str:
    """Return SVG of the ring (single-node handled)."""
    if not nodes:                                              # nothing? return blank SVG
        return "<svg width='1' height='1'/>"

    dwg = svgwrite.Drawing(size=("180px", "180px"))
    cx, cy, r = 90, 90, 70

    if len(nodes) == 1:                                        # lone survivor
        dwg.add(dwg.circle((cx, cy), 14, fill="#1e88e5", stroke="white", stroke_width=2))
        dwg.add(dwg.text(nodes[0], insert=(cx, cy + 4), text_anchor="middle",
                         fill="white", font_size="9px"))
        return dwg.tostring()

    arrow = dwg.marker(insert=(3, 3), size=(6, 6), orient="auto")
    arrow.add(dwg.path(d="M0 0 L6 3 L0 6 Z", fill="#888")); dwg.defs.add(arrow)
    n = len(nodes)
    for i, name in enumerate(nodes):
        ang = 2 * math.pi * i / n
        x, y = cx + r * 0.9 * math.sin(ang), cy - r * 0.9 * math.cos(ang)
        x2, y2 = cx + r * 0.9 * math.sin(ang + 2 * math.pi / n), cy - r * 0.9 * math.cos(ang + 2 * math.pi / n)
        dwg.add(dwg.circle((x, y), 14, fill="#1e88e5", stroke="white", stroke_width=2))
        dwg.add(dwg.text(name, insert=(x, y + 4), text_anchor="middle", fill="white", font_size="9px"))
        dwg.add(dwg.line((x, y), (x2, y2), stroke="#888", stroke_dasharray="5,3",
                         marker_end=arrow.get_funciri()))
    return dwg.tostring()


TEMPLATE = TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Sensor Measurements Dashboard</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta http-equiv="refresh" content="60">
  <style>
    :root{--bg:#1e293b;--panel:#273349;--txt:#e2e8f0}
    body{margin:0;font:16px/1.4 system-ui;background:var(--bg);color:var(--txt)}
    h1{margin:0;padding:16px 0;text-align:center;font-size:1.8rem}
    .grid{display:grid;gap:16px;padding:16px}
    .grid{grid-template-columns:repeat(auto-fit,minmax(280px,1fr))}
    .card{background:var(--panel);border-radius:8px;padding:20px;text-align:center}
    .card h2{margin:4px 0;font-size:1.1rem}
    img{max-width:240px;height:auto;margin:0 auto;display:block}
    .wx{font-size:3rem;margin-bottom:8px}
  </style>
</head>
<body>
<h1>Sensor Measurements Dashboard</h1>

<div class="grid">
  <!-- Forecast card -->
  <div class="card">
    <div class="wx">{{icon}}</div>
    <h2>{{location}}</h2>
    <p style="font-size:2rem;margin:4px 0">{{fcst.temperature}}°</p>
    <p>{{weekday}} • High {{fcst.temperature}}°<br>
       Hum {{fcst.humidity}}% • Wind {{fcst.wind_speed}}&nbsp;m/s</p>
  </div>

  {% for m,img in bars.items() %}
    <div class="card"><img src="data:image/png;base64,{{img}}"></div>
  {% endfor %}
</div>

<p style="text-align:center;font-size:.8rem;margin:20px">
  Updated {{ts}} – auto refresh every 60 s
</p>
<h2 style="text-align:center;margin-top:0">Current&nbsp;Topology</h2>
<div style="display:flex;justify-content:center">
  {{ ring_svg|safe }}
</div>
</body></html>"""

@app.post("/topology-update")
def topo_update():
    global ring_state
    j = request.get_json(force=True, silent=True) or {}
    ring_state = j.get("ring", ring_state)
    print("[topology] updated to", ring_state)
    return ("", 204)


@app.route("/")
def index():
    df, fc = db_to_frame(), forecast_today()
    bars = {m: make_bar(df, m, fc.get(m)) for m in METRICS}

    db_ring = latest_topology()
    svg_nodes = normalize_labels(db_ring) if db_ring else ring_state

    return render_template_string(
        TEMPLATE,
        bars=bars,
        ring_svg=ring_svg(svg_nodes),
        fcst=fc,
        icon=wx_icon(fc.get("weathercode", 0)),
        weekday=datetime.now().strftime("%A"),
        location="Santa Cruz",
        ts=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )


@app.route("/healthz")
def ok(): return Response("OK", 200)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
