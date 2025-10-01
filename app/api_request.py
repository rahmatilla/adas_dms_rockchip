import requests

API_BASE = "http://localhost:8083/api"
TOKEN = "eyJhbGciOiJIUzUxMiJ9.eyJ0cmtpZCI6MTEsInN1YiI6IjQzNTQ2NUdEUzc2N0ZHRkciLCJleHAiOjE3NTkzNzIwMzMsImF1dGgiOltdLCJpYXQiOjE3NTkyODU2MzN9.Lvq5uIHu1BZ6M2-AoUNcJwAC3iaWS0CctWGKqr5R9tfmLWg2deAGBMmGyNpgqG8drqW8CU22fhT6HrugzHV0hQ"

headers = {
    "Authorization": f"Bearer {TOKEN}"
}


def upload_video(file_path, start_time, end_time, format="P720", camera_type="INSIDE"):
    """
    Upload a video file to the server
    """
    url = f"{API_BASE}/video/upload"
    files = {
        "file": open(file_path, "rb")
    }
    data = {
        "startTime": start_time,   # e.g. "2025-09-30T15:30:10.123456Z"
        "endTime": end_time,       # e.g. "2025-09-30T15:39:10.123456Z"
        "format": format,          # allowed values: ["P240", "P480", "P720", "P1080", "K2", "K4"]
        "cameraType": camera_type  # allowed values: ["INSIDE", "OUTSIDE"]
    }
    response = requests.post(url, headers=headers, files=files, data=data)
    return response.json()


def send_driver_event(event_data):
    """
    Send a driver event to the server
    """
    url = f"{API_BASE}/driver-events"
    response = requests.post(url, headers=headers, json=event_data)
    return response.json()


# === Example usage ===

# 1) Upload a video
# resp1 = upload_video("test_video.mp4", "2025-09-30T15:30:10.123456Z", "2025-09-30T15:39:10.123456Z")
# print(resp1)

# 2) Send a driver event
# event_payload = {
#     "globalEventId": "GL-EVENT-74658435",   # required
#     "event": "HARSH_BRAKE",                 # required
#     "status": "NEED_REVIEW",                # required
#     "deviceDateTime": "2025-09-30T15:30:10.123456Z", # required
#     "latitude": 89.003232,                  # required
#     "longitude": 87.099999,                 # required
#     "distance": 12.1,                       # required
#     "state": "AR",                          # required
#     "location": "Arzon State",              # required
#     "direction": "NW",                      # required
#     "fuelLevelPercent": 12,                 # required
#     "defLevelPercent": 12,                  # required
#     "speed": 60,                            # required
#     "truck": {"id": 1},
#     "driver": {"id": 1}
# }
# resp2 = send_driver_event(event_payload)
# print(resp2)
