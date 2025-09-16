import os
import time
import threading
import subprocess
import json
from collections import deque
from datetime import datetime
import numpy as np

import cv2
import paramiko
from scp import SCPClient
import requests
from dotenv import load_dotenv 
import sounddevice as sd
import soundfile as sf
import pygame

# =====================
# CONFIG & CONSTANTS
# =====================
load_dotenv()
os.environ["ULTRALYTICS_NO_CHECK"] = "1"

AUDIO_SR = 44100
CHANNELS = 1
BUFFER_SECONDS = 60
FRAME_RATE = 30         # FPS ni haqiqiy kameraga qarab moslang
CLIP_SECONDS = 6
CLIP_FRAMES = FRAME_RATE * CLIP_SECONDS
POST_TRIGGER_WAIT_SEC = 3

# video bufferlar
inner_buffer = deque(maxlen=FRAME_RATE * BUFFER_SECONDS)
front_buffer = deque(maxlen=FRAME_RATE * BUFFER_SECONDS)
inner_lock = threading.Lock()
front_lock = threading.Lock()

# audio buffer
audio_buffer = deque(maxlen=AUDIO_SR * BUFFER_SECONDS)
audio_lock = threading.Lock()
recording = True

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BASE_DIR)

# server parametrlari
REMOTE_HOST = os.getenv("REMOTE_HOST")
REMOTE_PORT = int(os.getenv("REMOTE_PORT") or 22)
LOGIN = os.getenv("LOGIN")
PASSWORD = os.getenv("PASSWORD")
REMOTE_PATH = os.getenv("REMOTE_PATH")
LOCAL_PATH = os.path.join(PARENT_DIR, os.getenv("LOCAL_PATH"))
MODEL_PATH = os.path.join(PARENT_DIR, os.getenv("MODEL_PATH"))
SOUND_PATH = os.path.join(BASE_DIR, os.getenv("SOUND_PATH"))
REF_IMAGES = os.path.join(BASE_DIR, os.getenv("REF_IMAGES"))  
INNER_MODEL = os.getenv("INNER_MODEL")
FRONT_MODEL = os.getenv("FRONT_MODEL")
LANE_MODEL = os.getenv("LANE_MODEL")
CAMERA_TYPE = os.getenv("CAMERA_TYPE")
URL = os.getenv("URL")
headers = {"Content-Type": "application/json", "Accept": "application/json"}

pygame.mixer.init()

# =====================
# AUDIO FUNCTIONS
# =====================
def audio_record_loop():
    """Doimiy audio yozish sikli (background-da ishga tushadi)."""
    def callback(indata, frames, time_info, status):
        with audio_lock:
            audio_buffer.extend(indata[:, 0])  # faqat mono kanal
    with sd.InputStream(samplerate=AUDIO_SR, channels=CHANNELS, callback=callback):
        while recording:
            sd.sleep(100)

def save_last_audio_clip(filename: str, duration_sec: int = CLIP_SECONDS):
    """Oxirgi duration_sec soniyalik audioni faylga yozadi."""
    n_samples = duration_sec * AUDIO_SR
    with audio_lock:
        samples = list(audio_buffer)[-n_samples:]
    if samples:
        sf.write(filename, np.array(samples), AUDIO_SR)

# =====================
# VIDEO FUNCTIONS
# =====================
def save_video(frames_list, output_file, fps=FRAME_RATE, audio_file=None):
    """Framelar va ixtiyoriy audio bilan H.264 video yozish."""
    if len(frames_list) == 0:
        raise ValueError("No frames to save")
    height, width, _ = frames_list[0].shape
    command = [
        "ffmpeg", "-y", "-f", "rawvideo", "-vcodec", "rawvideo", "-pix_fmt", "bgr24",
        "-s", f"{width}x{height}", "-r", str(fps), "-i", "-"
    ]
    if audio_file and os.path.exists(audio_file):
        command += ["-i", audio_file, "-c:a", "aac", "-b:a", "96k"]
    command += [
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-crf", "28", "-preset", "ultrafast", "-shortest", output_file
    ]

    proc = subprocess.Popen(command, stdin=subprocess.PIPE)
    for frame in frames_list:
        proc.stdin.write(frame.astype(np.uint8).tobytes())
    proc.stdin.close()
    proc.wait()

def upload_to_server(file_path, json_body=None):
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(REMOTE_HOST, port=REMOTE_PORT, username=LOGIN, password=PASSWORD)
        with SCPClient(ssh.get_transport()) as scp:
            scp.put(file_path, REMOTE_PATH)
        ssh.close()
        if URL and json_body:
            requests.post(url=URL, headers=headers, data=json_body, verify=False)
    except Exception as e:
        print(f"[upload_to_server] Upload failed: {e}")

# =====================
# BUFFER HELPERS
# =====================
def append_to_buffer(which: str, frame):
    """Frame ni mos bufferga qo‘shish."""
    if which == "inner":
        with inner_lock:
            inner_buffer.append(frame.copy())
    elif which == "front":
        with front_lock:
            front_buffer.append(frame.copy())
    else:
        raise ValueError("which must be 'inner' or 'front'")

def extract_last_n_frames_from_buffer(which: str, n_frames: int):
    """Oxirgi n_frames framelarni chiqarib olish."""
    if which == "inner":
        with inner_lock:
            lst = list(inner_buffer)[-n_frames:]
    elif which == "front":
        with front_lock:
            lst = list(front_buffer)[-n_frames:]
    else:
        raise ValueError("which must be 'inner' or 'front'")
    return [f.copy() for f in lst]

# =====================
# VIOLATION HANDLER
# =====================
def _violation_worker(detected_classes: set, driver_name="driver01"):
    """Asl worker: 3 sekund kutadi, oxirgi 6 sekund audio+videoni saqlaydi va yuklaydi."""
    try:
        time.sleep(POST_TRIGGER_WAIT_SEC)

        # bufferdan oxirgi 6s framelar
        inner_frames = extract_last_n_frames_from_buffer("inner", CLIP_FRAMES)
        front_frames = extract_last_n_frames_from_buffer("front", CLIP_FRAMES)

        # audio chiqish fayli
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        audio_file = os.path.join(LOCAL_PATH, f"{ts}_audio.wav")
        save_last_audio_clip(audio_file, CLIP_SECONDS)

        # video fayllar
        cls_str = "-".join(sorted(detected_classes)) if detected_classes else "unknown"
        inner_name = f"{ts}-inner-{cls_str}.mp4"
        front_name = f"{ts}-front-{cls_str}.mp4"
        inner_out = os.path.join(LOCAL_PATH, inner_name)
        front_out = os.path.join(LOCAL_PATH, front_name)

        os.makedirs(LOCAL_PATH, exist_ok=True)

        if inner_frames:
            save_video(inner_frames, inner_out, fps=FRAME_RATE, audio_file=audio_file)
            json_body = {
                "driver_name": driver_name,
                "violation_type": " ".join(sorted(detected_classes)),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "video_path": f"{REMOTE_PATH}{inner_name}"
            }
            # upload_to_server(inner_out, json.dumps(json_body))

        if front_frames:
            save_video(front_frames, front_out, fps=FRAME_RATE, audio_file=audio_file)
            json_body = {
                "driver_name": driver_name,
                "violation_type": " ".join(sorted(detected_classes)),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "video_path": f"{REMOTE_PATH}{front_name}"
            }
            # upload_to_server(front_out, json.dumps(json_body))

        # vaqtincha audio faylni o‘chirib tashlash mumkin
        if os.path.exists(audio_file):
            os.remove(audio_file)

    except Exception as e:
        print(f"[violation_worker] Error: {e}")

def trigger_violation(detected_classes: set, driver_name="driver01"):
    """Violation aniqlanganda chaqiriladi."""
    classes_copy = set(detected_classes) if detected_classes else set()
    t = threading.Thread(target=_violation_worker, args=(classes_copy, driver_name), daemon=True)
    t.start()
    return t

def getColours(cls_num):
    base = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]
    incs = [(1, -2, 1), (-2, 1, -1), (1, -1, 2)]
    idx = cls_num % len(base)
    color = [base[idx][i] + incs[idx][i] * (cls_num // len(base)) % 256 for i in range(3)]
    return tuple(color)
violation_sounds = {
    "drinking": f"{SOUND_PATH}drinking.mp3",
    "eating": f"{SOUND_PATH}eating.mp3",
    "eyes_closed": f"{SOUND_PATH}eyes_closed.mp3",
    "mobile_usage": f"{SOUND_PATH}mobile_usage.mp3",
    "no_seatbelt": f"{SOUND_PATH}no_seatbelt.mp3",
    "smoking": f"{SOUND_PATH}smoking.mp3",
    "yawn": f"{SOUND_PATH}yawn.mp3",
    "inattentive_driving": f"{SOUND_PATH}inattentive_driving.mp3",
    "camera_obstructed": f"{SOUND_PATH}camera_obstructed.mp3",
    "car": f"{SOUND_PATH}car.mp3",
    "do_not_enter": f"{SOUND_PATH}do_not_enter.mp3",
    "do_not_stop": f"{SOUND_PATH}do_not_stop.mp3",
    "do_not_turn_l": f"{SOUND_PATH}do_not_turn_l.mp3",
    "do_not_turn_r": f"{SOUND_PATH}do_not_turn_r.mp3",
    "do_not_u_turn": f"{SOUND_PATH}do_not_u_turn.mp3",
    "enter_left_lane": f"{SOUND_PATH}enter_left_lane.mp3",
    "green_light": f"{SOUND_PATH}green_light.mp3",
    "left_right_lane": f"{SOUND_PATH}left_right_lane.mp3",
    "no_parking": f"{SOUND_PATH}no_parking.mp3",
    "ped_crossing": f"{SOUND_PATH}ped_crossing.mp3",
    "ped_zebra_cross": f"{SOUND_PATH}ped_zebra_cross.mp3",
    "railway_crossing": f"{SOUND_PATH}railway_crossing.mp3",
    "red_light": f"{SOUND_PATH}red_light.mp3",
    "roundabout": f"{SOUND_PATH}roundabout.mp3",
    "speed_limit_10": f"{SOUND_PATH}speed_limit_10.mp3",
    "speed_limit_100": f"{SOUND_PATH}speed_limit_100.mp3",
    "speed_limit_110": f"{SOUND_PATH}speed_limit_110.mp3",
    "speed_limit_120": f"{SOUND_PATH}speed_limit_120.mp3",
    "speed_limit_130": f"{SOUND_PATH}speed_limit_130.mp3",
    "speed_limit_15": f"{SOUND_PATH}speed_limit_15.mp3",
    "speed_limit_20": f"{SOUND_PATH}speed_limit_20.mp3",
    "speed_limit_30": f"{SOUND_PATH}speed_limit_30.mp3",
    "speed_limit_40": f"{SOUND_PATH}speed_limit_40.mp3",
    "speed_limit_5": f"{SOUND_PATH}speed_limit_5.mp3",
    "speed_limit_50": f"{SOUND_PATH}speed_limit_50.mp3",
    "speed_limit_60": f"{SOUND_PATH}speed_limit_60.mp3",
    "speed_limit_70": f"{SOUND_PATH}speed_limit_70.mp3",
    "speed_limit_80": f"{SOUND_PATH}speed_limit_80.mp3",
    "speed_limit_90": f"{SOUND_PATH}speed_limit_90.mp3",
    "stop": f"{SOUND_PATH}stop.mp3",
    "traffic_light": f"{SOUND_PATH}traffic_light.mp3",
    "truck": f"{SOUND_PATH}truck.mp3",
    "u_turn": f"{SOUND_PATH}u_turn.mp3",
    "warning": f"{SOUND_PATH}warning.mp3",
    "yellow_light": f"{SOUND_PATH}yellow_light.mp3",
    "lane_departure": f"{SOUND_PATH}lane_departure.mp3",
    "bicycle": f"{SOUND_PATH}bicycle.mp3",
    "bus": f"{SOUND_PATH}bus.mp3",
    "motorbike": f"{SOUND_PATH}motorbike.mp3",
    "person": f"{SOUND_PATH}person.mp3",
    "no_vehicles": f"{SOUND_PATH}no_vehicles.mp3",
    "main_road": f"{SOUND_PATH}main_road.mp3",
    "yield": f"{SOUND_PATH}yield_sign.mp3",
    "fast_lane": f"{SOUND_PATH}fast_lane.mp3",
}
def play_alert(violation):
    if violation in violation_sounds:
        threading.Thread(target=lambda: pygame.mixer.Sound(violation_sounds[violation]).play(), daemon=True).start()

def focal_length(measured_distance, real_width, width_in_rf_image):
    return (width_in_rf_image * measured_distance) / real_width

def distance_finder(focal_length, real_width, width_in_frame):
    return (real_width * focal_length) / width_in_frame

def get_width(ref_image, model, cls_name):
    results = model.predict(ref_image)
    for result in results:
        for box in result.boxes:
            cls = int(box.cls[0])
            if cls_name == result.names[cls]:
                x1, _, x2, _ = map(int, box.xyxy[0])
                return x2 - x1
    return None

def check_to_fast_lane(detected_lines: set) -> bool:
    left_options = {
        "left_solid_white",
        "left_solid_yellow",
        "left_double_solid_white",
        "left_double_solid_yellow"
    }

    right_options = {
        "right_broken_white",
        "right_broken_yellow"
    }

    return any(left in detected_lines for left in left_options) and \
           any(right in detected_lines for right in right_options)

def is_lane_departure_and_fast_lane(model, frame, departure_threshold, frame_center_x, height):
    detected_lines = set()
    lanedeparture = False
    fastlane = False
    results = model.predict(source=frame, verbose=False)
    result = results[0]
    classes_names = result.names
    for box in result.boxes:
        [x1, y1, x2, y2] = map(int, box.xyxy[0])
        cls = int(box.cls[0])
        class_name = classes_names[cls]
        x_center = (x1 + x2) / 2
            # Порог вероятности
        threshold =  0.4
        if box.conf[0] > threshold:
            if  x_center < frame_center_x:
                class_name = "left_"+class_name
            else:
                class_name = "right_"+class_name
            detected_lines.add(class_name)
            if abs(x_center - frame_center_x) < departure_threshold:
                lanedeparture = True
            #     cv2.putText(frame, f"Lane departure", (50, 50), fonts, 1, (RED), 2)
            # colour = getColours(cls)
            # cv2.rectangle(frame, (x1, y1), (x2, y2), colour, 2)
            # cv2.putText(frame, f'{class_name} {box.conf[0]:.2f}', (x1, y1),
            #             cv2.FONT_HERSHEY_SIMPLEX, 1, colour, 2)
    if check_to_fast_lane(detected_lines):
        fastlane = True
    # # Нарисовать вертикальную линию в центре кадра (машина)
    # cv2.line(frame, (frame_center_x, 0), (frame_center_x, height), (200, 200, 200), 2)
    return frame, lanedeparture, fastlane