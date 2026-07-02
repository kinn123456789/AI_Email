from vector_search import search_similar_emails
from rag_reranker import rerank_emails
import json

subject = "Can we reschedule?"
body = "Our family will be on vacation next week. My daughter will miss Tuesday's class."

results = search_similar_emails(subject, body)


for email in results:
    print(email[0], email[7], email[2])

reranked = rerank_emails(subject, body, results)

print(json.dumps(reranked, indent=4))