from teacher_portal_reader import (
    get_teachers,
    get_chats,
    get_messages
)
from database import (
    save_conversation,
    save_conversation_message,
    conversation_message_exists
)

def sync_teacher_portal():

    teachers = get_teachers()
    print("Total teachers:", len(teachers))

    for teacher in teachers:

        api_teacher_id = teacher["id"]

        print(f"\nProcessing teacher: {teacher['name']}")

        chats = get_chats(api_teacher_id)
        print(
            f"Teacher: {teacher['name']} | Chats: {len(chats)}"
        )

        for chat in chats:

   

            chat_id = chat["id"]

            parent_name = "Unknown"
            teacher_name = "Unknown"

            parent_id = None
            conversation_teacher_id = None

            print("\nParticipants:")
            for participant in chat["participants"]:
                print(
                    participant["user_role"],
                    participant["user"]["name"],
                    participant["user"]["id"]
                )

            parent_name = "Unknown"
            teacher_name = "Unknown"
            parent_id = None
            conversation_teacher_id = None

            for participant in chat["participants"]:

                if participant["user_role"] == "parent":
                    parent_name = participant["user"]["name"]
                    parent_id = participant["user"]["id"]

                elif participant["user_role"] == "teacher":
                    teacher_name = participant["user"]["name"]
                    conversation_teacher_id = participant["user"]["id"]

            print("Saving:")
            print("Parent :", parent_name, parent_id)
            print("Teacher:", teacher_name, conversation_teacher_id)
            print("Saving:")
            print("Parent :", parent_name)
            print("Teacher:", teacher_name)
            print("Parent ID :", parent_id)
            print("Teacher ID:", conversation_teacher_id)
            
            save_conversation(
                chat_id,
                parent_name,
                teacher_name,
                parent_id,
                conversation_teacher_id,
                chat["created_at"]
            )

            print("Saved conversation:", chat_id)

            messages_response = get_messages(
                chat_id, 
                api_teacher_id)
            if messages_response is None:
                continue
            messages = messages_response["response"]["messages"]
            print(
                f"Messages in chat: {len(messages)}"
        )




            for message in messages:
                
                print(message)
                
                if conversation_message_exists(message["id"]):
                    continue

                save_conversation_message(
                    chat_id,
                    message["user_id"],
                    message.get("text"),
                    message["created_at"],
                    message["id"]
                )

                print("Saved message:", message["id"])


if __name__ == "__main__":
    sync_teacher_portal()