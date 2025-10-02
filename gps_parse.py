import serial
import pynmea2
import time
import threading

PORT = "/dev/ttyUSB1"
BAUD = 115200

# Shared data (will be updated by background thread)
_gps_data = {
    "lat": None,
    "lon": None,
    "speed_mph": 0.0,
    "direction": "N/A",
}

def _degrees_to_direction(deg):
    if deg is None:
        return "N/A"
    deg = float(deg)
    if (deg >= 337.5) or (deg < 22.5):
        return "N"
    elif deg < 67.5:
        return "NE"
    elif deg < 112.5:
        return "E"
    elif deg < 157.5:
        return "SE"
    elif deg < 202.5:
        return "S"
    elif deg < 247.5:
        return "SW"
    elif deg < 292.5:
        return "W"
    else:
        return "NW"

def _open_serial():
    while True:
        try:
            ser = serial.Serial(PORT, BAUD, timeout=1)
            return ser
        except serial.SerialException:
            time.sleep(2)

def _gps_thread():
    ser = _open_serial()
    while True:
        try:
            line = ser.readline().decode('ascii', errors='replace').strip()
            if line.startswith('$GPRMC'):
                try:
                    msg = pynmea2.parse(line)

                    # Latitude / Longitude
                    _gps_data["lat"] = msg.latitude
                    _gps_data["lon"] = msg.longitude

                    # Speed
                    speed_knots = msg.spd_over_grnd
                    if speed_knots is None or speed_knots == "":
                        speed_knots = 0.0
                    else:
                        speed_knots = float(speed_knots)
                    _gps_data["speed_mph"] = speed_knots * 1.15078

                    # Direction
                    _gps_data["direction"] = _degrees_to_direction(msg.true_course)

                except pynmea2.ParseError:
                    pass
        except serial.SerialException:
            ser.close()
            ser = _open_serial()

# Start background GPS reading when module is imported
thread = threading.Thread(target=_gps_thread, daemon=True)
thread.start()

# 🧭 Public getter functions
def get_latitude():
    return _gps_data["lat"]

def get_longitude():
    return _gps_data["lon"]

def get_speed():
    return _gps_data["speed_mph"]

def get_direction():
    return _gps_data["direction"]
