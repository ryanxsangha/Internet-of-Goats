#!/usr/bin/env python3
import sys, socket, json, time
import matplotlib.pyplot as plt
import sensor_polling
import mysql.connector

DB = dict(
    host     = "169.233.201.75",        # laptop IP
    port     = 3306,
    user     = "primaryPi",
    password = "theeIoTofGoats!",
    database = "piSenseDB"
)

conn = mysql.connector.connect(**DB)
cur  = conn.cursor(prepared=True)     
INSERT = ("INSERT INTO {table} "
          "(temperature, humidity, wind_speed, soil_moisture) "
          "VALUES (%s, %s, %s, %s)")

TIMEOUT       = 10    
PLOT_PAUSE    = 3   
RETRY_PAUSE = 2

USAGE = """
Usage: token-ring.py <role> <my_host:port> <node1> <node2> <node3> [<node4>...]
  role: start | mid | plot
  each nodeX is host:port in ring order.
Examples:
  # Pi1 (starter):
  token-ring.py start 192.168.1.10:6001 \\
       192.168.1.10:6001 192.168.1.11:6002 192.168.1.12:6003

  # Pi2 (middle):
  token-ring.py mid 192.168.1.11:6002 \\
       192.168.1.10:6001 192.168.1.11:6002 192.168.1.12:6003

  # Pi3 (plotter):
  token-ring.py plot 192.168.1.12:6003 \\
       192.168.1.10:6001 192.168.1.11:6002 192.168.1.12:6003
"""

if len(sys.argv) < 5:
    print(USAGE); sys.exit(1)

role      = sys.argv[1]
my_addr   = sys.argv[2]
ring      = sys.argv[3:]
N         = len(ring)

if role not in ("start","mid","plot") or my_addr not in ring:
    print("Bad role or my_addr not in ring\n", USAGE)
    sys.exit(1)

my_index  = ring.index(my_addr)

pred_index = (my_index - 1) % N
pred_host, pred_port = ring[pred_index].split(":")

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
host, port = my_addr.split(":")
server.bind((host, int(port)))
server.listen(1)
print(f"[{role}] bound to {my_addr}, predecessor={ring[pred_index]}, ring={ring}")

def db_insert(table, reading):
    if not reading:
        return
    vals = (reading.get("temperature"),
            reading.get("humidity"),
            reading.get("wind_speed"),
            reading.get("soil_moisture"))
    cur.execute(INSERT.format(table=table), vals)
    conn.commit()

def recv_token():
    server.settimeout(TIMEOUT*(my_index+1))
    try:
        conn, addr = server.accept()
    except socket.timeout:
        return None      
    with conn:
        raw = conn.recv(4096)
    try:
        token = json.loads(raw.decode())
    except Exception as e:
        print(f"[!] invalid token from {addr}: {e!r}")
        return []
    return token

def forward_token(token):
    for attempt in range(1, N):
        next_index = (my_index + attempt) % N
        my_id = my_index - 2
        next_host, next_port = ring[next_index].split(":")
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(TIMEOUT)
                s.connect((next_host, int(next_port)))
                s.sendall(json.dumps(token).encode())
            print(f"[{role}] forwarded to {ring[next_index]}")
            return
        except socket.timeout:
            print(f"[!] timeout forwarding to {ring[next_index]}, trying next")
        except Exception as e:
            print(f"[!] can't forward to {ring[next_index]}: {e!r}")
    print(f"[ERROR] all successors unreachable from {my_addr}")


def plot_token(token, round_num):
    metrics = ["temperature","humidity","soil_moisture","wind_speed"]
    titles  = ["Temperature (°C)","Humidity (%)","Soil Moisture","Wind Speed"]
    labelsX = [f"Node{i+1}" for i in range(len(token))] + ["Avg"]

    fig, axes = plt.subplots(2,2,figsize=(10,8))
    axes = axes.flatten()
    for i, ax in enumerate(axes):
        vals = [entry.get(metrics[i]) for entry in token]
        clean = [v for v in vals if v is not None]
        avg = sum(clean)/len(clean) if clean else None
        vals.append(avg)

        xs = list(range(len(vals)))
        colors = ["red","blue","green","black"]
        for x, c, v in zip(xs, colors, vals):
            if v is None:
                ymin,ymax = ax.get_ylim()
                ymark = ymin + 0.05*(ymax-ymin)
                ax.scatter(x, ymark, marker="x", color="gray", s=100)
            else:
                ax.scatter(x, v, color=c, s=80)

        ax.set_xticks(xs)
        ax.set_xticklabels(labelsX)
        ax.set_title(titles[i])
        ax.grid(True, linestyle="--", alpha=0.3)

    fig.tight_layout()
    fname = f"token-plot-{round_num}.png"
    fig.savefig(fname)
    plt.close(fig)
    print(f"[+] saved {fname}")

round_num = 1
try:
    while True:
        if role == "start" and round_num == 1:
            reading = sensor_polling.get_local_measurements(my_index)
            #db_insert(f"sensor_readings{my_index+1}", reading)
            token = [ reading ]
            print(f"[start] initial token = {token}")
            forward_token(token)
            token = recv_token()
            continue

        tok = recv_token()

        if tok is None:
            print(f"[{role}] no token — re-initiating token ring")
            reading = sensor_polling.get_local_measurements(my_index) 
            # db_insert(f"sensor_readings{my_index+1}", reading)
            token = [ reading ]
            forward_token(token)
            time.sleep(RETRY_PAUSE)
            continue

        token = tok or []  

        print(f"[{role}] got token: {token}")
        reading = sensor_polling.get_local_measurements(my_index)
        token.append(reading)
        #if the last node in the ring, push to the db and plot the shit
        if my_index % N == 0:
            for reading in token:
                db_insert(f"sensor_readings{reading['node']+1}", reading)
        plot_token(token, round_num)
        round_num += 1
        time.sleep(PLOT_PAUSE)

        forward_token(token)

except KeyboardInterrupt:
    print(f"\n[{role}] shutting down")



# #!/usr/bin/env python3
# """
# Robust Token Ring without SQL – Collects and plots IoT sensor data

# Usage:
#   token-ring.py <role> <my_host:port> <node1> <node2> <node3>
#     role: start | mid
# """

# import sys, socket, json, time, random
# import matplotlib.pyplot as plt
# import sensor_polling
# from datetime import datetime
# from pathlib import Path

# TIMEOUT      = 5
# SILENCE      = 15
# JITTER_MAX   = 2
# RETRY_PAUSE  = 2
# DATA_LOG     = Path("data.jsonl")
# ROUND_PREFIX = "round-"

# if len(sys.argv) != 5:
#     print(__doc__)
#     sys.exit(1)

# role, my_addr, *ring = sys.argv[1:]
# if my_addr not in ring or role not in ("start", "mid"):
#     print("Invalid role or address.")
#     sys.exit(1)

# N = len(ring)
# my_index = ring.index(my_addr)
# host, port = my_addr.split(":")

# srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
# srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
# srv.bind((host, int(port)))
# srv.listen(1)
# print(f"[{role}] Listening on {my_addr}")

# def recv_token():
#     srv.settimeout(TIMEOUT)
#     try:
#         conn, _ = srv.accept()
#     except socket.timeout:
#         return None
#     with conn:
#         blob = conn.recv(8192)
#     try:
#         return json.loads(blob.decode())
#     except Exception:
#         return None

# def forward_token(tok):
#     msg = json.dumps(tok).encode()
#     for step in range(1, N):
#         nxt_host, nxt_port = ring[(my_index + step) % N].split(":")
#         try:
#             with socket.create_connection((nxt_host, int(nxt_port)), TIMEOUT) as s:
#                 s.sendall(msg)
#             print(f"[{role}] ➜ {nxt_host}:{nxt_port}")
#             return True
#         except:
#             continue
#     print(f"[{role}] No reachable successors — holding token.")
#     return False

# def fresh_token(seq):
#     return {"seq": seq, "data": [sensor_polling.get_local_measurements()]}

# def append_to_log(token):
#     record = {
#         "timestamp": datetime.now().isoformat(),
#         "round": token["seq"],
#         "data": token["data"]
#     }
#     with open(DATA_LOG, "a") as f:
#         f.write(json.dumps(record) + "\n")
#     print(f"[{role}] Appended round {token['seq']} to data.jsonl")

# def plot_round(values, round_no):
#     metrics = ["temperature", "humidity", "soil_moisture", "wind_speed"]
#     titles  = ["Temp (°C)", "Humidity (%)", "Soil Moisture", "Wind Speed"]
#     labels  = [f"Node{i+1}" for i in range(len(values))] + ["Avg"]

#     fig, axes = plt.subplots(2,2,figsize=(10,8)); axes = axes.flatten()
#     for i, ax in enumerate(axes):
#         vals = [d.get(metrics[i]) for d in values]
#         clean = [v for v in vals if v is not None]
#         vals.append(sum(clean)/len(clean) if clean else None)

#         for x, v in enumerate(vals):
#             color = "gray" if v is None else ("black" if x == len(vals)-1 else ["red","blue","green","orange"][x % 4])
#             ax.scatter(x, v or 0, color=color, marker="x" if v is None else "o", s=80)

#         ax.set_xticks(range(len(vals)))
#         ax.set_xticklabels(labels)
#         ax.set_title(titles[i])
#         ax.grid(True, ls="--", alpha=.3)

#     fig.tight_layout()
#     fname = f"{ROUND_PREFIX}{round_no}.png"
#     fig.savefig(fname)
#     plt.close(fig)
#     print(f"[plot] Saved {fname}")

# last_seq  = -1
# last_seen = time.monotonic()
# holding   = None
# round_no  = 1

# try:
#     while True:
#         if holding:
#             if forward_token(holding):
#                 holding = None
#                 last_seen = time.monotonic()
#             else:
#                 time.sleep(RETRY_PAUSE)
#             continue

#         tok = recv_token()
#         now = time.monotonic()

#         if tok:
#             if tok.get("seq", -1) <= last_seq:
#                 continue
#             last_seq = tok["seq"]
#             last_seen = now
#             tok["data"].append(sensor_polling.get_local_measurements())

#             if len(tok["data"]) >= N:
#                 append_to_log(tok)
#                 plot_round(tok["data"], round_no)
#                 round_no += 1
#                 tok = {"seq": last_seq + 1, "data": []}

#             holding = tok
#             continue

#         if now - last_seen >= SILENCE:
#             wait = random.uniform(0, JITTER_MAX)
#             time.sleep(wait)
#             if time.monotonic() - last_seen >= SILENCE:
#                 seq = last_seq + 1
#                 print(f"[{role}] ** Regenerating token seq={seq}")
#                 holding = fresh_token(seq)
#                 last_seq = seq

# except KeyboardInterrupt:
#     print(f"\n[{role}] Shutting down.")
