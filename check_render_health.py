"""Checks Render service health after a deploy: latest deploy status and any
OOM kills since a given time. Run with no args to check since the last
deploy, or pass an ISO timestamp to check since then.

Usage:
    python3 check_render_health.py
    python3 check_render_health.py 2026-07-30T18:00:00Z
"""

import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv()

RENDER_API_KEY = os.getenv("RENDER_API_KEY")
SERVICE_ID = "srv-d8spv71kh4rs73c4f4r0"  # AI_Email-2
BASE_URL = "https://api.render.com/v1"

headers = {"Authorization": f"Bearer {RENDER_API_KEY}"}


def get_latest_deploy():
    resp = requests.get(
        f"{BASE_URL}/services/{SERVICE_ID}/deploys",
        headers=headers,
        params={"limit": 1},
    )
    resp.raise_for_status()
    return resp.json()[0]["deploy"]


def get_events(limit=50):
    resp = requests.get(
        f"{BASE_URL}/services/{SERVICE_ID}/events",
        headers=headers,
        params={"limit": limit},
    )
    resp.raise_for_status()
    return [e["event"] for e in resp.json()]


def main():
    deploy = get_latest_deploy()
    print(f"Latest deploy: {deploy['status']} — {deploy['commit']['message'].splitlines()[0]}")
    print(f"  finished at: {deploy['finishedAt']}")

    since = sys.argv[1] if len(sys.argv) > 1 else deploy["finishedAt"]
    print(f"\nChecking events since {since}...\n")

    events = get_events()
    events_since = [e for e in events if e["timestamp"] >= since]

    oom_kills = [e for e in events_since if e["type"] == "server_failed"]
    restarts = [e for e in events_since if e["type"] == "server_available"]

    if not oom_kills:
        print(f"No OOM kills since {since}. ({len(restarts)} clean restart event(s) in that window.)")
    else:
        print(f"{len(oom_kills)} OOM kill(s) since {since}:")
        for e in oom_kills:
            print(f"  {e['timestamp']} — instance {e['details'].get('instanceID')}")

    print("\nAll events in window:")
    for e in sorted(events_since, key=lambda e: e["timestamp"]):
        print(f"  {e['timestamp']} — {e['type']}")


if __name__ == "__main__":
    main()
