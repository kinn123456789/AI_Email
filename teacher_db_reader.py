from supabase import create_client
import os
from dotenv import load_dotenv

load_dotenv()

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SECRET_KEY")
)


def get_chats():
    return (
        supabase.table("Chats")
        .select("*")
        .execute()
    ).data


def get_chat_messages():
    return (
        supabase.table("ChatMessages")
        .select("*")
        .eq("is_deleted", False)
        .order("created_at")
        .execute()
    ).data


def get_chat_participants():
    return (
        supabase.table("ChatParticipants")
        .select("*")
        .execute()
    ).data


def get_users():
    return (
        supabase.table("Users")
        .select("user_id,name,username,type")
        .execute()
    ).data