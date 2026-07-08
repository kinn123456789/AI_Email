from supabase_client import supabase

response = supabase.auth.admin.list_users()

print(response)