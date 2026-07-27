import os
import email
import imaplib
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from email.header import decode_header, make_header
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from emails_cleaner import clean_email_body
# Project modules
from logger import logger
from database import (
    db_pool,
    save_email,
    email_exists,
    get_message_by_message_id,
)
from email.utils import parsedate_to_datetime
from database import (
    set_sent_time,
    save_sync_log,
    get_last_successful_sync_time,
    save_failed_sync_message,
    get_pending_retry_messages,
    get_failed_sync_message_by_id,
    mark_failed_message_resolved,
    mark_failed_message_exhausted,
)

load_dotenv()

# Fallback window used only when there's no prior clean sync recorded yet
# (first-ever run for this account). Once a checkpoint exists, the actual
# last-successful-sync time is used instead — see main().
BOOTSTRAP_WINDOW_DAYS = 7

# IMAP's SINCE search is date-only (no time-of-day precision), so the
# checkpoint is backed off by a day regardless of the exact finish time —
# a message from earlier the same calendar day as the last sync would
# match SINCE anyway, and email_exists() correctly skips it as a
# duplicate; this just guards against any edge case near a day boundary.
CHECKPOINT_BUFFER_DAYS = 1

# Sanity cap only — not the primary correctness mechanism anymore (the
# checkpoint is). Guards against a pathological case (checkpoint broken
# for a long time, huge backlog) rather than normal operation, where a
# run typically finds only a handful of genuinely new messages.
MAX_MESSAGES_PER_RUN = 500

EMAIL_ACCOUNTS = [
    {
        "email": os.getenv("EMAIL_1"),
        "token": "token_support.json",
        "source": "support@coralacademy.com",
    },
    {
        "email": os.getenv("EMAIL_2"),
        "token": "token_lucy.json",
        "source": "lucy@coralacademy.com",
    },
    {
        "email": os.getenv("EMAIL_3"),
        "token": "token_engineering.json",
        "source": "engineering@coralacademy.com",
    },
]
def oauth_login(email_address, token_file=None):
    # token_file is unused now (kept only so existing callers don't need to
    # change) - auth is via domain-wide delegation, impersonating
    # email_address directly. See gmail_auth.py.
    from gmail_auth import imap_login
    return imap_login(email_address)


def _process_sent_message(mail, sent_id, account):
    """Fetches, threads, and saves one sent message identified by sent_id
    (an IMAP sequence number valid for the current mail session — either
    from the normal SINCE search, or from a fresh Message-ID relocate
    during a retry). Shared by both the normal sweep and the retry sweep
    so they can never drift out of sync with each other.

    Returns (outcome, email_date, message_id, error):
      outcome is "imported", "duplicate", or "error".
      email_date/message_id are None only if the failure happened before
      they could even be extracted (so there's nothing to key a retry on).
    """

    status, msg_data = mail.fetch(sent_id, "(RFC822)")
    if status != "OK":
        return "error", None, None, "IMAP fetch returned non-OK status"

    msg = email.message_from_bytes(msg_data[0][1])
    email_date = parsedate_to_datetime(msg["Date"])
    message_id = " ".join((msg.get("Message-ID") or "").split())

    try:
        in_reply_to = " ".join((msg.get("In-Reply-To") or "").split())
        references = " ".join((msg.get("References") or "").split())

        thread_id, parent = message_id, None
        if in_reply_to:
            parent = get_message_by_message_id(in_reply_to, account["source"])

        if not parent and references:
            for ref in reversed(references.split()):
                parent = get_message_by_message_id(ref, account["source"])
                if parent: break

        if parent:
            thread_id = parent["thread_id"]
            set_sent_time(parent["id"])
            logger.info(f"Thread linked: {message_id} -> {thread_id}")
        else:
            logger.info(f"New thread: {message_id}")

        if not message_id or email_exists(message_id, account["source"]):
            logger.info(f"Duplicate skipped: {message_id}")
            return "duplicate", email_date, message_id, None

        body, html_body = "", ""
        for part in msg.walk():
            if part.get_filename(): continue
            content_type = part.get_content_type()
            payload = part.get_payload(decode=True)
            if not payload: continue
            if content_type == "text/plain": body += payload.decode(errors="ignore")
            elif content_type == "text/html": html_body += payload.decode(errors="ignore")

        if not body.strip() and html_body:
            body = BeautifulSoup(html_body, "html.parser").get_text(separator=" ", strip=True)

        body = clean_email_body(body)

        has_attachment = any(part.get_filename() for part in msg.walk())

        save_email(
            sender=parseaddr(msg.get("From", ""))[1],
            subject=str(make_header(decode_header(msg.get("Subject", "")))),
            body=body,
            category="Human Reply",
            priority="Low",
            ai_summary="Reply sent manually from Gmail",
            ai_draft_reply=body,
            message_id=message_id,
            thread_id=thread_id,
            in_reply_to=in_reply_to,
            source=account["source"],
            status="Replied",
            requires_review=False,
            reply_type="gmail_manual",
            references_header=references,
            email_date=email_date,
            has_attachment=has_attachment
        )
        logger.info(f"Imported: {message_id}")
        mail.store(sent_id, '+FLAGS', '\\Seen')

        return "imported", email_date, message_id, None

    except Exception as e:
        return "error", email_date, message_id, str(e)


def _retry_pending_failures(mail, account):
    """Gives each previously-failed message one automatic retry, relocating
    it by Message-ID (stable, unlike the sequence number it failed under
    originally — sequence numbers drift as new mail arrives). This is the
    2nd and final attempt: whatever happens here, the row leaves
    'pending_retry' — resolved on success, exhausted (manual follow-up)
    on failure. Runs before the normal sweep each hour."""

    pending = get_pending_retry_messages("sync_sent_gmail", account["source"])

    for row in pending:
        message_id = row["message_id"]

        try:
            status, search_data = mail.search(None, f'(HEADER Message-ID "{message_id}")')
            if status != "OK" or not search_data[0]:
                mark_failed_message_exhausted(row["id"], "Could not relocate message for retry")
                logger.info(f"Retry could not relocate {message_id}, marked exhausted")
                continue

            sent_id = search_data[0].split()[-1]
            outcome, _, _, err = _process_sent_message(mail, sent_id, account)

        except Exception as e:
            outcome, err = "error", str(e)

        if outcome == "error":
            mark_failed_message_exhausted(row["id"], err)
            logger.info(f"Retry failed permanently for {message_id}: {err}")
        else:
            mark_failed_message_resolved(row["id"])
            logger.info(f"Retry succeeded for {message_id} ({outcome})")


def retry_one_now(row_id):
    """On-demand retry for a single failed-sync row, triggered manually
    from the dashboard's failed-sync panel — as opposed to _retry_pending_failures(),
    which the hourly job runs automatically for every pending row on an
    account. Same relocate-by-Message-ID + _process_sent_message logic,
    just scoped to the one row a staff member clicked "Retry" on.

    Returns a short status string for the caller to show/log; never
    raises — any failure just leaves the row as-is (still pending_retry
    or exhausted) so it can be retried again or reviewed manually."""

    row = get_failed_sync_message_by_id(row_id)

    if not row:
        return "not_found"

    if row["job_name"] != "sync_sent_gmail":
        return "unsupported_job"

    account = next(
        (a for a in EMAIL_ACCOUNTS if a["source"] == row["account"]),
        None
    )

    if not account:
        return "unknown_account"

    mail = None

    try:
        mail = oauth_login(account["email"], account["token"])
        status, _ = mail.select('"[Gmail]/Sent Mail"')

        if status != "OK":
            return "mailbox_error"

        message_id = row["message_id"]
        status, search_data = mail.search(None, f'(HEADER Message-ID "{message_id}")')

        if status != "OK" or not search_data[0]:
            mark_failed_message_exhausted(row["id"], "Could not relocate message for manual retry")
            return "not_relocated"

        sent_id = search_data[0].split()[-1]
        outcome, _, _, err = _process_sent_message(mail, sent_id, account)

        if outcome == "error":
            mark_failed_message_exhausted(row["id"], err)
            return "failed"

        mark_failed_message_resolved(row["id"])
        return outcome  # "imported" or "duplicate"

    except Exception as e:
        logger.error(f"Manual retry failed for row {row_id}: {e}")
        return "error"

    finally:
        if mail:
            try: mail.logout()
            except Exception: pass


def main():
    for account in EMAIL_ACCOUNTS:
        logger.info(f"Checking sent mail for {account['source']}")
        mail = None
        started_at = datetime.now(timezone.utc)
        imported, skipped, error_count = 0, 0, 0
        error_message = None
        # None means "no safe progress established yet this run" — only ever
        # replaced with a real, conservatively-computed value below. Never
        # defaults to now(), so a total failure before reaching the search
        # (e.g. login failure) correctly leaves the checkpoint untouched.
        checkpoint_time = None

        try:
            mail = oauth_login(account["email"], account["token"])
            status, _ = mail.select('"[Gmail]/Sent Mail"')
            if status != "OK":
                logger.error(f"Could not open Sent Mail for {account['source']}")
                error_count += 1
                error_message = "Could not open Sent Mail"
                continue

            try:
                _retry_pending_failures(mail, account)
            except Exception:
                logger.exception(f"Retry sweep failed for {account['source']}")

            # Real checkpoint (the last confirmed-safe progress point for
            # this account — see checkpoint_time below) instead of a fixed
            # lookback window or a count-based "last N" slice — either of
            # those could silently miss messages if volume in the window
            # ever exceeded the slice size. Falls back to a 7-day bootstrap
            # window only on the very first run, when there's no checkpoint yet.
            last_success = get_last_successful_sync_time("sync_sent_gmail", account["source"])

            if last_success:
                since_dt = last_success - timedelta(days=CHECKPOINT_BUFFER_DAYS)
            else:
                since_dt = datetime.now(timezone.utc) - timedelta(days=BOOTSTRAP_WINDOW_DAYS)

            since_date = since_dt.strftime("%d-%b-%Y")
            status, search_data = mail.search(None, f'(SINCE "{since_date}")')

            if status != "OK": continue

            all_ids = search_data[0].split()
            message_ids = all_ids[-MAX_MESSAGES_PER_RUN:]
            truncated = len(all_ids) > MAX_MESSAGES_PER_RUN
            oldest_processed_date = None
            # Newest date among messages this run actually confirmed handled
            # (imported or recognized as an existing duplicate) — lets the
            # checkpoint advance on the messages that succeeded even if some
            # other message in the same run threw an exception, instead of
            # one bad message blocking every future run's progress forever.
            latest_success_date = None

            for sent_id in message_ids:
                try:
                    outcome, email_date, message_id, err = _process_sent_message(mail, sent_id, account)
                except Exception as e:
                    outcome, email_date, message_id, err = "error", None, None, str(e)

                if email_date and (oldest_processed_date is None or email_date < oldest_processed_date):
                    oldest_processed_date = email_date

                if outcome == "error":
                    logger.error(f"Failed processing sent email {sent_id}: {err}")
                    error_count += 1
                    error_message = err
                    if message_id:
                        try:
                            save_failed_sync_message("sync_sent_gmail", account["source"], message_id, err)
                        except Exception:
                            logger.error(f"Failed to record failed sync message {message_id}")
                    continue

                if outcome == "duplicate":
                    skipped += 1
                elif outcome == "imported":
                    imported += 1

                if email_date and (latest_success_date is None or email_date > latest_success_date):
                    latest_success_date = email_date

            if truncated and oldest_processed_date:
                # Backlog exceeded MAX_MESSAGES_PER_RUN — cap the checkpoint at the
                # oldest message actually processed instead of "now", so the next
                # run's SINCE search picks up right where this one stopped rather
                # than skipping the untouched older messages forever.
                checkpoint_time = oldest_processed_date
                logger.info(
                    f"{account['source']}: backlog exceeded {MAX_MESSAGES_PER_RUN}, "
                    f"checkpoint capped at {checkpoint_time} instead of now"
                )
            elif latest_success_date:
                # Not truncated, but at least one message failed elsewhere in
                # this run — advance only as far as what's confirmed handled,
                # instead of either "now" (would wrongly claim the failed
                # message is covered) or leaving the checkpoint untouched
                # (would let one bad message block every future run forever).
                checkpoint_time = latest_success_date
            elif not message_ids:
                # Nothing matched the search at all — nothing to lose by
                # moving up to now.
                checkpoint_time = datetime.now(timezone.utc)
            else:
                # Every message in this run failed; no safe progress to record.
                checkpoint_time = None

            logger.info(f"{account['source']} sync complete. Imported={imported}, Skipped={skipped}")

        except Exception as e:
            logger.exception(f"Failed to process {account['source']}")
            error_count += 1
            error_message = str(e)
        finally:
            if mail:
                try: mail.logout()
                except Exception: pass

            try:
                save_sync_log(
                    job_name="sync_sent_gmail",
                    account=account["source"],
                    started_at=started_at,
                    finished_at=checkpoint_time,
                    imported_count=imported,
                    skipped_count=skipped,
                    error_count=error_count,
                    error_message=error_message,
                )
            except Exception as e:
                logger.error(f"Failed to save sync_log for {account['source']}: {e}")

if __name__ == "__main__":
    main()