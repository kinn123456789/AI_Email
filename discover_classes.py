import requests
import json

browse = requests.get(
    "https://api.coralacademy.com/browse-classes"
).json()

cls = browse["response"]["classes"][1]

slug = f"{cls['url_slug']}-{cls['id']}"

print(slug)

response = requests.post(
    "https://api.coralacademy.com/get-class",
    json={
        "url_slug": slug
    }
)

print(response.status_code)

print(json.dumps(response.json(), indent=2)[:5000])