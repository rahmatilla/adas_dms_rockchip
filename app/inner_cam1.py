import cv2
import json
import time
import platform
from collections import deque
from datetime import datetime, timedelta
from ultralytics import YOLO

from local_functions1 import (
    LOCAL_PATH,
    MODEL_PATH,
    REMOTE_PATH,
    INNER_MODEL,
    CAMERA_TYPE,
    getColours,
    save_upload_in_background,
    play_alert
)

# ---------------- CONFIG ------------------
CAMERA_INDEX = 1
CAMERA_INDEX_LINUX = 2
BUFFER_LEN = 20
COOLDOWN_THRESHOLD = 30
VIOLATION_CLASSES = {
    'drinking', 'eating', 'eyes_closed', 'mobile_usage', 'no_seatbelt',
    'smoking', 'yawn', "inattentive_driving"
}
OBSTRUCTION_CLASSES = {
    'eyes_closed', 'yawn', 'inattentive_driving', "awake"
}

# ---------------- INIT ------------------
os_name = platform.system()
is_windows = os_name == 'Windows'
class_buffer = {cls: deque([0] * BUFFER_LEN, maxlen=BUFFER_LEN) for cls in VIOLATION_CLASSES}

inner_model = YOLO(MODEL_PATH + INNER_MODEL)

camera = None

if is_windows:
    camera = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)
    camera.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    camera.set(cv2.CAP_PROP_FPS,30)
    camera.set(cv2.CAP_PROP_FRAME_WIDTH,1920)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT,1080)
else:
    if CAMERA_TYPE == "usb":
        camera = cv2.VideoCapture(CAMERA_INDEX_LINUX, cv2.CAP_V4L2)
        camera.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        camera.set(cv2.CAP_PROP_FPS,30)
        camera.set(cv2.CAP_PROP_FRAME_WIDTH,1280)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT,720)
    elif CAMERA_TYPE == "csi":
        from nanocamera import Camera
        camera = Camera(device_id=0, fps=25, width=1280, height=720, flip=0)

cooldown_timers = {cls: 0 for cls in VIOLATION_CLASSES}
detected_violations = set()
detected_classes = set()
last_seen_driver = time.time()

# ---------------- MAIN LOOP ------------------
while True:
    # -------- Read frame --------
    if CAMERA_TYPE == "usb":
        ret, frame = camera.read()
        if not ret:
            continue
    elif CAMERA_TYPE == "csi":
        frame = camera.read()
        if frame is None:
            continue
    
    results = inner_model.predict(frame, verbose=False)

    for cls in VIOLATION_CLASSES:
        class_buffer[cls].append(0)

    result = results[0]
    class_names = result.names
    for box in result.boxes:
        x1, y1, x2, y2 = map(int, box.xyxy[0])
        cls_id = int(box.cls[0])
        cls_name = class_names[cls_id]
        conf = float(box.conf[0])

        threshold = 0.7 if cls_name == "eyes_closed" else 0.4
        if conf > threshold:
            color = getColours(cls_id)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(frame, f'{cls_name} {conf:.2f}', (x1, y1),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, color, 2)

            if cls_name in VIOLATION_CLASSES:
                class_buffer[cls_name][-1] = 1

            if cls_name in OBSTRUCTION_CLASSES:
                last_seen_driver = time.time()

    now = time.time()
    for cls, buf in class_buffer.items():
        if sum(buf) / BUFFER_LEN >= 0.8:
            if now - cooldown_timers[cls] >= COOLDOWN_THRESHOLD:
                detected_violations.add(cls)
                cooldown_timers[cls] = now
                play_alert(cls)
            class_buffer[cls].clear()
            class_buffer[cls].extend([0] * BUFFER_LEN)

    if now - last_seen_driver > 10:
        if "camera_obstructed" not in class_buffer:
            class_buffer["camera_obstructed"] = deque([1] * BUFFER_LEN, maxlen=BUFFER_LEN)
            cooldown_timers["camera_obstructed"] = 0
        if now - cooldown_timers["camera_obstructed"] >= COOLDOWN_THRESHOLD:
            detected_violations.add("camera_obstructed")
            cooldown_timers["camera_obstructed"] = now
            play_alert("camera_obstructed")

    if detected_violations:
        detected_classes.update(detected_violations)
        detected_violations.clear()
    
    if detected_classes:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_body = json.dumps({
            "driver_name": "driver01",
            "violation_type": ' '.join(detected_classes),
            "timestamp": timestamp,
        })
        save_upload_in_background(frame_buffer, output_file, FPS, json_body, audio_file)
        detected_classes.clear()

    try:
        cv2.namedWindow('Driver Monitor', cv2.WINDOW_NORMAL)
        cv2.resizeWindow('Driver Monitor', 960,540)
        cv2.imshow('Driver Monitor', frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
    except cv2.error as e:
        print("cv2.imshow error (no GUI):", e)
# -------- CLEANUP --------
camera.release()
cv2.destroyAllWindows()
