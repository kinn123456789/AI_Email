# ⚙️ Settings Module — Full Documentation

*Managing which email accounts this app actually reads, watches, and sends from — without touching code.*

---

## 🌟 What This Module Does (Simple Version)

This app watches specific email inboxes (support@, lucy@, engineering@coralacademy.com) — reading incoming mail, sending replies, learning writing style from sent mail, all of it. Until this session, which mailboxes were watched was **hardcoded in the code**, repeated across several files — adding or removing a mailbox meant editing code and redeploying.

The Settings page fixes that: a staff member can add or delete a monitored mailbox from a simple page, and it takes effect automatically within a few minutes — no code change, no redeploy.

---

## 🎬 Features (at `/settings`)

1. **See every monitored mailbox** — the 3 "core" accounts (support/lucy/engineering, always present) plus anything added here, each shown with its status.
2. **Add an email account** — type in an address and click "+ Add Email." The address is checked live against Gmail before it's saved, so a typo or a non-Workspace address is caught immediately with a clear error, instead of silently saving something broken.
3. **Delete an email account** — removes an added mailbox from being monitored. Only accounts added through this page can be deleted here — the 3 core accounts can't be removed from this screen (they're tied to the app's own environment configuration, not this table).

---

## 🛠️ Technical Details

### Why this is only possible now — the OAuth-to-Domain-Wide-Delegation change

Before this session, each mailbox needed its **own separate Google OAuth consent flow** — a one-time manual "sign in and approve" step per account (`generate_oauthtoken.py`), producing its own token file (`token_support.json`, `token_lucy.json`, `token_engineering.json`) that had to be kept refreshed and stored on the server. Adding a new mailbox meant physically running that consent flow for the new address first — not something a staff member could just click a button for.

This session migrated the whole app to **Domain-Wide Delegation** instead: a single service account (`service-account.json`) that can impersonate *any* mailbox in the Google Workspace domain it's been granted access to, via `gmail_auth.py`'s `get_gmail_service(email)` / `imap_login(email)` — just given a plain email address, no separate consent step, no token file, no per-account setup at all. That single change is what makes this Settings page realistic to build: adding an account is now just "save the email address," not "run a manual consent flow for it first."

### Where accounts are stored (`database.py`)

- **`CORE_EMAIL_ACCOUNTS`** — the 3 original mailboxes, still read from the `EMAIL_1`/`EMAIL_2`/`EMAIL_3` environment variables (unchanged from before), not stored in a table. This is why they can't be deleted from the Settings page — deleting them would need an env var change and a redeploy anyway, same as before this feature existed.
- **`email_accounts`** table (new this session) — every mailbox added through Settings: `email`, `source_label`, `status`, `created_at`.
- **`get_all_email_accounts()`** — merges the 3 core accounts with every active row in `email_accounts` into one list, fetched **fresh on every call**, never cached. This is deliberate: `email_reader.py`, `sync_sent_gmail.py`, `learn_email_style.py`, `gmail_watch.py`, and `gmail_history.py` all call this function instead of using a hardcoded list, so an account added or deleted in Settings is picked up on the very next scheduled run (email polling every 5 minutes, sent-mail sync hourly, etc.) — not after a restart.
- **`add_email_account()` / `delete_email_account()`** — insert/delete a row in `email_accounts`. Adding uses `ON CONFLICT (email) DO UPDATE SET status = 'active'`, so re-adding a previously deleted address just reactivates it instead of erroring.

### Validation on Add (`main.py`)

Before saving, the route calls `get_gmail_service(email).users().getProfile(userId="me").execute()` — a real, live Gmail API call impersonating that exact address. If the address is misspelled, doesn't exist, or isn't in the Workspace domain the service account can impersonate, this fails immediately and the error is shown on the page — the row is never saved. On success, it also best-effort calls `register_watch(email)` so push-notification syncing starts right away, rather than waiting for the once-daily watch-renewal job; if that specific call fails, the account is still added, since the 5-minute polling backup covers it regardless.

### Deleting an Account

Deleting just removes the row from `email_accounts` — it stops future polling/syncing for that address. It does **not** delete any emails already saved from that mailbox; that data stays in `messages`/`historical_emails` as-is.

### A related fix made alongside this

`/email/{email_id}/send` in `main.py` used to hardcode a 3-way lookup (`if source == "support@coralacademy.com": from_email = os.getenv("EMAIL_1") ...`) to figure out which address to send a reply from. That would have silently failed to reply for any mailbox added through Settings, since it wasn't one of the 3 hardcoded cases. Fixed to use `source` directly as the from-address, since `source` is always the real mailbox address for both core and Settings-added accounts alike.

---

## 📝 Important Note — Adding New Mailboxes

Adding a new mailbox only enables the app to read, monitor, and send from that email account. It does **not** automatically teach the AI how to answer new categories of questions that may arrive through that mailbox.

If a newly added mailbox serves a different purpose (for example, teacher communication rather than general customer support), the Knowledge Base and historical email library should also be reviewed and expanded to cover those topics. Otherwise, the AI may:

- respond that it does not have enough information,
- produce inconsistent replies,
- or have drafts blanked by the teacher-content safety checks if only teacher-facing documentation is retrieved.

For best results, ensure the Knowledge Base and representative historical emails are updated whenever a newly monitored mailbox introduces substantially different types of enquiries.

---

## 📋 File Reference

| File | Role |
|---|---|
| `gmail_auth.py` | Central Domain-Wide Delegation auth — `get_gmail_service(email)`, `imap_login(email)` |
| `database.py` | `CORE_EMAIL_ACCOUNTS`, `get_all_email_accounts()`, `add_email_account()`, `delete_email_account()` |
| `main.py` — `/settings`, `/settings/accounts/add`, `/settings/accounts/{id}/delete` | The page and its two actions |
| `templates/settings.html` | The Settings page itself |
| `templates/home.html` | Has the Settings card linking here |

---
