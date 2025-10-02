import queue
import threading
import time
import os
from local_functions_new import save_video, save_audio_from_buffer, upload_to_server, create_driver_event, send_driver_event

# Queue lar
video_queue = queue.Queue()
event_queue = queue.Queue()



def video_worker():
    while True:
        task = video_queue.get()
        if task is None:
            break
        try:
            buffer, output_file, fps, start_time, end_time, format, camera_type, audio_file = task
            try:
                # Agar video fayl allaqachon mavjud bo‘lsa, qayta saqlash shart emas
                if not os.path.exists(output_file):
                    if audio_file:
                        save_audio_from_buffer(audio_file)
                    save_video(buffer, output_file, fps, audio_file)
                    if audio_file and os.path.exists(audio_file):
                        os.remove(audio_file)
                    print(f"[INFO] Video saved: {output_file}")
                else:
                    print(f"[INFO] Video already exists: {output_file}")

                # Endi faqat upload qismida retry bo‘ladi
                upload_to_server(output_file, start_time, end_time, format, camera_type)
                print(f"[INFO] Video uploaded: {output_file}")

            except Exception as e:
                print(f"[ERROR] Upload failed: {e}")
                # Faqat uploadni retry qilish uchun qayta qo‘yiladi
                video_queue.put((None, output_file, fps, start_time, end_time, format, camera_type, None))
                time.sleep(5)

        finally:
            video_queue.task_done()


def event_worker():
    while True:
        task = event_queue.get()
        if task is None:
            break
        try:
            event = task
            try:
                payload = create_driver_event(event=event)
                send_driver_event(payload)
                print(f"[INFO] Event sent: {event}")
            except Exception as e:
                print(f"[ERROR] Event worker failed: {e}")
                event_queue.put(task)  # Retry
                time.sleep(5)
        finally:
            event_queue.task_done()


# Worker threadlarni ishga tushirish
threading.Thread(target=video_worker, daemon=True).start()
threading.Thread(target=event_worker, daemon=True).start()


# Wrapper funksiyalar (oldingi save_upload_in_background va save_event_in_background o‘rniga)
def enqueue_video(buffer, output_file, fps, start_time, end_time, format, camera_type, audio_file=None):
    video_queue.put((buffer, output_file, fps, start_time, end_time, format, camera_type, audio_file))


def enqueue_event(event):
    event_queue.put(event)