# shared_buffers.py
from multiprocessing import shared_memory
import numpy as np
import time

# ================= CONFIG ==================
FRAME_RATE = 30
BUFFER_SECONDS = 60
AUDIO_SR = 44100

# Frame shape (height, width, channels)
FRAME_SHAPE = (480, 640, 3)
FRAME_DTYPE = np.uint8       # video framelar uchun
AUDIO_DTYPE = np.float32     # audio sample-lar uchun

NUM_FRAMES = FRAME_RATE * BUFFER_SECONDS
NUM_SAMPLES = AUDIO_SR * BUFFER_SECONDS

# ================= SIZE CALCULATIONS ==================
inner_size = int(np.prod(FRAME_SHAPE)) * NUM_FRAMES * np.dtype(FRAME_DTYPE).itemsize
front_size = int(np.prod(FRAME_SHAPE)) * NUM_FRAMES * np.dtype(FRAME_DTYPE).itemsize
audio_size = NUM_SAMPLES * np.dtype(AUDIO_DTYPE).itemsize

# ================= INIT SHARED MEMORY ==================
shm_inner = shared_memory.SharedMemory(create=True, size=inner_size, name="shm_inner")
shm_front = shared_memory.SharedMemory(create=True, size=front_size, name="shm_front")
shm_audio = shared_memory.SharedMemory(create=True, size=audio_size, name="shm_audio")

print("=== Shared buffers created ===")
print(f"Inner: {shm_inner.name} (size={inner_size/1024/1024:.2f} MB)")
print(f"Front: {shm_front.name} (size={front_size/1024/1024:.2f} MB)")
print(f"Audio: {shm_audio.name} (size={audio_size/1024/1024:.2f} MB)")
print("Attach qilish uchun shu nomlardan foydalaning.")

try:
    while True:
        time.sleep(1)  # Processni tirik ushlab turish
except KeyboardInterrupt:
    print("Shutting down shared buffers...")
    shm_inner.close(); shm_inner.unlink()
    shm_front.close(); shm_front.unlink()
    shm_audio.close(); shm_audio.unlink()
