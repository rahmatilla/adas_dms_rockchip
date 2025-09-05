import os
import time
import requests
import shutil
import subprocess
import json
import logging
import tempfile
import zipfile
import hashlib
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ================= CONFIG =================
SERVER_URL = f'http://{os.getenv("DOMEN")}/check_models'
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BASE_DIR)
MODELS_DIR = os.path.join(PARENT_DIR, "models")
OLD_MODELS_DIR = os.path.join(PARENT_DIR, "old_models")
VERSION_FILE = os.path.join(MODELS_DIR, "version.json")
CHECK_INTERVAL = 30  # 30 seconds
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


def calculate_md5(file_path: str) -> str:
    """Вычислить MD5 для файла"""
    md5_hash = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            md5_hash.update(chunk)
    return md5_hash.hexdigest()


def download_file(url: str, dest: str, expected_md5: str = None, timeout: int = TIMEOUT) -> str:
    """
    Скачивает файл и проверяет MD5.
    Если хэш не совпадает → удаляет файл и кидает исключение.
    """
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".part", dir=os.path.dirname(dest))
    os.close(tmp_fd)

    try:
        logger.info(f"Downloading from {url} → {dest}")

        with requests.get(url, stream=True, timeout=timeout) as r:
            r.raise_for_status()
            with open(tmp_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

        shutil.move(tmp_path, dest)
        logger.info(f"Download complete: {dest}")

        # Проверка MD5
        if expected_md5:
            actual_md5 = calculate_md5(dest)
            if actual_md5 != expected_md5:
                os.remove(dest)
                raise ValueError(f"MD5 mismatch for {dest}: expected {expected_md5}, got {actual_md5}")
            logger.info(f"MD5 verified for {dest}: {actual_md5}")

        return dest

    except Exception as e:
        logger.error(f"Failed to download {url}: {e}")
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def download_and_verify_models(models_info: dict, tmp_dir: str):
    """
    Скачивает только указанные модели во временную папку и проверяет MD5.
    """
    os.makedirs(tmp_dir, exist_ok=True)
    downloaded = {}

    for model_name, info in models_info.items():
        if model_name == "app":
            continue  # приложение отдельно
        url = info["url"]
        expected_md5 = info.get("md5")
        dest = os.path.join(tmp_dir, os.path.basename(url))
        download_file(url, dest, expected_md5)
        downloaded[model_name] = dest

    logger.info(f"Downloaded {len(downloaded)} models into tmp_dir={tmp_dir}")
    return downloaded


def apply_new_models(downloaded: dict, models_dir: str, old_models_dir: str):
    """
    Бэкапит и заменяет только те модели, которые реально обновляются.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(old_models_dir, timestamp)
    os.makedirs(backup_dir, exist_ok=True)

    for model_name, tmp_path in downloaded.items():
        prefix = model_name.split("_")[0]  # например "front"
        # ищем в models_dir файлы только этого префикса
        for fname in os.listdir(models_dir):
            if fname.startswith(prefix) and fname.endswith(".pt"):
                src = os.path.join(models_dir, fname)
                dst = os.path.join(backup_dir, fname)
                try:
                    shutil.move(src, dst)
                    logger.info(f"Backed up {model_name}: {src} → {dst}")
                except Exception as e:
                    logger.error(f"Failed to backup {src}: {e}")

        # ставим новую модель
        new_fname = os.path.basename(tmp_path)
        shutil.move(tmp_path, os.path.join(models_dir, new_fname))
        logger.info(f"Installed new {model_name}: {new_fname}")

    # удалим tmp_dir, если пустой
    try:
        shutil.rmtree(os.path.dirname(list(downloaded.values())[0]))
    except Exception:
        pass
    logger.info("Applied updated models successfully")


def backup_and_update_app(app_url: str, expected_md5: str, dest_dir: str = PARENT_DIR):
    """
    Бэкапит только папку app/, скачивает новый архив, проверяет MD5 и заменяет.
    """
    tmp_zip = os.path.join(tempfile.gettempdir(), os.path.basename(app_url))
    backup_root = os.path.join(dest_dir, "old_app")
    os.makedirs(backup_root, exist_ok=True)
    backup_dir = os.path.join(backup_root, datetime.now().strftime("%Y%m%d_%H%M%S"))
    os.makedirs(backup_dir, exist_ok=True)

    # Скачиваем с проверкой MD5
    download_file(app_url, tmp_zip, expected_md5)

    # Бэкапим только app/
    app_path = os.path.join(dest_dir, "app")
    if os.path.exists(app_path):
        try:
            shutil.copytree(app_path, os.path.join(backup_dir, "app"))
            logger.info(f"Backed up app/ → {backup_dir}")
        except Exception as e:
            logger.error(f"Failed to backup app/: {e}")

    # Распаковываем архив
    try:
        with zipfile.ZipFile(tmp_zip, "r") as zip_ref:
            zip_ref.extractall(dest_dir)
        logger.info(f"Application updated from {app_url}")
    except Exception as e:
        logger.error(f"Failed to extract app archive {tmp_zip}: {e}")
        raise
    finally:
        if os.path.exists(tmp_zip):
            os.remove(tmp_zip)


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
                logger.info("New updates available...")

                models_info = data["models"]

                # ---- обновляем модели ----
                tmp_dir = tempfile.mkdtemp(prefix="new_models_")
                downloaded = download_and_verify_models(models_info, tmp_dir)

                if downloaded:
                    apply_new_models(downloaded, MODELS_DIR, OLD_MODELS_DIR)

                # ---- обновляем приложение ----
                if "app" in models_info:
                    app_info = models_info["app"]
                    logger.info("Updating application package...")
                    backup_and_update_app(app_info["url"], app_info.get("md5"))

                # ---- сохраняем версии ----
                save_versions(data["versions"])

                # ---- перезапускаем сервисы ----
                restart_app()
            else:
                logger.info("Models and app are up-to-date.")

        except Exception as e:
            logger.error(f"Update check failed: {e}")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
