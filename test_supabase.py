from supabase_client import supabase

print("Connecting...")

response = (
    supabase
    .table("FreeTrialPass")
    .select("*")
    .limit(5)
    .execute()
)

print("Connected!")
print("Rows:", len(response.data))

for row in response.data:
    print(row)