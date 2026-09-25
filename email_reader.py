import os
import email
import base64
import time
import imaplib
import traceback
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

from openai import OpenAI

from email.utils import parseaddr
from email.header import decode_header
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from email_sender import send_email
from sync_sent_gmail import main as sync_sent_mail

# Vector & Knowledge Search
from vector_search import search_similar_emails
from rag_reranker import rerank_emails
from reply_generator import generate_reply
from emails_cleaner import clean_email_body
from knowledge_search import search_knowledge_base
from process_email import process_email
from database import email_exists
from embedding_service import new_embedding_client, close_embedding_client

# Custom modules
from email_filter import is_automated_email
from ai_classifier import ai_triage
from email.utils import parsedate_to_datetime

# Configuration
load_dotenv()
ATTACHMENT_DIR = "attachments"
if not os.path.exists(ATTACHMENT_DIR):
    os.makedirs(ATTACHMENT_DIR)

# Caps how many non-duplicate emails get fully fetched+processed in a single
# poll. Without this, a large unseen backlog (e.g. after downtime) triggers a
# full BODY.PEEK[] fetch + AI pipeline for every one of them in one run, all
# in-memory at once, which is what has been causing repeated OOM kills on the
# 512MB instance. Leftover messages are simply picked up on the next 5-minute
# run since they stay "unseen".
MAX_EMAILS_PER_RUN = 15

def get_email_accounts():
    """The 3 core mailboxes plus anything added via the Settings page -
    fetched fresh on every call, never cached at import time, so an
    account added/removed in Settings takes effect on the very next
    scheduled run in this same long-running process, no restart needed.
    See database.get_all_email_accounts(). Deliberately a function, not a
    module-level list - a list snapshotted once at import time would never
    see accounts added later in the process's lifetime."""

    from database import get_all_email_accounts
    return get_all_email_accounts()


def oauth_login(email_address, token_file=None):
    # token_file is unused now (kept only so existing callers don't need to
    # change) - auth is via domain-wide delegation, impersonating
    # email_address directly. See gmail_auth.py.
    from gmail_auth import imap_login
    return imap_login(email_address)

def _new_llm_client():
    # Reuses the exact same construction already used by ai_classifier.py,
    # rag_reranker.py, and reply_generator.py's own module-level `client`
    # (same env var, same base_url, same model-independent client - no
    # credentials duplicated or hardcoded here, and no model selection
    # happens at client-construction time at all).
    return OpenAI(
        api_key=os.getenv("OPENROUTER_API_KEY"),
        base_url="https://openrouter.ai/api/v1",
    )


def _process_account(account):
    """One mailbox worker. Owns one isolated 5-client LLM/embedding bundle
    for its entire run - created once here, reused for every message this
    account processes (never recreated per message), and closed exactly
    once in the outer finally below, regardless of whether this account's
    processing succeeds or raises. See process_email.py's llm_clients
    docstring for the full concurrency reasoning this bundle exists to
    satisfy: without it, concurrently-running mailbox workers would share
    ai_classifier.py/rag_reranker.py/reply_generator.py's module-level
    clients across threads for the first time ever, which is exactly the
    hazard embedding_service.py's new_embedding_client() already exists to
    avoid for embeddings.

    Mechanical extraction of the former per-account loop body in main() -
    the only changes from that original code are: an explicit `return`
    instead of `continue` (this is now a standalone callable, not a loop
    iteration), creating/threading through/closing the client bundle, and
    prefixing the account's own status lines with its email address now
    that mailbox logs can interleave. IMAP login, mailbox selection,
    search criteria, date window, duplicate detection, message fetch,
    parsing, the process_email() call itself, error handling, and message
    ordering within this mailbox are all unchanged."""

    if not account.get("email"):
        return

    llm_clients = {
        "classifier": _new_llm_client(),
        "reranker": _new_llm_client(),
        "generator": _new_llm_client(),
        "similar_embedding": new_embedding_client(),
        "knowledge_embedding": new_embedding_client(),
    }

    try:
        print("=" * 60)
        print(f"[{account['email']}] Checking:", account["source"])
        print("=" * 60)

        mail = None

        try:
            mail = oauth_login(account["email"])
            mail.select("INBOX", readonly=True)

            since_date = (datetime.now() - timedelta(days=2)).strftime("%d-%b-%Y")
            status, messages = mail.search(None, "OR", "UNSEEN", "SINCE", since_date)
            print(f"[{account['email']}]", account["source"], "Unread/recent emails:", len(messages[0].split()))
            if status != "OK":
                return

            # EXACT ORIGINAL LIMITING LOGIC RESTORED
            mail_ids = messages[0].split()

            processed_count = 0

            for email_id in mail_ids:

                if processed_count >= MAX_EMAILS_PER_RUN:
                    print(
                        f"[{account['email']}]",
                        account["source"],
                        f"Reached MAX_EMAILS_PER_RUN ({MAX_EMAILS_PER_RUN}); "
                        "remaining unseen messages will be picked up next run."
                    )
                    break

                # Cheap pre-check: this backlog is read via readonly=True (so
                # Gmail's own unread state is never touched, and the same
                # "unseen" ids keep showing up every run) - most of the ids
                # here are ones we've already processed on a prior run and
                # will just be discarded as duplicates. Fetching only the
                # Message-ID header first (a few bytes) instead of the full
                # BODY.PEEK[] (the entire raw message, attachments included)
                # avoids paying that full download cost 5 minutes later for
                # the same already-known messages, forever, as this backlog
                # grows.
                status, header_data = mail.fetch(
                    email_id,
                    "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])"
                )

                if (
                    status != "OK"
                    or not header_data
                    or not isinstance(header_data[0], tuple)
                ):
                    continue

                header_msg = email.message_from_bytes(
                    header_data[0][1]
                )

                candidate_message_id = " ".join(
                    (header_msg.get("Message-ID") or "").split()
                )

                if candidate_message_id and email_exists(
                    candidate_message_id, account["source"]
                ):
                    continue

                status, msg_data = mail.fetch(
                    email_id,
                    "(BODY.PEEK[])"
                )

                if (
                    status != "OK"
                    or not msg_data
                    or not isinstance(msg_data[0], tuple)
                ):
                    continue

                msg = email.message_from_bytes(
                    msg_data[0][1]
                )


                email_date = parsedate_to_datetime(msg["Date"])
                try:
                    process_email(
                        msg=msg,
                        account=account,
                        ingested_via="imap_poll",
                        llm_clients=llm_clients,
                    )
                except Exception:
                    traceback.print_exc()
                    continue
                finally:
                    processed_count += 1



        finally:
            if mail:
                try:
                    mail.logout()
                except Exception:
                    pass
    finally:
        close_embedding_client(llm_clients["classifier"])
        close_embedding_client(llm_clients["reranker"])
        close_embedding_client(llm_clients["generator"])
        close_embedding_client(llm_clients["similar_embedding"])
        close_embedding_client(llm_clients["knowledge_embedding"])


def main(target_email=None):
    # target_email filtering happens here, at selection time - the exact
    # same semantics as before (only the named mailbox is processed when
    # given, every account otherwise), except now it also means an
    # unselected account never gets submitted to the executor at all,
    # rather than being iterated and skipped.
    accounts = [
        account for account in get_email_accounts()
        if not target_email or account["email"] == target_email
    ]

    # Exactly 3 workers because there are exactly 3 core mailboxes today -
    # not a dynamic count. Each mailbox worker (_process_account) owns its
    # own isolated LLM/embedding client bundle; nothing here shares state
    # across workers. as_completed() means one slow mailbox never blocks
    # collecting/logging the others' results. The existing reader_lock in
    # scheduler.py already ensures only one full email_reader.main() run is
    # in flight at a time - unchanged, not touched here - so this executor
    # only ever parallelizes the mailboxes within one such run.
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(_process_account, account): account
            for account in accounts
        }

        for future in as_completed(futures):
            account = futures[future]
            try:
                future.result()
            except Exception:
                print(f"[{account.get('email')}] mailbox worker failed:")
                traceback.print_exc()
                continue

    print("=" * 60)
    print("ABOUT TO START SENT MAIL SYNC")
    print("=" * 60)

   # try:
       # sync_sent_mail()

        #print("=" * 60)
       # print("SENT MAIL SYNC FINISHED")
       # print("=" * 60)

    #except Exception:
       # print("=" * 60)
       # print("SENT MAIL SYNC FAILED")
       # traceback.print_exc()

    print("=" * 60)


if __name__ == "__main__":
    main()