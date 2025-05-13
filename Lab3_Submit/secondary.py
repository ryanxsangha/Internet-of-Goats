#!/usr/bin/env python3
import sensor_polling
import sys
import socket
import json
from datetime import datetime

doingShit = True
REQUEST = b"Requesting Data"
if(len(sys.argv) != 3):
    print(f"Usage: {sys.argv[0]} <host> <port>")
    sys.exit(1)

host, port = sys.argv[1], int(sys.argv[2])
lsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
lsock.bind((host, port))
lsock.listen()
print(f"Listening on {(host, port)}")
lsock.setblocking(True)

while doingShit:
    conn, addr = lsock.accept()
    current_time = datetime.now().strftime("%m-%d-%Y      %H:%M:%S")
    with conn:
        print(f"{current_time}\nConnection on {addr}")
        try:
            req = conn.recv(1024)
            if req.strip() == REQUEST:
                data = sensor_polling.get_local_measurements()
                payload = json.dumps(data).encode()
                conn.sendall(payload)
                print(f"Payload sent to {addr}\n")
            else:
                print(f"Weird ass request or something for {addr}\n")
        except Exception as e:
            print(f"Network error polling {host}:{port}: {e!r}")