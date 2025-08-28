import os
import time
import requests
import shutil
import subprocess
import json
import logging
import tempfile
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ================= CONFIG =================
SERVER_URL = f'http://{os.getenv("DOMEN")}/check_models'
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "models")
OLD_MODELS_DIR = os.path.join(BASE_DIR, "old_models")
VERSION_FILE = os.path.join(MODELS_DIR, "version.json")
CHECK_INTERVAL = 300  # 5 min
TIMEOUT = 20  # sec for requests
# ==========================================

# Ensure old_models dir exists
os.makedirs(OLD_MODELS_DIR, exist_ok=True)

# Logging config
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("model_updater")


def get_local_versions():
    if not os.path.exists(VERSION_FILE):
        return {"versions": {}}
    try:
        with open(VERSION_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to read {VERSION_FILE}: {e}")
        return {"versions": {}}


def save_versions(data):
    try:
        with open(VERSION_FILE, "w") as f:
            json.dump({"versions": data}, f, indent=4)
        logger.info("Updated version.json saved.")
    except Exception as e:
        logger.error(f"Failed to save version.json: {e}")


def download_file(url: str, dest: str, timeout: int = TIMEOUT) -> str:
    """
    Скачивает файл по URL во временный файл и потом атомарно перемещает в dest.
    Возвращает путь к скачанному файлу.
    """
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".part", dir=os.path.dirname(dest))
    os.close(tmp_fd)  # закроем, будем писать сами

    try:
        logger.info(f"Downloading from {url} → {dest}")

        with requests.get(url, stream=True, timeout=timeout) as r:
            r.raise_for_status()
            total_size = int(r.headers.get("Content-Length", 0))
            written = 0

            with open(tmp_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        written += len(chunk)

        # Проверки после скачивания
        if total_size and written != total_size:
            raise ValueError(
                f"Incomplete download: expected {total_size} bytes, got {written}"
            )
        if written == 0:
            raise ValueError(f"Downloaded file {url} is empty")

        # Атомарно заменяем
        shutil.move(tmp_path, dest)
        logger.info(f"Download complete: {dest} ({written} bytes)")
        return dest

    except Exception as e:
        logger.error(f"Failed to download {url}: {e}")
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise

# def backup_old_models():
#     timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
#     backup_dir = os.path.join(OLD_MODELS_DIR, timestamp)
#     os.makedirs(backup_dir, exist_ok=True)

#     for fname in os.listdir(MODELS_DIR):
#         fpath = os.path.join(MODELS_DIR, fname)
#         if os.path.isfile(fpath) and fname.endswith(".pt"):
#             shutil.move(fpath, backup_dir)
#             logger.info(f"Moved old model {fname} → {backup_dir}")

#     return backup_dir

def backup_old_models(models_to_update: dict, MODELS_DIR: str, OLD_MODELS_DIR: str) -> str:

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(OLD_MODELS_DIR, timestamp)
    os.makedirs(backup_dir, exist_ok=True)

    for model_name, url in models_to_update.items():
        new_fname = os.path.basename(url)

        # ищем все файлы в MODELS_DIR, которые начинаются с префикса (front_, inner_, lane_)
        prefix = model_name.split("_")[0]  # "front", "inner", "lane"
        for fname in os.listdir(MODELS_DIR):
            if fname.startswith(prefix) and fname.endswith(".pt"):
                src = os.path.join(MODELS_DIR, fname)
                dst = os.path.join(backup_dir, fname)
                try:
                    shutil.move(src, dst)
                    logger.info(f"Moved old {model_name}: {src} → {dst}")
                except Exception as e:
                    logger.error(f"Failed to move {src}: {e}")

    return backup_dir


def restart_app():
    try:
        subprocess.run(["sudo", "systemctl", "restart", "inner_cam.service"], check=True)
        subprocess.run(["sudo", "systemctl", "restart", "front_cam.service"], check=True)
        logger.info("Successfully restarted inner_cam and front_cam services.")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to restart services: {e}")


def main():
    while True:
        try:
            local_versions = get_local_versions()
            logger.info("Checking for updates...")

            resp = requests.post(SERVER_URL, json=local_versions, timeout=TIMEOUT)
            resp.raise_for_status()
            data = resp.json()

            if data.get("update_required"):
                logger.info("New models found → updating...")

                # Backup old models
                backup_old_models(data["models"], MODELS_DIR, OLD_MODELS_DIR)

                # Download new models
                for model_name, url in data["models"].items():
                    dest = os.path.join(MODELS_DIR, os.path.basename(url))
                    download_file(url, dest)

                # Update version.json
                save_versions(data["versions"])

                # Restart application
                restart_app()
            else:
                logger.info("Models are up-to-date.")

        except Exception as e:
            logger.error(f"Update check failed: {e}")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
