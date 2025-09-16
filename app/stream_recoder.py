import os
import time
import json
from datetime import datetime

from local_functions import (
    extract_last_n_frames_from_buffer,
    save_video,
    upload_to_server,
    LOCAL_PATH,
    REMOTE_PATH,
    FRAME_RATE,
    save_last_audio_clip
)

CLIP_SECONDS = 60  # 1 minut
CLIP_FRAMES = FRAME_RATE * CLIP_SECONDS

def upload_minute_clips(driver_name="driver01"):
    while True:
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")

            # audio fayl (1 minutlik)
            audio_file = os.path.join(LOCAL_PATH, f"{ts}_minute_audio.wav")
            save_last_audio_clip(audio_file, CLIP_SECONDS)

            # inner 1 minut video
            inner_frames = extract_last_n_frames_from_buffer("inner", CLIP_FRAMES)
            if inner_frames:
                inner_name = f"{ts}-inner-minute.mp4"
                inner_out = os.path.join(LOCAL_PATH, inner_name)
                save_video(inner_frames, inner_out, fps=FRAME_RATE, audio_file=audio_file)

                json_body = json.dumps({
                    "driver_name": driver_name,
                    "video_type": "minute_inner",
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "video_path": f"{REMOTE_PATH}{inner_name}"
                })
                upload_to_server(inner_out, json_body)

            # front 1 minut video
            front_frames = extract_last_n_frames_from_buffer("front", CLIP_FRAMES)
            if front_frames:
                front_name = f"{ts}-front-minute.mp4"
                front_out = os.path.join(LOCAL_PATH, front_name)
                save_video(front_frames, front_out, fps=FRAME_RATE, audio_file=audio_file)

                json_body = json.dumps({
                    "driver_name": driver_name,
                    "video_type": "minute_front",
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "video_path": f"{REMOTE_PATH}{front_name}"
                })
                upload_to_server(front_out, json_body)

            # vaqtincha audio faylni o‘chirish
            if os.path.exists(audio_file):
                os.remove(audio_file)

        except Exception as e:
            print(f"[minute_uploader] Error: {e}")

        # 60 sekund kutamiz
        time.sleep(60)

if __name__ == "__main__":
    print("[INFO] Minute uploader started...")
    upload_minute_clips(driver_name="driver01")
