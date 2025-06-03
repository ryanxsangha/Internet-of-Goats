#!/usr/bin/env python3
"""
Primary-secondary polling topology
  • Primary Pi polls two secondary Pis over TCP
  • Each cycle:
        sensor_readings1  ← primary’s own data
        sensor_readings2  ← first secondary
        sensor_readings3  ← second secondary
  • Plots one PNG per round
Usage:
    primary.py <sec1_host> <sec1_port> <sec2_host> <sec2_port>
"""
import json, sys, socket, time
import matplotlib.pyplot as plt
import sensor_polling
import mysql.connector           

DB = dict(
    host     = "192.168.0.132",        # laptop IP
    port     = 3306,
    user     = "primaryPi",
    password = "theeIoTofGoats!",
    database = "piSenseDB"
)
conn = mysql.connector.connect(**DB)
cur  = conn.cursor(prepared=True)     
INSERT = ("INSERT INTO {table} "
          "(temperature, humidity, wind_speed, soil_moisture, topology_state) "
          "VALUES (%s, %s, %s, %s, %s)")

REQUEST = b"Requesting Data"

if len(sys.argv) != 5:
    print(f"Usage: {sys.argv[0]} <sec1_host> <sec1_port> <sec2_host> <sec2_port>")
    sys.exit(1)

sec1_host, sec1_port = sys.argv[1], int(sys.argv[2])
sec2_host, sec2_port = sys.argv[3], int(sys.argv[4])
clients = [(sec1_host, sec1_port), (sec2_host, sec2_port)]   # keep order!

def request_readings(host, port):
    try:
        with socket.create_connection((host, port), timeout=5) as sock:
            sock.sendall(REQUEST)
            data = sock.recv(2048)
        return json.loads(data.decode())
    except socket.timeout:
        print(f"[timeout] {host}:{port}")
    except Exception as e:
        print(f"[error] {host}:{port} → {e!r}")
    return None

def db_insert(table, reading, topo_json):
    if not reading:
        return
    vals = (
        reading.get("temperature"),
        reading.get("humidity"),
        reading.get("wind_speed"),
        reading.get("soil_moisture"),
        reading.get("topology_state", topo_json), 
    )
    cur.execute(INSERT.format(table=table), vals)
    conn.commit()

def plot_round(local, measurements, round_no):
    metrics = ['temperature', 'humidity', 'soil_moisture', 'wind_speed']
    titles  = ['Temperature', 'Humidity', 'Soil Moisture', 'Wind Speed']
    ylabels = ['°C', '%', 'Units', 'm/s']

    data_matrix = []
    for m in metrics:
        vals = [
            measurements[0].get(m) if measurements[0] else None,
            measurements[1].get(m) if measurements[1] else None,
            local.get(m)
        ]
        avg = sum(v for v in vals if v is not None) / max(1, len([v for v in vals if v]))
        vals.append(avg)
        data_matrix.append(vals)

    labels = ['Sec1', 'Sec2', 'Primary', 'Avg']
    colors = ['red', 'blue', 'green', 'black']
    fig, axes = plt.subplots(2, 2, figsize=(10, 8)); axes = axes.flatten()

    for i, ax in enumerate(axes):
        vals = data_matrix[i]
        ax.set_xticks(range(4)); ax.set_xticklabels(labels)
        ax.set_title(titles[i]); ax.set_ylabel(ylabels[i]); ax.grid(True, ls='--', alpha=.4)
        for x, c, y in zip(range(4), colors, vals):
            ax.scatter(x, y if y is not None else 0, color=c, marker='o' if y else 'x', s=80)

    fig.tight_layout()
    fname = f"polling-plot-{round_no}.png"
    fig.savefig(fname); plt.close(fig)
    print(f"[plot] saved {fname}")

def main():
    round_no = 1
    while True:
        # ── poll sensors ────────────────────────────────────────────────
        local = sensor_polling.get_local_measurements()   # primary
        sec_readings = []                                 # list for Sec1, Sec2
        for host, port in clients:
            sec_readings.append(request_readings(host, port))

        # ── build a JSON list with the *currently alive* nodes in order ─
        live_nodes = ["Primary"]
        if sec_readings[0]: live_nodes.append("Sec1")
        if sec_readings[1]: live_nodes.append("Sec2")
        topo_json = json.dumps(live_nodes)

        # ── store everything ------------------------------------------------
        local["topology_state"] = topo_json
        db_insert("sensor_readings1", local, topo_json)

        for idx, reading in enumerate(sec_readings, start=2):   # idx 2,3
            if reading is not None:
                reading["topology_state"] = topo_json
            db_insert(f"sensor_readings{idx}", reading, topo_json)

        # ── plot & wait -----------------------------------------------------
        plot_round(local, sec_readings, round_no)
        round_no += 1
        time.sleep(3)

if __name__ == "__main__":
    try:
        main()
    finally:
        conn.close()