import os
import platform
import subprocess
import threading
from datetime import datetime

RECORD_DIR = "./recordings"
os.makedirs(RECORD_DIR, exist_ok=True)

DURATION = 60  # секунд

# Укажем источники камер и микрофонов
FRONT_CAM_SRC = "/dev/video0"   # Jetson/Линукс
INNER_CAM_SRC = "/dev/video1"
FRONT_AUDIO_SRC = "hw:1,0"      # Jetson ALSA
INNER_AUDIO_SRC = "hw:1,0"

# Windows примеры
WIN_FRONT_CAM = "FHD Camera"
WIN_INNER_CAM = "HD User Facing"
WIN_FRONT_MIC = "Microphone (FHD Camera AC)"
WIN_INNER_MIC = "Microphone Array (Realtek(R) Audio)"


def get_timestamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def record_camera(name, video_src, audio_src, is_windows=False, is_jetson=False):
    ts = get_timestamp()
    out_file = os.path.join(RECORD_DIR, f"{name}_{ts}.mp4")

    if is_windows:
        # Windows → DirectShow
        cmd = [
            "ffmpeg", "-y", "-t", str(DURATION),
            "-f", "dshow", "-i", f"video={video_src}:audio={audio_src}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-pix_fmt", "yuv420p", out_file
        ]

    elif is_jetson:
        # Jetson → GStreamer
        if "video1" in video_src:
            sensor_id = 1
        else:
            sensor_id = 0
        cmd = [
            "gst-launch-1.0",
            "nvarguscamerasrc", f"sensor-id={sensor_id}", "!", 
            "video/x-raw(memory:NVMM),width=1280,height=720,framerate=30/1", "!",
            "nvvidconv", "!", "nvv4l2h264enc", "!", "mp4mux", "!",
            f"filesink", f"location={out_file}", "-e"
        ]

    else:
        # Linux PC → ffmpeg (v4l2 + alsa)
        cmd = [
            "ffmpeg", "-y", "-t", str(DURATION),
            "-f", "v4l2", "-framerate", "30", "-video_size", "1280x720", "-i", video_src,
            "-f", "alsa", "-i", audio_src,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-pix_fmt", "yuv420p", out_file
        ]

    print(f"[INFO] Запись {name} в {out_file}")
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Ошибка записи {name}: {e}")



def main():
    system = platform.system().lower()
    is_windows = system == "windows"
    is_jetson = os.path.exists("/usr/sbin/nvargus-daemon")  # простая проверка Jetson

    if is_windows:
        cams = [
            ("front", WIN_FRONT_CAM, WIN_FRONT_MIC),
            ("inner", WIN_INNER_CAM, WIN_INNER_MIC)
        ]
    elif is_jetson:
        cams = [
            ("front", FRONT_CAM_SRC, FRONT_AUDIO_SRC),
            ("inner", INNER_CAM_SRC, INNER_AUDIO_SRC)
        ]
    else:
        cams = [
            ("front", FRONT_CAM_SRC, FRONT_AUDIO_SRC),
            ("inner", INNER_CAM_SRC, INNER_AUDIO_SRC)
        ]

    threads = []
    for name, vsrc, asrc in cams:
        t = threading.Thread(target=record_camera, args=(name, vsrc, asrc, is_windows, is_jetson))
        t.start()
        threads.append(t)

    for t in threads:
        t.join()


if __name__ == "__main__":
    main()
