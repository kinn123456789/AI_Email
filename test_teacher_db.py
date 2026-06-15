from database import (
    save_conversation,
    save_conversation_message
)

save_conversation(
    "chat_123",
    "John Parent",
    "Nicole Teacher",
    "2026-06-10 14:00:00"
)

save_conversation_message(
    "chat_123",
    "parent",
    "Hello teacher",
    "2026-06-10 14:01:00"
)

print("Test data inserted successfully")