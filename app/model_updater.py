# import os
# import time
# import requests
# import shutil
# import subprocess
# import json
# import logging
# import tempfile
# import zipfile
# from datetime import datetime
# from dotenv import load_dotenv

# load_dotenv()

# # ================= CONFIG =================
# SERVER_URL = f'http://{os.getenv("DOMEN")}/check_models'
# BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# PARENT_DIR = os.path.dirname(BASE_DIR)
# MODELS_DIR = os.path.join(PARENT_DIR, "models")
# OLD_MODELS_DIR = os.path.join(PARENT_DIR, "old_models")
# VERSION_FILE = os.path.join(MODELS_DIR, "version.json")
# CHECK_INTERVAL = 30  # 30 seconds
# TIMEOUT = 20  # sec for requests
# # ==========================================

# # Ensure old_models dir exists
# os.makedirs(OLD_MODELS_DIR, exist_ok=True)

# # Logging config
# logging.basicConfig(
#     level=logging.INFO,
#     format="[%(asctime)s] %(levelname)s: %(message)s",
#     datefmt="%Y-%m-%d %H:%M:%S"
# )
# logger = logging.getLogger("model_updater")


# def get_local_versions():
#     if not os.path.exists(VERSION_FILE):
#         return {"versions": {}}
#     try:
#         with open(VERSION_FILE, "r") as f:
#             return json.load(f)
#     except Exception as e:
#         logger.error(f"Failed to read {VERSION_FILE}: {e}")
#         return {"versions": {}}


# def save_versions(data):
#     try:
#         with open(VERSION_FILE, "w") as f:
#             json.dump({"versions": data}, f, indent=4)
#         logger.info("Updated version.json saved.")
#     except Exception as e:
#         logger.error(f"Failed to save version.json: {e}")


# def download_file(url: str, dest: str, timeout: int = TIMEOUT) -> str:
#     """
#     Скачивает файл по URL во временный файл и потом атомарно перемещает в dest.
#     Возвращает путь к скачанному файлу.
#     """
#     tmp_fd, tmp_path = tempfile.mkstemp(suffix=".part", dir=os.path.dirname(dest))
#     os.close(tmp_fd)  # закроем, будем писать сами

#     try:
#         logger.info(f"Downloading from {url} → {dest}")

#         with requests.get(url, stream=True, timeout=timeout) as r:
#             r.raise_for_status()
#             total_size = int(r.headers.get("Content-Length", 0))
#             written = 0

#             with open(tmp_path, "wb") as f:
#                 for chunk in r.iter_content(chunk_size=8192):
#                     if chunk:
#                         f.write(chunk)
#                         written += len(chunk)

#         # Проверки после скачивания
#         if total_size and written != total_size:
#             raise ValueError(
#                 f"Incomplete download: expected {total_size} bytes, got {written}"
#             )
#         if written == 0:
#             raise ValueError(f"Downloaded file {url} is empty")

#         # Атомарно заменяем
#         shutil.move(tmp_path, dest)
#         logger.info(f"Download complete: {dest} ({written} bytes)")
#         return dest

#     except Exception as e:
#         logger.error(f"Failed to download {url}: {e}")
#         if os.path.exists(tmp_path):
#             os.remove(tmp_path)
#         raise

# def backup_old_models(models_to_update: dict, MODELS_DIR: str, OLD_MODELS_DIR: str) -> str:

#     timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
#     backup_dir = os.path.join(OLD_MODELS_DIR, timestamp)
#     os.makedirs(backup_dir, exist_ok=True)

#     for model_name, url in models_to_update.items():
#         new_fname = os.path.basename(url)

#         # ищем все файлы в MODELS_DIR, которые начинаются с префикса (front_, inner_, lane_)
#         prefix = model_name.split("_")[0]  # "front", "inner", "lane"
#         for fname in os.listdir(MODELS_DIR):
#             if fname.startswith(prefix) and fname.endswith(".pt"):
#                 src = os.path.join(MODELS_DIR, fname)
#                 dst = os.path.join(backup_dir, fname)
#                 try:
#                     shutil.move(src, dst)
#                     logger.info(f"Moved old {model_name}: {src} → {dst}")
#                 except Exception as e:
#                     logger.error(f"Failed to move {src}: {e}")

#     return backup_dir

# def backup_and_update_app(app_url: str, dest_dir: str = PARENT_DIR):
#     """
#     Скачивает ZIP с новой версией приложения, бэкапит текущую папку app/
#     и обновляет её.
#     """
#     tmp_zip = os.path.join(tempfile.gettempdir(), os.path.basename(app_url))
#     backup_root = os.path.join(dest_dir, "old_app")
#     os.makedirs(backup_root, exist_ok=True)
#     backup_dir = os.path.join(backup_root, datetime.now().strftime("%Y%m%d_%H%M%S"))
#     os.makedirs(backup_dir, exist_ok=True)

#     # Скачиваем архив во временный файл
#     download_file(app_url, tmp_zip)

#     # Бэкапим текущую папку app/
#     app_path = os.path.join(dest_dir, "app")
#     if os.path.exists(app_path):
#         try:
#             shutil.copytree(app_path, os.path.join(backup_dir, "app"))
#             logger.info(f"Backed up app/ → {backup_dir}")
#         except Exception as e:
#             logger.error(f"Failed to backup app/: {e}")

#     # Распаковываем архив в dest_dir
#     try:
#         with zipfile.ZipFile(tmp_zip, "r") as zip_ref:
#             zip_ref.extractall(dest_dir)
#         logger.info(f"Application updated from {app_url}")
#     except Exception as e:
#         logger.error(f"Failed to extract app archive {tmp_zip}: {e}")
#         raise
#     finally:
#         if os.path.exists(tmp_zip):
#             os.remove(tmp_zip)

# def restart_app():
#     try:
#         subprocess.run(["sudo", "systemctl", "restart", "inner_cam.service"], check=True)
#         subprocess.run(["sudo", "systemctl", "restart", "front_cam.service"], check=True)
#         logger.info("Successfully restarted inner_cam and front_cam services.")
#     except subprocess.CalledProcessError as e:
#         logger.error(f"Failed to restart services: {e}")


# def main():
#     while True:
#         try:
#             local_versions = get_local_versions()
#             logger.info("Checking for updates...")

#             resp = requests.post(SERVER_URL, json=local_versions, timeout=TIMEOUT)
#             resp.raise_for_status()
#             data = resp.json()

#             if data.get("update_required"):
#                 # Backup old models
#                 backup_old_models(data["models"], MODELS_DIR, OLD_MODELS_DIR)

#                 # Download new models
#                 for model_name, url in data["models"].items():
#                     if model_name == "app":
#                         logger.info("Updating application package...")
#                         backup_and_update_app(data["models"]["app"])
#                     else:
#                         logger.info("New model found → updating...")
#                         dest = os.path.join(MODELS_DIR, os.path.basename(url))
#                         download_file(url, dest)

#                 # Update version.json
#                 save_versions(data["versions"])

#                 # Restart application
#                 restart_app()
#             else:
#                 logger.info("Models are up-to-date.")

#         except Exception as e:
#             logger.error(f"Update check failed: {e}")

#         time.sleep(CHECK_INTERVAL)


# if __name__ == "__main__":
#     main()


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
    Скачивает все новые модели во временную папку и проверяет MD5.
    Если ошибка — кидает исключение и старые модели остаются на месте.
    """
    os.makedirs(tmp_dir, exist_ok=True)
    for model_name, info in models_info.items():
        if model_name == "app":
            continue  # приложение обрабатываем отдельно
        url = info["url"]
        expected_md5 = info.get("md5")
        dest = os.path.join(tmp_dir, os.path.basename(url))
        download_file(url, dest, expected_md5)
    logger.info("All models downloaded and verified in tmp dir")


def apply_new_models(tmp_dir: str, models_dir: str, old_models_dir: str):
    """
    Переносит старые модели в backup, а новые из tmp_dir кладёт в models_dir.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(old_models_dir, timestamp)
    os.makedirs(backup_dir, exist_ok=True)

    # Переносим старые модели
    for fname in os.listdir(models_dir):
        if fname.endswith(".pt"):
            shutil.move(os.path.join(models_dir, fname), os.path.join(backup_dir, fname))
            logger.info(f"Moved old model {fname} → {backup_dir}")

    # Устанавливаем новые
    for fname in os.listdir(tmp_dir):
        shutil.move(os.path.join(tmp_dir, fname), os.path.join(models_dir, fname))
        logger.info(f"Installed new model {fname}")

    shutil.rmtree(tmp_dir)
    logger.info("Applied new models successfully")


def backup_and_update_app(app_url: str, expected_md5: str, dest_dir: str = PARENT_DIR):
    """
    Скачивает ZIP с новой версией приложения, проверяет MD5,
    бэкапит текущую папку app/ и обновляет её.
    """
    tmp_zip = os.path.join(tempfile.gettempdir(), os.path.basename(app_url))
    backup_root = os.path.join(dest_dir, "old_app")
    os.makedirs(backup_root, exist_ok=True)
    backup_dir = os.path.join(backup_root, datetime.now().strftime("%Y%m%d_%H%M%S"))
    os.makedirs(backup_dir, exist_ok=True)

    # Скачиваем с проверкой MD5
    download_file(app_url, tmp_zip, expected_md5)

    # Бэкапим текущую папку app/
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
                models_info = data["models"]

                # 1. сначала качаем и проверяем во временную папку
                tmp_dir = os.path.join(tempfile.gettempdir(), "new_models")
                if os.path.exists(tmp_dir):
                    shutil.rmtree(tmp_dir)
                download_and_verify_models(models_info, tmp_dir)

                # 2. если всё ок → обновляем приложение/модели
                for model_name, info in models_info.items():
                    if model_name == "app":
                        logger.info("Updating application package...")
                        backup_and_update_app(info["url"], info.get("md5"))
                apply_new_models(tmp_dir, MODELS_DIR, OLD_MODELS_DIR)

                # 3. обновляем version.json
                save_versions(data["versions"])

                # 4. рестартуем сервисы
                restart_app()
            else:
                logger.info("Models are up-to-date.")

        except Exception as e:
            logger.error(f"Update check failed: {e}")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
