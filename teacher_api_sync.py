from teacher_portal_api_reader import (
    get_teachers,
    get_chats,
    get_messages
)

from database import (
    save_conversation,
    save_conversation_message,
    conversation_message_exists,
    get_last_message_id
)


def sync_teacher_portal():

    teachers = get_teachers()

    print("=" * 70)
    print("Teacher Portal Sync Started")
    print("=" * 70)

    total_chats = 0
    total_messages = 0
    new_messages = 0

    for teacher in teachers:

        teacher_id = teacher["id"]
        teacher_name = teacher["name"]

        print(f"\nTeacher: {teacher_name}")

        try:
            chats = get_chats(teacher_id)
        except Exception as e:
            print("Unable to fetch chats:", e)
            continue

        print(f"Chats Found: {len(chats)}")

        total_chats += len(chats)

        for chat in chats:
            

            latest = chat.get("latest_message")

            latest_message_id = str(latest["id"]) if latest else None

            stored_message_id = get_last_message_id(chat["id"])

            if latest_message_id == stored_message_id:
                continue
            participants = chat["participants"]

            parent = None
            teacher_user = None

            for p in participants:

                if p["user_role"] == "parent":
                    parent = p

                elif p["user_role"] == "teacher":
                    teacher_user = p

            if not parent or not teacher_user:
                continue

            latest = chat.get("latest_message")

            save_conversation(
                chat_id=chat["id"],
                parent_name=parent["user"]["name"],
                teacher_name=teacher_user["user"]["name"],
                parent_id=parent["user"]["id"],
                teacher_id=teacher_user["user"]["id"],
                updated_at=latest["created_at"] if latest else chat["created_at"],
                last_message=latest["text"] if latest else "",
                last_message_id=str(latest["id"]) if latest else None,
                unread_count=0
            )

            try:
                response = get_messages(chat["id"], teacher_id)
            except Exception as e:
                print("Unable to fetch messages:", e)
                continue

            messages = response["response"]["messages"]

            total_messages += len(messages)

            for message in messages:

                message_id = str(message["id"])

                if conversation_message_exists(message_id):
                    continue

                save_conversation_message(
                    chat_id=chat["id"],
                    sender=str(message["user_id"]),
                    body=message.get("text"),
                    created_at=message["created_at"],
                    message_id=message_id
                )

                new_messages += 1

    print("\n" + "=" * 70)
    print("Teacher Portal Sync Complete")
    print("=" * 70)
    print(f"Teachers       : {len(teachers)}")
    print(f"Chats          : {total_chats}")
    print(f"Messages Seen  : {total_messages}")
    print(f"New Messages   : {new_messages}")
    print("=" * 70)


if __name__ == "__main__":
    sync_teacher_portal()