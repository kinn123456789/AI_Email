from supabase_client import supabase

response = supabase.auth.admin.create_user(
    {
        "email": "trialtest001@example.com",
        "password": "Test12345!",
        "email_confirm": True
    }
)

print(response.user.id)