from vector_search import search_similar_emails

results = search_similar_emails(
    subject="Child absent tomorrow",
    body="My son has a fever and will be absent tomorrow."
)

print()

for email in results:

    print("=" * 70)

    
    print(f"Similarity : {email[7]:.2%}")
    print(f"Subject    : {email[2]}")
    print(f"Sender     : {email[1]}")
    print(f"Sent At    : {email[4]}")
    print(email[3][:200])

    print("\nBody")
    

    print(f"\nThread ID")
    print(email[5])

    print()