#knowledge_search.py
from database import get_connection, db_pool
from embedding_service import generate_embedding
from rag_reranker import rerank_knowledge


def search_knowledge_base(subject, body, limit=5, embedding_client=None, rerank=False, audience="parent"):
    """
    Searches the unified Coral Academy Knowledge Base.

    Sources may include:
    - Help Center
    - Classes
    - Future knowledge sources

    Returns the most relevant unique results.

    When rerank=True, over-fetches deduped candidates and runs them through
    an LLM reranking pass (rag_reranker.rerank_knowledge) before truncating
    to `limit` - same idea as rerank_emails for historical emails, since raw
    vector similarity can return a chunk that's topically close without
    actually answering the question. Default is False so existing callers
    that don't need this extra LLM call are unaffected.

    When rerank=True, returns None (instead of a list) specifically if the
    rerank_knowledge() call itself failed — never for a genuine "nothing
    relevant" outcome, which still returns a normal (possibly empty) list.

    audience is an explicit "parent" or "teacher" signal from the caller -
    never inferred from the email itself. category="Teaching" rows (written
    for instructors, not customers - e.g. "Class Cancellation &
    Rescheduling") are dropped before they're ever added to `results` when
    audience="parent", so they can't reach the reranker or the generator at
    all for a parent-facing email. audience="teacher" (Teacher Portal)
    keeps the existing unfiltered behavior - Teaching content stays fully
    available there. Filtering this early means a request that only had
    Teaching-category candidates still produces a genuine empty `results`
    list (or None only on an actual rerank failure, exactly as before) -
    never a fabricated retrieval error.
    """

    query = f"""
Subject:
{subject}

Body:
{body}
""".strip()
    print("USING KNOWLEDGE SEARCH FILE #1")
    print("Generating Knowledge Base query embedding...")

    query_embedding = generate_embedding(query, client=embedding_client)

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
            category = row[2] or ""

            #if url in seen_urls:
             #   continue

            #seen_urls.add(url)

            # Primary protection against teacher-facing content reaching a
            # parent-facing reply: dropped here, before dedup/append, so a
            # Teaching-category row can never enter `results` at all for
            # audience="parent" - never reaches the reranker, never reaches
            # generate_reply(). Deterministic category check, no extra LLM
            # call. audience="teacher" (Teacher Portal) is unaffected.
            if audience == "parent" and category == "Teaching":
                continue

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
                    "category": category,
                    "content": row[3] or "",
                    "url": row[4] or "",
                    "source": row[5] or "",
                    "source_id": row[6] or "",
                    "similarity": similarity,
                }
            )

            if not rerank and len(results) >= limit:
                break

        if not rerank:
            return results

        if not results:
            return results

        reranked = rerank_knowledge(subject, body, results)

        # Distinguishable from "reranked and genuinely found nothing" (which
        # returns [] below via a valid, empty `selected` list) — None means
        # the rerank call itself failed, so the caller can tell an
        # infrastructure/API hiccup apart from a real absence of relevant KB
        # content and react differently (e.g. force human review) instead of
        # silently treating an error as "nothing was found".
        if reranked.get("error"):
            return None

        selected = sorted(
            reranked["selected"],
            key=lambda item: item["confidence"],
            reverse=True
        )

        final = [
            results[item["index"]]
            for item in selected
            if 0 <= item["index"] < len(results)
        ][:limit]

        return final

    finally:
        cursor.close()
        db_pool.putconn(conn)