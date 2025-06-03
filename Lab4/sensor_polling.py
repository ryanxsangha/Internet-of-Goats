#!/usr/bin/env python3

import time
import board
import busio
from datetime import datetime
import adafruit_sht31d
from adafruit_seesaw.seesaw import Seesaw
import adafruit_ads1x15.ads1015 as ADS
from adafruit_ads1x15.analog_in import AnalogIn
from simpleio import map_range
LOG = "polling-log.txt"     

ANEM_MIN_VOLT    = 0.4         
ANEM_MAX_VOLT    = 2.0         
MAX_WIND_SPEED   = 32.4        

i2c = busio.I2C(board.SCL, board.SDA)

sht31 = adafruit_sht31d.SHT31D(i2c)

ss = Seesaw(i2c, addr=0x36)

ads  = ADS.ADS1015(i2c)
wind_chan = AnalogIn(ads, ADS.P0)

def read_temperature_humidity():
    t = sht31.temperature
    h = sht31.relative_humidity
    return t, h

def read_soil():
    m = ss.moisture_read()
    t = ss.get_temp()
    return t, m

def read_wind_speed():
    v = wind_chan.voltage
    v_clamped = min(max(v, ANEM_MIN_VOLT), ANEM_MAX_VOLT)
    speed = map_range(v_clamped,
                      ANEM_MIN_VOLT, ANEM_MAX_VOLT,
                      0.0, MAX_WIND_SPEED)
    return v, speed

def log_readings():
    now = datetime.now().strftime("%m-%d-%Y %H:%M:%S")
    t, h      = read_temperature_humidity()
    soil_t, m = read_soil()
    v, wind   = read_wind_speed()

    line = (
        f"{now}  \n"
        f"Temperature: {t:.3f}°C  \r\n"
        f"Humidity: {h:.3f}%  \r\n"
        f"Soil Moisture: {m:.3f}  \r\n"
        f"Soil Temperature: {soil_t:.3f}°C  \r\n"
        f"Wind speed: {wind:.3f} m/s\r\n\r\n"
    )

    with open(LOG, "a") as f:
        f.write(line)

def get_local_measurements(node=None):
    """
    Returns all four sensor readings as a dict:
      {
        'temperature': float (°C),
        'humidity': float (%),
        'soil_moisture': float (raw value),
        'wind_speed': float (m/s)
      }
    """
    t, h      = read_temperature_humidity()
    soil_t, m = read_soil()
    _, wind   = read_wind_speed()
    return {
        'temperature':   t,
        'humidity':      h,
        'soil_moisture': m,
        'soil_temperature': soil_t,
        'wind_speed':    wind,
        'node' : node
    }

if __name__ == "__main__":
    with open(LOG, "a") as f:
        f.write("Isaac Garibay\n")
    while True:
        log_readings()
        time.sleep(5)
