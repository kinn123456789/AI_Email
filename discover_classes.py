import os
import json
import time
import requests

BASE = "https://api.coralacademy.com"

headers = {
    "Origin": "https://www.coralacademy.com",
    "Referer": "https://www.coralacademy.com/",
    "Content-Type": "application/json",
    "Accept": "application/json"
}

os.makedirs("class_json", exist_ok=True)

print("="*60)
print("STEP 1 - Fetching all classes")
print("="*60)

r = requests.post(
    f"{BASE}/get-landing-classes",
    headers=headers,
    json={}
)

r.raise_for_status()

classes = r.json()["response"]

print(f"\nFound {len(classes)} classes\n")

all_classes = []

for c in classes:

    cls = {
        "id": c["id"],
        "slug": c["url_slug"],
        "title": c["title"],
        "teacher": c["teacher"]["name"]
    }

    all_classes.append(cls)

    print("--------------------------------")
    print("Title :", cls["title"])
    print("Slug  :", cls["slug"])
    print("ID    :", cls["id"])
    print("Teacher:", cls["teacher"])

with open("classes.json","w") as f:
    json.dump(all_classes,f,indent=4)

print("\nSaved classes.json")

###############################################################

print("\n")
print("="*60)
print("STEP 2 - Downloading every class")
print("="*60)

for cls in all_classes:

    print(f"Downloading {cls['title']}")

    payload = {
        "id": cls["id"]
    }

    try:

        r = requests.post(
            f"{BASE}/get-class",
            headers=headers,
            json=payload,
            timeout=30
        )

        if r.status_code != 200:
            print("Failed", r.status_code)
            continue

        data = r.json()

        filename = f"class_json/{cls['slug']}.json"

        with open(filename,"w") as f:
            json.dump(data,f,indent=4)

        print("Saved", filename)

    except Exception as e:
        print(e)

    time.sleep(0.5)

print("\nFinished.")