from learn_email_style import sync_sent_mail_style_examples
from embed_historical_emails import main as embed_historical_emails
from database import prune_old_historical_emails, HISTORICAL_EMAIL_RETENTION_MONTHS


def sync_sent_mail_and_embed():
    """Runs the Sent Mail catch-up import, embeds anything it just saved,
    then prunes anything older than HISTORICAL_EMAIL_RETENTION_MONTHS — one
    combined maintenance pass for the historical_emails table, all on the
    same 15-day schedule. Import is for the occasional case of a reply sent
    directly from Gmail instead of through this app's own Send button
    (which already saves+embeds automatically); pruning keeps the table
    from growing forever, bounding storage/maintenance cost long-term
    (search speed itself doesn't need this — the vector index stays fast
    regardless of table size at this scale). See scheduler.py for the
    schedule."""

    print("=" * 60)
    print("Sent Mail style-example sync started")
    print("=" * 60)

    sync_sent_mail_style_examples()

    print("=" * 60)
    print("Embedding new historical emails")
    print("=" * 60)

    embed_historical_emails()

    print("=" * 60)
    print(f"Pruning historical emails older than {HISTORICAL_EMAIL_RETENTION_MONTHS} months")
    print("=" * 60)

    deleted = prune_old_historical_emails()
    print(f"Pruned {deleted} old historical email(s)")

    print("=" * 60)
    print("Sent Mail style-example sync complete")
    print("=" * 60)


if __name__ == "__main__":
    sync_sent_mail_and_embed()
