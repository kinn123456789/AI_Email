from database import get_connection, db_pool
from embedding_service import generate_embedding


def search_knowledge_base(subject, body, limit=5):
    """
    Searches the unified Coral Academy Knowledge Base.

    Sources may include:
    - Help Center
    - Classes
    - Future knowledge sources

    Returns the most relevant unique results.
    """

    query = f"""
Subject:
{subject}

Body:
{body}
""".strip()
    print("USING KNOWLEDGE SEARCH FILE #1")
    print("Generating Knowledge Base query embedding...")

    query_embedding = generate_embedding(query)

    conn = get_connection()
    cursor = conn.cursor()

    try:

        cursor.execute(
            """
            SELECT
                article_title,
                section_title,
                category,
                content,
                url,
                source,
                source_id,
                1 - (embedding <=> %s::vector) AS similarity

            FROM knowledge_base

            WHERE embedding IS NOT NULL

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
        #seen_urls = set()
        seen = set()


        for row in rows:
            print(
                row[0],
                row[1],
                row[7]
            )

    
            similarity = row[7]

            print(
                f"{row[0]} | {row[1]} | similarity={row[7]:.3f}"
            )

          

            url = row[4]

            #if url in seen_urls:
             #   continue

            #seen_urls.add(url)

            key = (
                row[5],   # source
                row[6],   # source_id
                row[1]    # section
            )  # article_title + section_title

            if key in seen:
                continue

            seen.add(key)

            print("USING KNOWLEDGE SEARCH FILE #1")
            results.append(
                {
                    "title": row[0],
                    "section": row[1] or "",
                    "category": row[2] or "",
                    "content": row[3] or "",
                    "url": row[4] or "",
                    "source": row[5] or "",
                    "source_id": row[6] or "",
                    "similarity": similarity,
                }
            )

            if len(results) >= limit:
                break

        return results

    finally:
        cursor.close()
        db_pool.putconn(conn)