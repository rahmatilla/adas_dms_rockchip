import cv2
import websockets
import asyncio, os
from dotenv import load_dotenv

load_dotenv()

STREAM_URL = os.getenv("STREAM_URL")

async def send_video():
    cap = cv2.VideoCapture(0)  # локальная камера
    async with websockets.connect(STREAM_URL, max_size=2**24) as ws:  # увеличили лимит
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            # уменьшаем размер кадра
            frame = cv2.resize(frame, (640, 480))

            # Кодируем JPEG
            _, buffer = cv2.imencode(".jpg", frame)

            # Отправляем
            await ws.send(buffer.tobytes())

asyncio.run(send_video())
