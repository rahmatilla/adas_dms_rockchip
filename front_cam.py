import cv2
import time
import platform
from ultralytics import YOLO
from local_functions import (
    MODEL_PATH, FRONT_MODEL, LANE_MODEL, CAMERA_TYPE, REF_IMAGES, focal_length, distance_finder, get_width, getColours, play_alert, is_lane_departure_and_fast_lane
)
from collections import deque

# Detect platform and set camera source
CAMERA_INDEX = 0
CAMERA_INDEX_LINUX = 51
os_name = platform.system()
is_windows = os_name == 'Windows'

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

    frame_id += 1

    # Reset class detection buffer
    for cls in object_class:
        class_buffer[cls].append(0)
    if frame_id % 2 == 0:
        results = front_model.predict(frame)
        for result in results:
            class_names = result.names
            for box in result.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                cls_id = int(box.cls[0])
                class_name = class_names[cls_id]

                conf = float(box.conf[0])
                if conf < 0.4:
                    continue

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
        current_time = time.time()
        for cls, buf in class_buffer.items():
            if sum(buf) / buffer_len >= 0.4 and current_time - cooldown_class[cls] >= 5:
                play_alert(cls)
                cooldown_class[cls] = current_time

    # Display result
    # try:
    #     cv2.imshow("ADAS View", frame)
    #     if cv2.waitKey(1) == ord("q"):
    #         break
    # except cv2.error as e:
    #     print("cv2.imshow error (no GUI):", e)

cap.release()
cv2.destroyAllWindows()
