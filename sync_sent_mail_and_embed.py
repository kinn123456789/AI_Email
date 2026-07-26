from learn_email_style import sync_sent_mail_style_examples
from embed_historical_emails import main as embed_historical_emails


def sync_sent_mail_and_embed():
    """Runs the Sent Mail catch-up import, then embeds anything it just
    saved, so new rows become usable by the AI in the same run instead of
    sitting un-embedded until a separate script happens to be run. Meant
    for the occasional case of a reply sent directly from Gmail instead of
    through this app's own Send button (which already saves+embeds
    automatically) — see scheduler.py for the schedule."""

    print("=" * 60)
    print("Sent Mail style-example sync started")
    print("=" * 60)

    sync_sent_mail_style_examples()

    print("=" * 60)
    print("Embedding new historical emails")
    print("=" * 60)

    embed_historical_emails()

    print("=" * 60)
    print("Sent Mail style-example sync complete")
    print("=" * 60)


if __name__ == "__main__":
    sync_sent_mail_and_embed()
