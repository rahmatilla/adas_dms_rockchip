import cv2
import websockets
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()
STREAM_URL = os.getenv("STREAM_URL")


async def video_sender(ws):
    """Функция для отправки видео по WebSocket"""
    cap = cv2.VideoCapture(0)
    try:
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

            await asyncio.sleep(0.03)  # ~30 fps
    finally:
        cap.release()


async def client():
    async with websockets.connect(STREAM_URL, max_size=2**24) as ws:
        print("✅ Connected to server")

        sending_task = None

        try:
            async for message in ws:
                if message == "START":
                    if sending_task is None or sending_task.done():
                        print("▶️ START streaming")
                        sending_task = asyncio.create_task(video_sender(ws))
                elif message == "STOP":
                    if sending_task and not sending_task.done():
                        print("⏹ STOP streaming")
                        sending_task.cancel()
                        try:
                            await sending_task
                        except asyncio.CancelledError:
                            pass
                else:
                    print(f"📩 Unknown command: {message}")
        except websockets.ConnectionClosed:
            print("❌ Connection closed")


if __name__ == "__main__":
    asyncio.run(client())
