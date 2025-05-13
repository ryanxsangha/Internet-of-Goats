#!/usr/bin/env python3
import sys, socket, json, time
import matplotlib.pyplot as plt
import sensor_polling

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

def recv_token():
    server.settimeout(TIMEOUT*3)
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
            token = [ sensor_polling.get_local_measurements() ]
            print(f"[start] initial token = {token}")
            forward_token(token)
            token = recv_token()
            continue

        tok = recv_token()

        if tok is None and role != "plot":
            print(f"[{role}] no token — re-initiating token ring")
            token = [ sensor_polling.get_local_measurements() ]
            forward_token(token)
            time.sleep(RETRY_PAUSE)
            continue

        token = tok or []  

        print(f"[{role}] got token: {token}")
        token.append(sensor_polling.get_local_measurements())

        plot_token(token, round_num)
        round_num += 1
        time.sleep(PLOT_PAUSE)

        forward_token(token)

except KeyboardInterrupt:
    print(f"\n[{role}] shutting down")

