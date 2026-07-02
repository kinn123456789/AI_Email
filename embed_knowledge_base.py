import os

from dotenv import load_dotenv
from openai import OpenAI

from database import get_connection


load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1"
)


conn = get_connection()
cursor = conn.cursor()

cursor.execute("""
SELECT
    id,
    content
FROM knowledge_base
WHERE embedding IS NULL
ORDER BY id
""")

rows = cursor.fetchall()

print(f"\nFound {len(rows)} chunks to embed.\n")

for row in rows:

    kb_id = row[0]
    content = row[1]

    print(f"Embedding chunk {kb_id}...")

    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=content
    )

    embedding = response.data[0].embedding

    cursor.execute(
        """
        UPDATE knowledge_base
        SET embedding = %s
        WHERE id = %s
        """,
        (
            embedding,
            kb_id
        )
    )

    conn.commit()

print("\nKnowledge Base Embeddings Complete!")

cursor.close()
conn.close()