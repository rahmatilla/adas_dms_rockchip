import cv2
import time
import json
import platform
from ultralytics import YOLO
from datetime import datetime, timedelta
from local_functions_new import (
    check_buffer,
    MODEL_PATH, 
    LOCAL_PATH, 
    REMOTE_PATH, 
    FRONT_MODEL, 
    LANE_MODEL, 
    CAMERA_TYPE,
    AUDIO_DEVICE_FRONT,
    REF_IMAGES, 
    get_width, 
    getColours,
    save_upload_in_background,
    play_alert, 
    is_lane_departure_and_fast_lane, 
    audio_record_loop
)
from collections import deque

# Detect platform and set camera source
CAMERA_INDEX = 1
CAMERA_INDEX_LINUX = 6
os_name = platform.system()
is_windows = os_name == 'Windows'
COOLDOWN_THRESHOLD = 30

VIOLATION_CLASSES = {
    'lane_departure', 'fast_lane', 'follow_distance', 'shoulder_stop', 'red_light', 'stop'
}

# Define known measurements for distance estimation
known_distance = {"truck": 7, "car": 7}  # meters
known_width = {"truck": 2.45, "car": 1.8}  # meters

# UI elements
GREEN = (0, 255, 0)
RED = (0, 0, 255)
fonts = cv2.FONT_HERSHEY_COMPLEX

# Load YOLO models
model_lane = YOLO(MODEL_PATH + LANE_MODEL)
front_model = YOLO(MODEL_PATH + FRONT_MODEL)

# Class configuration
object_class = list(front_model.names.values()) + ["lane_departure", "fast_lane"]
buffer_len = 10
class_buffer = {cls: deque([0] * buffer_len, maxlen=buffer_len) for cls in object_class}
cooldown_class = {cls: 0 for cls in object_class}

# Load reference images and compute scale factors for distance estimation
ref_image_truck = cv2.imread(REF_IMAGES + "truck.jpg")
ref_image_car = cv2.imread(REF_IMAGES + "car.jpg")

ref_image_width = {
    "truck": ref_image_truck.shape[1],
    "car": ref_image_car.shape[1],
}

object_width_in_ref = {
    "truck": get_width(ref_image_truck, front_model, "truck"),
    "car": get_width(ref_image_car, front_model, "car"),
}

normalized_width_ref = {
    cls: object_width_in_ref[cls] / ref_image_width[cls] for cls in known_distance
}

scale_factor = {
    cls: known_distance[cls] * normalized_width_ref[cls] for cls in known_distance
}

# Initialize video capture

if is_windows:
    cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)
    frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
else:
    if CAMERA_TYPE == "usb":
        cap = cv2.VideoCapture(CAMERA_INDEX_LINUX)
        frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    elif CAMERA_TYPE == "csi":
        from nanocamera import Camera
        cap = Camera(device_id=1, fps=30, width=1280, height=720, flip=0)
        frame_width = cap.width
        frame_height = cap.height

middle_x = frame_width // 2
departure_threshold = frame_width // 15

frame_id = 0
detected_violations = set()
detected_classes = set()
is_buffer_ready = False

last_minute = None
FPS = 12
VIDEO_FRAME_LEN = 60*FPS
frame_buffer =[]   #deque(maxlen=VIDEO_FRAME_LEN)
starttime = time.time()

# ---------------- START AUDIO ------------------
import threading
threading.Thread(target=audio_record_loop, args=(AUDIO_DEVICE_FRONT,), daemon=True).start()

print("[INFO] Front camera started...")

# Main loop
while True:
    # -------- Read frame --------
    if CAMERA_TYPE == "usb":
        ret, frame = cap.read()
        if not ret:
            continue
    elif CAMERA_TYPE == "csi":
        frame = cap.read()
        if frame is None:
            continue
    
    current_time = datetime.now()
    current_minute = current_time.replace(second=0, microsecond=0)

    frame_id += 1
    frame_buffer.append(frame)

    # Reset class detection buffer
    for cls in object_class:
        class_buffer[cls].append(0)
    if frame_id % 2 == 0:
        results = front_model.predict(frame, verbose=False)
        result = results[0]
        class_names = result.names
        for box in result.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            cls_id = int(box.cls[0])
            class_name = class_names[cls_id]

            conf = float(box.conf[0])
            if conf < 0.4:
                continue

            if class_name in VIOLATION_CLASSES:
                class_buffer[class_name][-1] = 1

            # Estimate distance if object is centered
            if x1 < middle_x < x2 and class_name in ["car", "truck"]:
                obj_width_in_frame = x2 - x1
                normalized_width = obj_width_in_frame / frame_width
                if normalized_width > 0:
                    distance = scale_factor[class_name] / normalized_width
                    cv2.putText(frame, f"Distance = {distance:.2f}m", (50, 50), fonts, 0.6, RED, 2)
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (GREEN), 2)
                    cv2.putText(frame, f'{class_name} {conf:.2f}', (x1, y1), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (GREEN), 2)
            else:
                colour = getColours(cls_id)
                cv2.rectangle(frame, (x1, y1), (x2, y2), colour, 2)
                cv2.putText(frame, f'{class_name} {conf:.2f}', (x1, y1), cv2.FONT_HERSHEY_SIMPLEX, 0.7, colour, 2)

        # Lane departure detection
        frame, lane_departure, fast_lane = is_lane_departure_and_fast_lane(model_lane, frame, departure_threshold, middle_x, frame_height)
        if lane_departure:
            class_buffer["lane_departure"][-1] = 1
        if fast_lane:
            class_buffer["fast_lane"][-1] = 1    
        # Alert logic
        currenttime = time.time()
        for cls, buf in class_buffer.items():
            if sum(buf) / buffer_len >= 0.4 and currenttime - cooldown_class[cls] >= 5:
                play_alert(cls)
                cooldown_class[cls] = currenttime
                if cls in VIOLATION_CLASSES:
                    detected_violations.add(cls)
                    class_buffer[cls].clear()
                    class_buffer[cls].extend([0] * buffer_len)

        # if detected_violations:
        #     detected_classes.update(detected_violations)
        #     detected_violations.clear()
        #     if not is_buffer_ready:
        #         frame_buffer = check_buffer(frame_buffer, VIDEO_FRAME_LEN // 2)
        #         is_buffer_ready = True

        # if is_buffer_ready and len(frame_buffer) >= VIDEO_FRAME_LEN - 1:
        #     timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        #     fname = f"{timestamp}-{'-'.join(detected_classes)}.mp4"
        #     output_file = f"{LOCAL_PATH}{fname}"
        #     audio_file = f"{LOCAL_PATH}{timestamp}-{'-'.join(detected_classes)}.wav"
        #     json_body = json.dumps({
        #         "driver_name": "driver01",
        #         "violation_type": ' '.join(detected_classes),
        #         "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        #         "video_path": f"{REMOTE_PATH}{fname}"
        #     })

        #     save_upload_in_background(frame_buffer, output_file, FPS, json_body, audio_file)

        #     is_buffer_ready = False
        #     detected_classes.clear()

    if last_minute is None:
        last_minute = current_minute

    if current_time.second == 0 and last_minute != current_minute:
    # if time.time() - starttime >= 60.0:
        # Fayl nomini boshlanish va tugash vaqtiga qarab
        start_time = last_minute.strftime("%H%M%S")
        end_time = (last_minute + timedelta(minutes=1)).strftime("%H%M%S")
        fname = f"{start_time}_{end_time}"
        output_file = f"{LOCAL_PATH}Front_{fname}.mp4"
        audio_file = f"{LOCAL_PATH}Front_{fname}.wav"
        duration_sec = time.time() - starttime
        FPS = len(frame_buffer)/duration_sec
        print("Real FPS",FPS)
        save_upload_in_background(list(frame_buffer), output_file, FPS, {}, audio_file)
        frame_buffer.clear()
        last_minute = current_minute
        starttime = time.time()

    # Display result
    try:
        cv2.imshow("ADAS View", frame)
        if cv2.waitKey(1) == ord("q"):
            break
    except cv2.error as e:
        print("cv2.imshow error (no GUI):", e)

cap.release()
cv2.destroyAllWindows()
