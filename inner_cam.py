import cv2
import json
import time
import threading
import platform
from collections import deque
from datetime import datetime
from ultralytics import YOLO

from local_functions import (
    check_buffer,
    LOCAL_PATH,
    MODEL_PATH,
    REMOTE_PATH,
    INNER_MODEL,
    getColours,
    save_upload_in_background,
    play_alert,
    audio_record_loop
)

# ---------------- CONFIG ------------------
CAMERA_INDEX = 0
CAMERA_INDEX_LINUX = 49
BUFFER_LEN = 20
VIDEO_FRAME_LEN = 180  # 6 sec at 30 FPS
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
frame_buffer = deque(maxlen=VIDEO_FRAME_LEN)
yolo = YOLO(MODEL_PATH + INNER_MODEL)

camera = None

if is_windows:
    camera = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)
    threading.Thread(target=audio_record_loop, daemon=True).start()
else:
    camera = cv2.VideoCapture(CAMERA_INDEX_LINUX)

cooldown_timers = {cls: 0 for cls in VIOLATION_CLASSES}
detected_violations = set()
detected_classes = set()
is_buffer_ready = False
last_seen_driver = time.time()

# ---------------- MAIN LOOP ------------------
while True:
    # -------- Read frame --------
    ret, frame = camera.read()
    if not ret:
        continue

    frame_buffer.append(frame)
    results = yolo(frame, stream=True)

    for cls in VIOLATION_CLASSES:
        class_buffer[cls].append(0)

    for result in results:
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
            if now - cooldown_timers[cls] >= 30:
                detected_violations.add(cls)
                cooldown_timers[cls] = now
                play_alert(cls)
            class_buffer[cls].clear()
            class_buffer[cls].extend([0] * BUFFER_LEN)

    if now - last_seen_driver > 10:
        if "camera_obstructed" not in class_buffer:
            class_buffer["camera_obstructed"] = deque([1] * BUFFER_LEN, maxlen=BUFFER_LEN)
            cooldown_timers["camera_obstructed"] = 0
        if now - cooldown_timers["camera_obstructed"] >= 30:
            detected_violations.add("camera_obstructed")
            cooldown_timers["camera_obstructed"] = now
            play_alert("camera_obstructed")

    if detected_violations:
        detected_classes.update(detected_violations)
        detected_violations.clear()
        if not is_buffer_ready:
            frame_buffer = check_buffer(frame_buffer, VIDEO_FRAME_LEN // 2)
            is_buffer_ready = True

    if is_buffer_ready and len(frame_buffer) >= VIDEO_FRAME_LEN - 1:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"{timestamp}-{'-'.join(detected_classes)}.mp4"
        output_file = f"{LOCAL_PATH}{fname}"
        audio_file = f"{LOCAL_PATH}{timestamp}-{'-'.join(detected_classes)}.wav"
        json_body = json.dumps({
            "driver_name": "driver01",
            "violation_type": ' '.join(detected_classes),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "video_path": f"{REMOTE_PATH}{fname}"
        })

        if is_windows:
            save_upload_in_background(frame_buffer, output_file, 30, json_body, audio_file)
        else:
            save_upload_in_background(frame_buffer, output_file, 30, json_body)

        is_buffer_ready = False
        detected_classes.clear()
    try:
        cv2.imshow('Driver Monitor', frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
    except cv2.error as e:
        print("cv2.imshow error (no GUI):", e)
# -------- CLEANUP --------
camera.release()
cv2.destroyAllWindows()
