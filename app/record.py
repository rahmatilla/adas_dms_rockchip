import os
import subprocess
import threading
import datetime
import logging

# ------------------ Логирование ------------------
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("recorder")

# ------------------ Пути ------------------
RECORD_DIR = "./recordings"
os.makedirs(RECORD_DIR, exist_ok=True)

# ------------------ Камеры + Микрофоны ------------------
FRONT_CAM = 6      # nvarguscamerasrc sensor-id
INNER_CAM = 2
FRONT_AUDIO = "hw:1,0"   # изменить под твой микрофон
INNER_AUDIO = "hw:0,0"   # или hw:1,2 — см. arecord -l

# ------------------ Энкодер ------------------
def detect_encoder():
    """Определяет доступный h264-энкодер на Jetson"""
    try:
        result = subprocess.run(
            ["gst-inspect-1.0", "nvv4l2h264enc"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        if result.returncode == 0:
            logger.info("Используется аппаратный энкодер: nvv4l2h264enc")
            return "nvv4l2h264enc"
    except FileNotFoundError:
        pass

    logger.warning("Аппаратный энкодер недоступен → используем x264enc (CPU)")
    return "x264enc tune=zerolatency bitrate=5000 speed-preset=superfast"

ENCODER = detect_encoder()

# ------------------ Запись ------------------
def record_camera(name: str, sensor_id: int, audio_src: str, duration: int = 60):
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = os.path.join(RECORD_DIR, f"{name}_{timestamp}.mp4")

    cmd = [
        "gst-launch-1.0", "-e",
        "nvarguscamerasrc", f"sensor-id={sensor_id}", "!",
        "video/x-raw(memory:NVMM),width=1280,height=720,framerate=30/1", "!",
        "nvvidconv", "!", "videoconvert", "!",
        *ENCODER.split(), "!", "queue", "!", "mux.",
        "alsasrc", f"device={audio_src}", "!", "audioconvert", "!", "voaacenc", "!", "queue", "!", "mux.",
        "mp4mux", "name=mux", "!", f"filesink location={filename}"
    ]

    logger.info(f"🎥 Запись {name} → {filename}")

    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=duration+10)
        logger.info(f"✅ {name}: запись завершена → {filename}")
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Ошибка записи {name}: {e}")
    except subprocess.TimeoutExpired:
        logger.warning(f"⚠️ {name}: запись превысила лимит {duration} сек")

# ------------------ Main ------------------
if __name__ == "__main__":
    threads = []

    t1 = threading.Thread(target=record_camera, args=("front", FRONT_CAM, FRONT_AUDIO))
    t2 = threading.Thread(target=record_camera, args=("inner", INNER_CAM, INNER_AUDIO))

    t1.start()
    t2.start()

    threads.extend([t1, t2])

    for t in threads:
        t.join()

    logger.info("🎬 Запись всех камер завершена.")

#sudo modprobe v4l2loopback devices=2 video_nr=10,11 card_label="VirtualCam1,VirtualCam2"

#ffmpeg   -thread_queue_size 512 -f v4l2 -input_format mjpeg -framerate 30 -video_size 1280x720 -i /dev/video2   -thread_queue_size 512 -f alsa -i hw:0,0     -map 0:v -pix_fmt yuv420p -f v4l2 /dev/video10     -map 0:v -map 1:a   -c:v libx264 -preset veryfast -crf 28   -c:a aac -b:a 128k   -f segment -strftime 1 -segment_time 60 -reset_timestamps 1 out_%Y-%m-%d_%H-%M-%S.mp4
#ffmpeg   -thread_queue_size 512 -f v4l2 -input_format mjpeg -framerate 30 -video_size 1280x720 -i /dev/video6   -thread_queue_size 512 -f alsa -i hw:1,0     -map 0:v -pix_fmt yuv420p -f v4l2 /dev/video11     -map 0:v -map 1:a   -c:v libx264 -preset veryfast -crf 28   -c:a aac -b:a 128k   -f segment -strftime 1 -segment_time 60 -reset_timestamps 1 out_%Y-%m-%d_%H-%M-%S.mp4

