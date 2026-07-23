from datetime import datetime, timezone, timedelta
from trial_followup import (
    get_trial_followup_candidates,
    get_followup_history,
    create_followup,
    update_followup_email1_sent,
    update_followup_email2_sent,
    update_followup_email3_sent,
    get_parent_details,
    save_followup_email_log,
    complete_followup_campaign

    
)
from followup_ai import generate_followup_email
from followup_email import send_email




def send_followup_email(candidate, parent_id, learner_id, email_number):
    """Helper to generate, send, and update tracking for an email."""
    # Generate AI email
    # Get parent details
    parent = get_parent_details(parent_id)

    if not parent:
        print(f"Parent details not found for {parent_id}")
        return False

    parent_email = parent["email"]
    parent_name = parent["name"]

    # Generate AI email
    subject, body = generate_followup_email(
        candidate,
        parent_name=parent_name,
        email_number=email_number
    )

    if not subject or not body:
        print(f"AI failed to generate email {email_number}")
        return False

   

    

    

    print(f"Sending Email {email_number} to: {parent_email}")

    # Send email through AI
    #gmail_message_id = send_email(
      #  parent_email,
      #  subject,
      #  body
    #)
    
    #if not gmail_message_id:
      #  print(f"✗ Email {email_number} sending failed")
      #  return False
    print("Saving AI draft for review...")

    gmail_message_id = None

    save_followup_email_log(
        learner_id=learner_id,
        learner_name=candidate["learner_name"],
        parent_id=parent_id,
        parent_name=parent_name,
        email_number=email_number,
        recipient_email=parent_email,
        subject=subject,
        email_body=body,
        #gmail_message_id=gmail_message_id,
        #status="sent",
        gmail_message_id=None,
        status="draft"
    )


    

    print(f"Gmail Message ID: {gmail_message_id}")
    print(f"✓ Email {email_number} sent successfully")

    # Update database
    if email_number == 1:
        update_followup_email1_sent(learner_id)
    elif email_number == 2:
        update_followup_email2_sent(learner_id)
    elif email_number == 3:
        update_followup_email3_sent(learner_id)
        complete_followup_campaign(learner_id)

   
    return True

def process_trial_followups():
    print(f"\n--- Starting Follow-up Run: {datetime.now(timezone.utc)} ---")
    
    # 1. Fetch Candidates (Ensure this function has .limit(100) inside it)
    candidates = get_trial_followup_candidates()
    
    if not candidates:
        print("No eligible learners found. Exiting.")
        return

    print(f"Found {len(candidates)} candidates to process.")

    # 2. Get history for all fetched candidates in one batch
    learner_ids = [c["learner_id"] for c in candidates]
    followup_history = get_followup_history(learner_ids)
    now = datetime.now(timezone.utc)

    # 3. Process each candidate
    for candidate in candidates:
        try:
            learner_id = candidate["learner_id"]
            parent_id = candidate["parent_id"]
            trial_expiry_at = candidate["trial_expiry_at"]

            # Standardize timezone
            if trial_expiry_at and trial_expiry_at.tzinfo is None:
                trial_expiry_at = trial_expiry_at.replace(tzinfo=timezone.utc)

            followup = followup_history.get(learner_id)

            print("=" * 60)
            print("Learner:", learner_id)
            print("Followup:", followup)

            # Initialize tracking if missing
            if not followup:
                print(f"Initializing tracking for learner: {learner_id}")
                create_followup(
                    parent_id=parent_id,
                    learner_id=learner_id,
                    free_trial_pass_id=candidate["free_trial_pass_id"],
                    trial_expiry_at=trial_expiry_at
                )
                followup = {
                    "status": "active",
                    "email1_sent_at": None,
                    "email2_sent_at": None,
                    "email3_sent_at": None,
                }

            # Skip if campaign closed
            if followup.get('status') != 'active':
                continue

            email1 = followup.get('email1_sent_at')
            email2 = followup.get('email2_sent_at')
            email3 = followup.get('email3_sent_at')

            # Temporary test mode: trigger follow-ups after 5/10/15 minutes.
            if email1 is None and trial_expiry_at <= now - timedelta(minutes=2):
                send_followup_email(candidate, parent_id, learner_id, 1)
            elif email1 is not None and email2 is None and trial_expiry_at <= now - timedelta(minutes=3):
                send_followup_email(candidate, parent_id, learner_id, 2)
            elif email1 is not None and email2 is not None and email3 is None and trial_expiry_at <= now - timedelta(minutes=4):
                send_followup_email(candidate, parent_id, learner_id, 3)

        except Exception as e:
            print(f"Error processing learner {candidate.get('learner_id')}: {e}")

if __name__ == "__main__":
    process_trial_followups()