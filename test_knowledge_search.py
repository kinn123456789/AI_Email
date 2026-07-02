from knowledge_search import search_knowledge_base

results = search_knowledge_base(
    subject="Refund",
    body="Can I get a refund for my subscription?"
)

for r in results:

    print("=" * 60)
    print(r["title"])
    print(r["url"])
    print(r["distance"])
    print()
    print(r["content"])