# main.py
import time
import gps_parse

while True:
    lat = gps_parse.get_latitude()
    lon = gps_parse.get_longitude()
    speed = gps_parse.get_speed()
    direction = gps_parse.get_direction()

    print(f"Lat: {lat}, Lon: {lon}, Speed: {speed:.2f} mph, Dir: {direction}")
    time.sleep(1)
