#!/usr/bin/env python3
import sys, socket, json, time
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

TIMEOUT       = 10    
PLOT_PAUSE    = 3   
RETRY_PAUSE   = 2

USAGE = """
Usage: token-ring.py <role> <my_host:port> <node1> <node2> <node3> [<node4>...]
  role: start | mid | plot
  each nodeX is host:port in ring order.
"""

if len(sys.argv) < 5:
    print(USAGE); sys.exit(1)

role      = sys.argv[1]
my_addr   = sys.argv[2]
ring      = sys.argv[3:]              # This list will be dynamically updated
N         = len(ring)                # Always keep in sync with len(ring)

if role not in ("start","mid","plot") or my_addr not in ring:
    print("Bad role or my_addr not in ring\n", USAGE)
    sys.exit(1)

# Compute my_index and predecessor index initially
my_index   = ring.index(my_addr)
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
            reading.get("soil_moisture"),
            reading.get("topology_state")) or json.dumps(ring)
    cur.execute(INSERT.format(table=table), vals)
    conn.commit()

def attach_topology(reading: dict) -> dict:
    """
    Adds a 'topology_state' field – JSON string with the CURRENT ring order.
    called right after sensor_polling.get_local_measurements().
    """
    reading["topology_state"] = json.dumps(ring) 
    return reading


def update_topology_and_indices(node_addr):
    """
    If node_addr is already in ring, remove it (because unreachable).
    Otherwise, append it (because rejoining).
    Then recalc N, my_index, pred_index, etc.
    """
    global ring, N, my_index, pred_index, pred_host, pred_port

    if node_addr in ring:
        ring.remove(node_addr)
        print(f"[{role}] Removing unreachable node {node_addr} from ring.")
    else:
        ring.append(node_addr)
        print(f"[{role}] Adding node {node_addr} back into ring.")

    N = len(ring)
    if N == 0:
        return

    try:
        my_index = ring.index(my_addr)
    except ValueError:
        # If somehow this node was removed, re-add it
        ring.append(my_addr)
        my_index = ring.index(my_addr)

    pred_index = (my_index - 1) % N
    pred_host, pred_port = ring[pred_index].split(":")
    print(f"[{role}] Updated ring={ring}, N={N}, my_index={my_index}, predecessor={ring[pred_index]}")


def recv_token():
    """
    Wait for a token to arrive (or timeout). Inspect token["source"] to detect re-joins.
    """
    server.settimeout(TIMEOUT * (my_index + 1))
    try:
        conn_sock, addr = server.accept()
    except socket.timeout:
        return None

    with conn_sock:
        raw = conn_sock.recv(4096)

    try:
        token = json.loads(raw.decode())
    except Exception as e:
        print(f"[!] invalid token from {addr}: {e!r}")
        return []

    #Look at token["source"]
    source_addr = token.get("source")
    if source_addr and source_addr not in ring:
        print(f"[{role}] Detected rejoining node {source_addr} from token")
        update_topology_and_indices(source_addr)

    return token


def forward_token(token):
    """
    Try to forward 'token' to each successor in current ring.
    If a successor is unreachable, remove it and retry (UPDATE-INDICES).
    Return True if forwarded; False if ring is empty or no one accepted.
    """
    global ring, N, my_index

    if N-1 == 0:
        print(f"[{role}] No successors left. I must be last-alive.")
        for rec in token["data"]:
                db_insert(f"sensor_readings{rec['node']+1}", rec)
        return False

    attempts = 0
    while attempts < (N - 1):
        next_index = (my_index + 1) % N
        successor = ring[next_index]
        next_host, next_port = successor.split(":")

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(TIMEOUT)
                s.connect((next_host, int(next_port)))
                s.sendall(json.dumps(token).encode())
            print(f"[{role}] forwarded to {successor}")
            return True

        except (socket.timeout, ConnectionRefusedError) as e:
            print(f"[!] successor {successor} unreachable: {e!r}, updating topology")
            update_topology_and_indices(successor)
            attempts += 1
            if N <= 1:
                break
            continue

    print(f"[ERROR] all successors unreachable from {my_addr} (after updating topology).")
    return False


def plot_token(token, round_num):
    metrics = ["temperature","humidity","soil_moisture","wind_speed"]
    titles  = ["Temperature (°C)","Humidity (%)","Soil Moisture","Wind Speed"]
    labelsX = [f"Node{i+1}" for i in range(len(token))] + ["Avg"]

    fig, axes = plt.subplots(2, 2, figsize=(10,8))
    axes = axes.flatten()
    for i, ax in enumerate(axes):
        vals  = [entry.get(metrics[i]) for entry in token]
        clean = [v for v in vals if v is not None]
        avg   = sum(clean)/len(clean) if clean else None
        vals.append(avg)

        xs     = list(range(len(vals)))
        colors = ["red","blue","green","black"]
        for x, c, v in zip(xs, colors, vals):
            if v is None:
                ymin, ymax = ax.get_ylim()
                ymark = ymin + 0.05 * (ymax - ymin)
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
            reading = attach_topology(sensor_polling.get_local_measurements(my_index))
            token = {
                "source": my_addr,    #include source
                "data":   [reading],
                "round":  1,
                "closed": False
            }
            print(f"[start] initial token = {token}")
            forward_token(token)
            token = recv_token()
            continue

        tok = recv_token()

        if tok is None:
            print(f"[{role}] no token — re-initiating token ring")
            reading = attach_topology(sensor_polling.get_local_measurements(my_index))
            token = {
                "source": my_addr,   #include source
                "data":   [reading],
                "round":  round_num,
                "closed": False
            }
            forward_token(token)
            time.sleep(RETRY_PAUSE)
            continue

        token = tok or []
        print(f"[{role}] got token: {token}")

        reading = attach_topology(sensor_polling.get_local_measurements(my_index))
        token["data"].append(reading)

        if len(token["data"]) == N:
            # End of lap for current live ring
            for rec in token["data"]:
                db_insert(f"sensor_readings{rec['node']+1}", rec)
            plot_token(token["data"], token["round"])

            next_round = token["round"] + 1
            empty = {
                "source": my_addr,    #include source
                "data":   [],
                "round":  next_round,
                "closed": False
            }
            print(f"[{role}] completed lap (size={N}). Starting empty token for round={next_round}")
            time.sleep(PLOT_PAUSE)
            forward_token(empty)

            round_num = next_round
            time.sleep(PLOT_PAUSE)
            continue

        # Otherwise, not end of lap—forward normally (with updated ring)
        token["source"] = my_addr  #reset source before forwarding
        if not forward_token(token):
            # Last-alive fallback
            for rec in token["data"]:
                db_insert(f"sensor_readings{rec['node']+1}", rec)
            plot_token(token["data"], token["round"])

            next_round = token["round"] + 1
            empty = {
                "source": my_addr,   
                "data":   [],
                "round":  next_round,
                "closed": False
            }
            print(f"[{role}] last-alive fallback. Starting empty token for round={next_round}")
            time.sleep(PLOT_PAUSE)
            forward_token(empty)

            round_num = next_round
            time.sleep(PLOT_PAUSE)
            continue

        # If forwarded successfully, bump round counter
        round_num += 1
        time.sleep(PLOT_PAUSE)

        token["source"] = my_addr  
        forward_token(token)

except KeyboardInterrupt:
    print(f"\n[{role}] shutting down")