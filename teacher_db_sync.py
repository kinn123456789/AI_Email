from collections import defaultdict

from teacher_db_reader import (
    get_chats,
    get_chat_messages,
    get_chat_participants,
    get_users,
)

from database import (
    save_conversation,
    save_conversation_message,
    conversation_message_exists,
)


def sync_teacher_db():

    print("Loading Chats...")
    chats = get_chats()

    print("Loading Participants...")
    participants = get_chat_participants()

    print("Loading Users...")
    users = get_users()

    print("Loading Messages...")
    messages = get_chat_messages()

    # ----------------------------------------------------
    # USER LOOKUP
    # ----------------------------------------------------

    user_lookup = {
        str(user["user_id"]): user
        for user in users
    }

    print(f"Users Loaded : {len(user_lookup)}")

    # ----------------------------------------------------
    # PARTICIPANT LOOKUP
    # ----------------------------------------------------

    participant_lookup = defaultdict(
        lambda: {
            "teacher": None,
            "parent": None
        }
    )

    for participant in participants:

        chat_id = str(participant["chat_id"])
        user_id = str(participant["user_id"])
        role = participant["user_role"]

        user = user_lookup.get(user_id)

        if not user:
            continue

        participant_lookup[chat_id][role] = {
            "id": user_id,
            "name": user.get("name") or "Unknown"
        }

    # ----------------------------------------------------
    # LATEST MESSAGE LOOKUP
    # ----------------------------------------------------

    latest_message_lookup = {}

    for msg in messages:

        chat_id = str(msg["chat_id"])

        if (
            chat_id not in latest_message_lookup
            or msg["created_at"]
            > latest_message_lookup[chat_id]["created_at"]
        ):
            latest_message_lookup[chat_id] = msg

    # ----------------------------------------------------
    # SAVE CONVERSATIONS
    # ----------------------------------------------------

    print(f"\nChats Found : {len(chats)}")

    saved = 0
    skipped = 0

    for chat in chats:

        chat_id = str(chat["chat_id"])

        people = participant_lookup.get(chat_id)

        if not people:
            skipped += 1
            continue

        teacher = people.get("teacher")
        parent = people.get("parent")

        if not teacher or not parent:
            skipped += 1
            continue

        latest = latest_message_lookup.get(chat_id)

        updated_at = (
            latest["created_at"]
            if latest
            else chat["created_at"]
        )

        latest = latest_message_lookup.get(chat_id)

        save_conversation(
            chat_id=chat_id,
            parent_name=parent["name"],
            teacher_name=teacher["name"],
            parent_id=parent["id"],
            teacher_id=teacher["id"],
            updated_at=updated_at,
            last_message=latest.get("text") if latest else None,
            last_message_id=str(latest["chat_message_id"]) if latest else None,
        )

        saved += 1

    # ----------------------------------------------------
    # SAVE MESSAGES
    # ----------------------------------------------------

    inserted = 0
    duplicate = 0

    print(f"\nMessages Found : {len(messages)}")

    for message in messages:

        message_id = str(message["chat_message_id"])

        if conversation_message_exists(message_id):
            duplicate += 1
            continue

        save_conversation_message(
            chat_id=str(message["chat_id"]),
            sender=str(message["user_id"]),    # <-- store USER ID
            body=message.get("text"),
            created_at=message["created_at"],
            message_id=message_id,
        )

        inserted += 1

    print("\n====================================")
    print("Teacher DB Sync Complete")
    print("====================================")
    print(f"Chats          : {len(chats)}")
    print(f"Saved          : {saved}")
    print(f"Skipped Chats  : {skipped}")
    print(f"Messages       : {len(messages)}")
    print(f"Inserted       : {inserted}")
    print(f"Duplicates     : {duplicate}")
    print("====================================")


if __name__ == "__main__":
    sync_teacher_db()