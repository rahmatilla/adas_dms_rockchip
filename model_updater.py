import os
import time
import requests
import shutil
import subprocess
import json
import logging
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
            json.dump(data, f, indent=2)
        logger.info("Updated version.json saved.")
    except Exception as e:
        logger.error(f"Failed to save version.json: {e}")


def download_file(url, dest):
    try:
        r = requests.get(url, stream=True, timeout=TIMEOUT)
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        if os.path.getsize(dest) == 0:
            raise ValueError(f"Downloaded file {dest} is empty")
        logger.info(f"Downloaded {dest}")
    except Exception as e:
        logger.error(f"Error downloading {url}: {e}")
        raise


def backup_old_models():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(OLD_MODELS_DIR, timestamp)
    os.makedirs(backup_dir, exist_ok=True)

    for fname in os.listdir(MODELS_DIR):
        fpath = os.path.join(MODELS_DIR, fname)
        if os.path.isfile(fpath) and fname.endswith(".pt"):
            shutil.move(fpath, backup_dir)
            logger.info(f"Moved old model {fname} → {backup_dir}")

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
                backup_old_models()

                # Download new models
                for model_name, url in data["models"].items():
                    dest = os.path.join(MODELS_DIR, model_name)
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
