from database import get_connection, db_pool
from embedding_service import generate_embedding


def search_knowledge_base(query, limit=5):

    
    print("Generating knowledge search embedding...")

    query_embedding = generate_embedding(query)

    print("Embedding generated.")

    conn = get_connection()
    cursor = conn.cursor()

    try:

        cursor.execute("""
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
            limit
        ))

        rows = cursor.fetchall()

        results = []

        for row in rows:

            results.append({
                "title": row[0],
                "section": row[1],
                "category": row[2],
                "content": row[3],
                "url": row[4],
                "source": row[5],
                "source_id": row[6],
                "similarity": row[7]
            })

        return results

    finally:

        cursor.close()
        db_pool.putconn(conn)