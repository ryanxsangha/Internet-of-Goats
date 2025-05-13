#!/usr/bin/env python3
import sensor_polling
import json
import sys
import socket
import time
import matplotlib.pyplot as plt

REQUEST = b"Requesting Data"

if len(sys.argv) != 5:
    print(f"Usage: {sys.argv[0]} <secondary_host1> <secondary_port1> <seondary_host2> <secondary_port2>")
    sys.exit(1)

host1, port1 = (sys.argv[1], int(sys.argv[2]))
host2, port2 = (sys.argv[3], int(sys.argv[4]))
doingShit = True

client1, client2 = (host1, port1), (host2, port2)
clients = [client1, client2]

def request_readings(host, port):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(5) #5 second time interval
            sock.connect((host, port))
            sock.sendall(REQUEST)
            data = sock.recv(2048)
        return json.loads(data.decode())

    except socket.timeout:
        print(f"Timeout upon request to {host} : {port} cause homie slow\n")
    except Exception as e:
        print(f"Network error polling {host}:{port}: {e!r}")


    return None

def plot_round(local, measurements, roundNum):
    metrics = ['temperature', 'humidity', 'soil_moisture', 'wind_speed']
    titles  = ['Temperature Sensor', 'Humidity Sensor',
               'Soil Moisture Sensor', 'Wind Sensor']
    ylabels = ['Temperature (°C)', 'Humidity (%)',
               'Soil moisture', 'Wind speed (m/s)']

    data_matrix = []
    for metric in metrics:
        vals = [ measurements[0].get(metric) if measurements[0] else None,
                 measurements[1].get(metric) if measurements[1] else None,
                 local.get(metric),
               ]
        #average of the readings
        clean = [v for v in vals if v is not None]
        avg = sum(clean) / len(clean) if clean else None
        vals.append(avg)
        data_matrix.append(vals)

    x = [0, 1, 2, 3]
    labels = ['Sec1', 'Sec2', 'Primary', 'Avg']
    colors = ['red', 'blue', 'green', 'black']

    #makes the subplots
    fig, axes = plt.subplots(2, 2, figsize=(10, 8))
    axes = axes.flatten()

    for idx, ax in enumerate(axes):
        vals = data_matrix[idx]
        ax.set_xticks(x)
        ax.set_xticklabels(labels)
        ax.set_title(titles[idx])
        ax.set_ylabel(ylabels[idx])
        ax.grid(True, linestyle='--', alpha=0.5)
        for xi, c in zip(x, colors):
            y = vals[xi]
            if y is None:
                ax.scatter(xi, y, marker='x', color='gray', s=100)
            else:
                ax.scatter(xi, y, color=c, s=50)

    fig.tight_layout()
    fig.savefig(f"polling-plot-{roundNum}.png")
    plt.close(fig)


def main():
    roundNum = 1
    while doingShit:
        local_readings = sensor_polling.get_local_measurements()
        print(f"Local Readings: {local_readings}")
        measurements = []
        for host, port in clients:
            clientData = request_readings(host, port)
            print(f"From {host} : {port} => {clientData}")
            measurements.append(clientData)

        plot_round(local_readings, measurements, roundNum)
        print(f"Saved plot to polling-plot-{roundNum}.png")
        roundNum += 1
        time.sleep(3)


if __name__ == "__main__":
    main()


              

