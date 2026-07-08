# discover_classes.py

import requests

API = "https://api.coralacademy.com/get-landing-classes"

headers = {
    "Origin": "https://www.coralacademy.com",
    "Referer": "https://www.coralacademy.com/",
    "Content-Type": "application/json"
}

response = requests.get(
    API,
    headers=headers,
    timeout=60
)

print(response.status_code)

data = response.json()

print(type(data))
print(data)