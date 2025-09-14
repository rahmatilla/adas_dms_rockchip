import subprocess
import time
import threading
import requests
from datetime import datetime, timedelta
import os

SERVER_URL = "http://your-server/upload_video"
FRONT_CAM_SRC = "/dev/video0"   # фронтальная камера
INNER_CAM_SRC = "/dev/video1"   # внутренняя камера
FRONT_AUDIO_SRC = "hw:1,0"      # микрофон для фронтальной камеры
INNER_AUDIO_SRC = "hw:2,0"      # микрофон для внутренней камеры
DURATION = 60  # секунд
OUTPUT_DIR = "./recordings"
RETENTION_HOURS = 24  # хранить сутки
os.makedirs(OUTPUT_DIR, exist_ok=True)


def cleanup_old_files():
    """Удаляет файлы старше суток"""
    now = datetime.now()
    for fname in os.listdir(OUTPUT_DIR):
        fpath = os.path.join(OUTPUT_DIR, fname)
        if os.path.isfile(fpath):
            mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
            if now - mtime > timedelta(hours=RETENTION_HOURS):
                try:
                    os.remove(fpath)
                    print(f"🗑 Удалён старый файл: {fpath}")
                except Exception as e:
                    print(f"⚠️ Ошибка удаления {fpath}: {e}")


def record_camera(cam_src, audio_src, prefix):
    while True:
        filename = f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
        filepath = os.path.join(OUTPUT_DIR, filename)

        # ffmpeg: видео H.264 + звук AAC
        cmd = [
            "ffmpeg",
            "-y",
            "-t", str(DURATION),
            "-f", "v4l2", "-i", cam_src,        # видео (V4L2)
            "-f", "alsa", "-i", audio_src,      # звук (ALSA)
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-pix_fmt", "yuv420p",
            filepath
        ]

        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            print(f"✅ Записано видео+звук: {filepath}")
        except subprocess.CalledProcessError as e:
            print(f"❌ Ошибка записи {prefix}: {e}")
            time.sleep(5)
            continue

        # Отправляем на сервер
        try:
            with open(filepath, "rb") as f:
                files = {"file": (filename, f, "video/mp4")}
                r = requests.post(SERVER_URL, files=files, timeout=120)
                if r.status_code == 200:
                    print(f"📤 Успешно отправлено: {filepath}")
                else:
                    print(f"⚠️ Ошибка при отправке {filepath}: {r.status_code}")
        except Exception as e:
            print(f"❌ Ошибка загрузки {filepath}: {e}")

        # Удаляем старые записи
        cleanup_old_files()


def main():
    t1 = threading.Thread(target=record_camera, args=(FRONT_CAM_SRC, FRONT_AUDIO_SRC, "front"))
    t2 = threading.Thread(target=record_camera, args=(INNER_CAM_SRC, INNER_AUDIO_SRC, "inner"))

    t1.start()
    t2.start()

    t1.join()
    t2.join()


if __name__ == "__main__":
    main()
