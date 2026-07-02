from embedding_service import generate_embedding

text = """
Subject: Child absent

My daughter has fever and won't attend class tomorrow.
"""

embedding = generate_embedding(text)

print(type(embedding))
print(len(embedding))
print(embedding[:10])
