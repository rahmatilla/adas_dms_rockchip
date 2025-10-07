import threading, os, time, subprocess

subprocess.Popen(["python3", "front_cam_new.py"])
subprocess.Popen(["python3", "inner_cam_new.py"])

print("[INFO] ADAS/DMS system started.")
while True:
    time.sleep(1)

