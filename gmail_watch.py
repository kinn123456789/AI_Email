#gmail_watch.py
from gmail_auth import get_gmail_service

TOPIC = "projects/lively-lock-500515-e4/topics/gmail-notifications"


def register_watch(email_address):

    service = get_gmail_service(email_address)

    try:
        result = service.users().watch(
            userId="me",
            body={
                "topicName": TOPIC
            }
        ).execute()

        profile = service.users().getProfile(userId="me").execute()

        print("=" * 70)
        print(f"Watch registered for: {profile['emailAddress']}")
        print(result)
        print("=" * 70)
        return result
    finally:
        service.close()

def renew_all_gmail_watches():

    from email_reader import get_email_accounts

    for account in get_email_accounts():
        try:
            register_watch(account["email"])
        except Exception as e:
            print(f"Failed to renew watch for {account['email']}: {e}")

if __name__ == "__main__":
    renew_all_gmail_watches()
    