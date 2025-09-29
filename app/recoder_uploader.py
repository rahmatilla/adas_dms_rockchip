#!/usr/bin/env python3
"""
Run two ffmpeg capture processes:
 - camera A: /dev/video2  -> virtual /dev/video10 + segments -> recordings/cam0/
 - camera B: /dev/video6  -> virtual /dev/video11 + segments -> recordings/cam1/

Track created mp4 files in SQLite and upload them to SERVER_URL.
"""

import os
import sys
import time
import sqlite3
import threading
import subprocess
import signal
import shutil
from pathlib import Path
from datetime import datetime
import requests

# ----------------- CONFIG -----------------
# Edit these to match your environment
CAM_A_VIDEO = "/dev/video2"
CAM_A_AUDIO = "hw:0,0"
CAM_A_VDEV  = "/dev/video10"
CAM_A_OUTDIR = Path("recordings/cam0")

CAM_B_VIDEO = "/dev/video6"
CAM_B_AUDIO = "hw:1,0"
CAM_B_VDEV  = "/dev/video11"
CAM_B_OUTDIR = Path("recordings/cam1")

# ffmpeg options (tweak CRF / bitrate as desired)
VIDEO_SIZE = "1280x720"
FRAMERATE = 30
CRF = 28
PRESET = "veryfast"
AUDIO_BITRATE = "128k"

# sqlite DB
DB_PATH = Path("video_uploader.db")

# Server upload endpoint (REPLACE with your real server)
SERVER_URL = "https://example.com/upload"  # <-- change this

# how often (sec) to scan directories for new files
SCAN_INTERVAL = 5

# uploader loop sleep between retries for files with failures (exponential backoff base)
UPLOAD_RETRY_BASE = 5

# ensure directories exist
CAM_A_OUTDIR.mkdir(parents=True, exist_ok=True)
CAM_B_OUTDIR.mkdir(parents=True, exist_ok=True)
# ------------------------------------------

# ---------------- DB helpers ----------------
def init_db(conn):
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        path TEXT UNIQUE NOT NULL,
        camera TEXT NOT NULL,
        created_at TEXT NOT NULL,
        size_bytes INTEGER NOT NULL,
        status TEXT NOT NULL, -- pending / uploading / uploaded / error
        retries INTEGER NOT NULL DEFAULT 0,
        last_error TEXT,
        uploaded_at TEXT
    )
    """)
    conn.commit()

def add_file_record(conn, path: str, camera: str):
    stat = os.stat(path)
    created = datetime.utcnow().isoformat()
    cur = conn.cursor()
    try:
        cur.execute("""
        INSERT INTO files (path, camera, created_at, size_bytes, status)
        VALUES (?, ?, ?, ?, 'pending')
        """, (str(path), camera, created, stat.st_size))
        conn.commit()
        print(f"[DB] Added {path} ({camera})")
    except sqlite3.IntegrityError:
        # already exists
        pass

def mark_uploaded(conn, path: str):
    cur = conn.cursor()
    cur.execute("""
    UPDATE files SET status='uploaded', uploaded_at=?, last_error=NULL WHERE path=?
    """, (datetime.utcnow().isoformat(), str(path)))
    conn.commit()

def mark_error(conn, path: str, errmsg: str):
    cur = conn.cursor()
    cur.execute("""
    UPDATE files SET status='error', retries=retries+1, last_error=?, uploaded_at=NULL WHERE path=?
    """, (errmsg, str(path)))
    conn.commit()

def mark_uploading(conn, path: str):
    cur = conn.cursor()
    cur.execute("""
    UPDATE files SET status='uploading' WHERE path=? AND status='pending'
    """, (str(path),))
    conn.commit()
    return cur.rowcount > 0

# ---------------- ffmpeg process helpers ----------------

def ensure_v4l2loopback(devices=("10","11")):
    """Try to load v4l2loopback with given video_nr list if not present."""
    # check lsmod
    try:
        out = subprocess.check_output(["lsmod"]).decode()
        if "v4l2loopback" in out:
            print("[SYS] v4l2loopback already loaded")
            return True
    except Exception:
        pass

    video_nr = ",".join(devices)
    labels = ",".join([f"VirtualCam{n}" for n in devices])
    cmd = ["sudo", "modprobe", "v4l2loopback", f"devices={len(devices)}", f"video_nr={video_nr}", f"card_label={labels}", "exclusive_caps=1"]
    print("[SYS] Loading v4l2loopback:", " ".join(cmd))
    try:
        subprocess.check_call(cmd)
        time.sleep(0.5)
        return True
    except Exception as e:
        print("[ERR] Couldn't load v4l2loopback:", e)
        return False

def build_ffmpeg_cmd(video_dev, audio_dev, vdev, outdir, camera_name):
    """
    Returns a list command to run ffmpeg that:
      - reads from video_dev and audio_dev
      - maps raw video to vdev (pix_fmt yuv420p)
      - writes video+audio to segments in outdir using strftime naming
    """
    outpattern = str(Path(outdir) / "%Y-%m-%d_%H-%M-%S.mp4")
    cmd = [
        "ffmpeg",
        "-thread_queue_size", "512",
        "-f", "v4l2",
        "-input_format", "mjpeg",
        "-framerate", str(FRAMERATE),
        "-video_size", VIDEO_SIZE,
        "-i", video_dev,
        "-thread_queue_size", "512",
        "-f", "alsa",
        "-i", audio_dev,
        # map raw video to virtual camera (no h264)
        "-map", "0:v",
        "-pix_fmt", "yuv420p",
        "-f", "v4l2", vdev,
        # now map video+audio to segment writer
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", PRESET, "-crf", str(CRF),
        "-c:a", "aac", "-b:a", AUDIO_BITRATE,
        "-f", "segment", "-strftime", "1", "-segment_time", "60", "-reset_timestamps", "1",
        outpattern
    ]
    return cmd

# def build_ffmpeg_cmd(video_dev, audio_dev, vdev, outdir, camera_name):
#     """
#     FFmpeg command:
#       - video_dev + audio_dev ni o‘qiydi
#       - virtual camera ga chiqaradi
#       - segmentlarga yozadi (.tmp → .mp4)
#     """
#     outpattern = str(Path(outdir) / "%Y-%m-%d_%H-%M-%S.mp4.tmp")
#     cmd = [
#         "ffmpeg",
#         "-thread_queue_size", "512",
#         "-f", "v4l2",
#         "-input_format", "mjpeg",
#         "-framerate", str(FRAMERATE),
#         "-video_size", VIDEO_SIZE,
#         "-i", video_dev,
#         "-thread_queue_size", "512",
#         "-f", "alsa",
#         "-i", audio_dev,
#         # map raw video to virtual camera (no h264)
#         "-map", "0:v",
#         "-pix_fmt", "yuv420p",
#         "-f", "v4l2", vdev,
#         # now map video+audio to segment writer
#         "-map", "0:v", "-map", "1:a",
#         "-c:v", "libx264", "-preset", PRESET, "-crf", str(CRF),
#         "-c:a", "aac", "-b:a", AUDIO_BITRATE,
#         "-f", "mp4", "segment", "-strftime", "1", "-segment_time", "60", "-reset_timestamps", "1",
#         outpattern
#     ]
#     return cmd


# ---------------- file watcher ----------------

def watch_dirs_and_register(conn, dirs_cameras):
    """Periodically scan directories for new mp4 files and insert into DB."""
    seen = set()
    while True:
        for d, cam in dirs_cameras:
            for path in sorted(Path(d).glob("*.mp4")):
                if str(path) not in seen:
                    # only register finished files (size non-zero and mtime older than 1s)
                    try:
                        st = path.stat()
                        if st.st_size > 100 and (time.time() - st.st_mtime) > 5:
                            add_file_record(conn, str(path), cam)
                            seen.add(str(path))
                    except FileNotFoundError:
                        continue
        time.sleep(SCAN_INTERVAL)

# def watch_dirs_and_register(conn, dirs_cameras):
#     """Yangi tugagan .mp4 fayllarni DBga qo‘shadi."""
#     seen = set()
#     while True:
#         for d, cam in dirs_cameras:
#             # faqat tugagan fayllarni ko‘rish
#             for path in sorted(Path(d).glob("*.mp4.tmp")):
#                 final_path = str(path).replace(".mp4.tmp", ".mp4")
#                 try:
#                     st = path.stat()
#                     # faqat to‘liq yozib bo‘lingan (mtime 2 sekunddan eski)
#                     if st.st_size > 0 and (time.time() - st.st_mtime) > 2:
#                         # rename -> .mp4
#                         new_path = Path(final_path)
#                         path.rename(new_path)
#                         add_file_record(conn, str(new_path), cam)
#                         seen.add(str(new_path))
#                 except FileNotFoundError:
#                     continue
#         time.sleep(SCAN_INTERVAL)

# ---------------- uploader ----------------

def upload_file(session, path):
    """Upload one file. Return True if success, False otherwise, and error message."""
    fname = Path(path).name
    url = SERVER_URL
    try:
        with open(path, "rb") as f:
            files = {"file": (fname, f, "video/mp4")}
            # adjust to your server's requirements (auth headers, extra fields)
            resp = session.post(url, files=files, timeout=30)
            if resp.status_code == 200:
                return True, None
            else:
                return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return False, str(e)

# def uploader_loop(conn, stop_event):
#     session = requests.Session()
#     backoff = UPLOAD_RETRY_BASE
#     while not stop_event.is_set():
#         cur = conn.cursor()
#         cur.execute("SELECT path, retries FROM files WHERE status IN ('pending','error') ORDER BY created_at")
#         rows = cur.fetchall()
#         if not rows:
#             time.sleep(2)
#             continue
#         for path, retries in rows:
#             if stop_event.is_set():
#                 break
#             # set uploading only if currently pending (avoid races)
#             mark_uploading(conn, path)
#             success, err = upload_file(session, path)
#             if success:
#                 mark_uploaded(conn, path)
#                 print(f"[UPLOAD] Sent {path}")
#                 backoff = UPLOAD_RETRY_BASE
#             else:
#                 mark_error(conn, path, err)
#                 print(f"[UPLOAD] Failed {path}: {err}")
#                 # exponential backoff on global loop
#                 time.sleep(min(backoff, 300))
#                 backoff *= 2
#         # small sleep to avoid busy loop
#         time.sleep(1)

def uploader_loop(conn, stop_event):
    """Doimiy cheksiz upload retry loop."""
    session = requests.Session()
    while not stop_event.is_set():
        cur = conn.cursor()
        cur.execute("SELECT path FROM files WHERE status='pending' ORDER BY created_at")
        rows = cur.fetchall()
        if not rows:
            time.sleep(3)
            continue
        for (path,) in rows:
            if stop_event.is_set():
                break
            # upload qilamiz
            success, err = upload_file(session, path)
            if success:
                mark_uploaded(conn, path)
                print(f"[UPLOAD] Sent {path}")
            else:
                # status 'pending' qoladi → keyingi loopda qayta urinadi
                print(f"[UPLOAD] Failed {path}: {err}")
                time.sleep(10)  # keyingi urinish oldidan kutish


# ---------------- main process management ----------------

def start_ffmpeg_process(cmd, name):
    print(f"[FFMPEG] Starting {name}: {' '.join(cmd[:6])} ...")
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
    return p

def stream_process_logger(proc, name, stop_event):
    """Read stderr of ffmpeg and print lines (non-blocking)."""
    try:
        while not stop_event.is_set():
            line = proc.stderr.readline()
            if not line:
                if proc.poll() is not None:
                    break
                time.sleep(0.1)
                continue
            print(f"[{name}] {line.rstrip()}")
    except Exception:
        pass

def main():
    # Ensure DB
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    init_db(conn)

    # Ensure v4l2loopback present
    if not ensure_v4l2loopback(devices=("10","11")):
        print("[FATAL] v4l2loopback not present. Please install v4l2loopback-dkms and try again.")
        sys.exit(1)

    # Build ffmpeg commands
    cmd_a = build_ffmpeg_cmd(CAM_A_VIDEO, CAM_A_AUDIO, CAM_A_VDEV, CAM_A_OUTDIR, "cam0")
    cmd_b = build_ffmpeg_cmd(CAM_B_VIDEO, CAM_B_AUDIO, CAM_B_VDEV, CAM_B_OUTDIR, "cam1")

    # Start ffmpeg processes
    proc_a = start_ffmpeg_process(cmd_a, "cam0")
    proc_b = start_ffmpeg_process(cmd_b, "cam1")

    stop_event = threading.Event()
    # start logger threads
    t_log_a = threading.Thread(target=stream_process_logger, args=(proc_a, "cam0", stop_event), daemon=True)
    t_log_b = threading.Thread(target=stream_process_logger, args=(proc_b, "cam1", stop_event), daemon=True)
    t_log_a.start(); t_log_b.start()

    # start directory watcher thread
    watcher = threading.Thread(target=watch_dirs_and_register, args=(conn, [(CAM_A_OUTDIR, "cam0"), (CAM_B_OUTDIR, "cam1")]), daemon=True)
    watcher.start()

    # start uploader thread
    uploader_stop = threading.Event()
    uploader = threading.Thread(target=uploader_loop, args=(conn, uploader_stop), daemon=True)
    uploader.start()

    def handle_sigint(sig, frame):
        print("[MAIN] Shutdown signal received")
        stop_event.set()
        uploader_stop.set()
        # terminate ffmpeg procs
        for p in (proc_a, proc_b):
            if p and p.poll() is None:
                print("[MAIN] Terminating ffmpeg pid", p.pid)
                p.terminate()
        # give processes a bit to exit
        time.sleep(2)
        for p in (proc_a, proc_b):
            if p and p.poll() is None:
                print("[MAIN] Killing ffmpeg pid", p.pid)
                p.kill()
        conn.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_sigint)
    signal.signal(signal.SIGTERM, handle_sigint)

    # main loop - just wait
    print("[MAIN] Running. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
            # check ffmpeg processes health
            for p, name in ((proc_a, "cam0"), (proc_b, "cam1")):
                if p and p.poll() is not None:
                    print(f"[MAIN] {name} ffmpeg exited with code {p.returncode}. Exiting.")
                    handle_sigint(None, None)
    finally:
        conn.close()

if __name__ == "__main__":
    main()
