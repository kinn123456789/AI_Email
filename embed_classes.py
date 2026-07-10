import json

from database import get_connection
from embedding_service import generate_embedding


def insert_chunk(
    cursor,
    class_id,
    title,
    subject,
    section,
    content,
    url=""
):
    """Create one semantic chunk and store it."""

    if not content:
        return

    if isinstance(content, (list, tuple)):
        if len(content) == 0:
            return
        content = "\n".join(f"• {item}" for item in content)

    elif isinstance(content, dict):
        if len(content) == 0:
            return
        content = json.dumps(content, indent=2)

    content = str(content).strip()

    if not content:
        return

    chunk = f"""
Class: {title}

Subject: {subject}

Section: {section}

Content:
{content}
""".strip()

    embedding = generate_embedding(chunk)

    cursor.execute(
        """
        INSERT INTO knowledge_base
        (
            article_title,
            section_title,
            category,
            content,
            url,
            embedding,
            source,
            source_id
        )
        VALUES
        (
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            'class',
            %s
        )
        """,
        (
            title,
            section,
            subject,
            chunk,
            url,
            embedding,
            str(class_id)
        )
    )


conn = get_connection()
cursor = conn.cursor()

try:

    cursor.execute("""
    SELECT
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
        parental_guidance
    FROM classes
    """)

    rows = cursor.fetchall()

    print(f"\nFound {len(rows)} classes.\n")

    for row in rows:

        (
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
            parental_guidance
        ) = row

        print(f"Embedding: {title}")

        try:

            # Delete previous chunks for this class
            cursor.execute(
                """
                DELETE
                FROM knowledge_base
                WHERE source = 'class'
                AND source_id = %s
                """,
                (str(class_id),)
            )

            class_url = (
                f"https://www.coralacademy.com/class/"
                f"{url_slug}-{class_id}"
            )

            insert_chunk(
                cursor,
                class_id,
                title,
                subject,
                "Parent Summary",
                summary_parent,
                class_url
            )

            insert_chunk(
                cursor,
                class_id,
                title,
                subject,
                "Learner Summary",
                summary_learner,
                class_url
            )

            insert_chunk(
                cursor,
                class_id,
                title,
                subject,
                "Description",
                description,
                class_url
            )

            insert_chunk(
                cursor,
                class_id,
                title,
                subject,
                "Learning Goals",
                learning_goals,
                class_url
            )

            insert_chunk(
                cursor,
                class_id,
                title,
                subject,
                "Prerequisites",
                prerequisites,
                class_url
            )

            insert_chunk(
                cursor,
                class_id,
                title,
                subject,
                "Resources",
                resources,
                class_url
            )

            insert_chunk(
                cursor,
                class_id,
                title,
                subject,
                "Parental Guidance",
                parental_guidance,
                class_url
            )

            conn.commit()

            print("✓ Done")

        except Exception as e:

            conn.rollback()

            print(f"✗ Failed: {title}")
            print(e)

finally:

    cursor.close()
    conn.close()

print("\n✅ Class Knowledge Base embedding complete.")