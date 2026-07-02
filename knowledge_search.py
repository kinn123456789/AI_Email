import os

from dotenv import load_dotenv
from openai import OpenAI

from database import get_connection


load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1"
)


def search_knowledge_base(subject, body, limit=5):

    print("Generating knowledge query embedding...")

    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=f"Subject: {subject}\n\nBody:\n{body}"
    )

    query_embedding = response.data[0].embedding

    conn = get_connection()
    cursor = conn.cursor()

    try:

        cursor.execute(
            """
            SELECT
                id,
                article_title,
                category,
                content,
                url,
                embedding <=> %s::vector AS distance
            FROM knowledge_base
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (
                query_embedding,
                query_embedding,
                limit * 3
            )
        )

        rows = cursor.fetchall()

        results = []
        seen_urls = set()

        for row in rows:

            url = row[4]

            if url in seen_urls:
                continue

            seen_urls.add(url)

            results.append({
                "id": row[0],
                "title": row[1],
                "category": row[2],
                "content": row[3],
                "url": url,
                "distance": row[5]
            })

            if len(results) == limit:
                break

        return results

        
    finally:

        cursor.close()
        conn.close()