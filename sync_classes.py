import json
import requests

from database import get_connection

BROWSE_URL = "https://api.coralacademy.com/browse-classes"
DETAIL_URL = "https://api.coralacademy.com/get-class"


conn = get_connection()
cursor = conn.cursor()

print("Fetching class list...")

browse = requests.get(BROWSE_URL).json()

classes = browse["response"]["classes"]

print(f"Found {len(classes)} classes.\n")


for cls in classes:

    slug = f"{cls['url_slug']}-{cls['id']}"

    print(f"Syncing {cls['title']}")

    response = requests.post(
        DETAIL_URL,
        json={"url_slug": slug}
    ).json()

    c = response["response"]

    cursor.execute(
        """
        INSERT INTO classes (
            class_id,
            title,
            url_slug,
            subject,
            summary_parent,
            summary_learner,
            description,
            learning_goals,
            prerequisites,
            resources,
            parental_guidance,
            age_min,
            age_max,
            grade_min,
            grade_max,
            pricing,
            image_url,
            video_url,
            raw_json,
            updated_at
        )
        VALUES (
            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
            %s,%s,%s,%s,%s,%s,%s,%s,%s,NOW()
        )

        ON CONFLICT (class_id)

        DO UPDATE SET

            title = EXCLUDED.title,
            url_slug = EXCLUDED.url_slug,
            subject = EXCLUDED.subject,
            summary_parent = EXCLUDED.summary_parent,
            summary_learner = EXCLUDED.summary_learner,
            description = EXCLUDED.description,
            learning_goals = EXCLUDED.learning_goals,
            prerequisites = EXCLUDED.prerequisites,
            resources = EXCLUDED.resources,
            parental_guidance = EXCLUDED.parental_guidance,
            age_min = EXCLUDED.age_min,
            age_max = EXCLUDED.age_max,
            grade_min = EXCLUDED.grade_min,
            grade_max = EXCLUDED.grade_max,
            pricing = EXCLUDED.pricing,
            image_url = EXCLUDED.image_url,
            video_url = EXCLUDED.video_url,
            raw_json = EXCLUDED.raw_json,
            updated_at = NOW()
        """,
        (
            c["id"],
            c["title"],
            c["url_slug"],
            c.get("subject"),
            c.get("summary", {}).get("parent"),
            c.get("summary", {}).get("learner"),
            c.get("description"),
            json.dumps(c.get("learning_goals", [])),
            json.dumps(c.get("prerequisites", [])),
            json.dumps(c.get("resources", [])),
            c.get("parental_guidance"),
            c.get("age", {}).get("min"),
            c.get("age", {}).get("max"),
            c.get("us_grade_level", {}).get("min"),
            c.get("us_grade_level", {}).get("max"),
            json.dumps(c.get("pricing", {})),
            c.get("image", {}).get("url"),
            c.get("video", {}).get("url"),
            json.dumps(c)
        )
    )

conn.commit()

cursor.close()
conn.close()

print("\n✅ Classes synced successfully.")

