from search_knowledge_base import search_knowledge_base

results = search_knowledge_base(
    "Can my 9 year old join Scratch Coding?"
)

for r in results:

    print("=" * 60)

    print(r["source"])
    print(r["title"])
    print(r["section"])
    print(r["similarity"])

    print()

    print(r["content"][:500])