# ✉️ Email Module — Full Documentation

*A simple guide to what the Email module does, and how it works under the hood.*

---

## 🌟 What This Module Does (Simple Version)

Coral Academy gets emails from parents every day — questions about classes, billing, admissions, and more. This module reads every email that comes in, figures out what it's about, writes a suggested reply using AI, and lets a staff member check it and send it (or fix it first).

 It like having an assistant who reads every email, sorts it into the right pile, drafts a reply for you, and hands it to you to approve — so you never have to start from a blank page.

---

## 🎬 Features (What You Can Show in a Demo)

### 1. 📥 The Inbox Dashboard
- One page shows every email that's come in — sender, subject, category, priority, and whether it still needs a reply.
- Search by keyword, filter by status or category, and page through results.
- The list refreshes itself every few seconds automatically, so new emails just appear — no need to hit refresh.
- Click any email to open it and see the full conversation.

### 2. 🧠 Automatic Sorting (AI Classification)
- Every email is automatically read by AI and sorted into a category: **Admissions**, **Billing**, **Teacher**, **General**, or flagged **Urgent**.
- The AI also decides: does this need a reply at all? Can AI safely draft one, or does a human need to handle it directly (e.g. complaints, refunds, legal concerns, anything sensitive)?
- A confidence score is shown — if the AI isn't confident, it flags the email for a human to look at more carefully.

### 3. ✍️ AI-Written Draft Replies
- For most emails, the AI writes a full suggested reply — ready to review and send.
- The AI is only allowed to state facts it can actually confirm — from Coral Academy's real Help Center articles, real class information, or (carefully) from patterns in real past staff replies. It's never allowed to guess or make things up.
- If it genuinely doesn't know the answer, it says so honestly instead of guessing — and it's not allowed to promise "someone will follow up," since that's not something it can guarantee.
- Replies always open with the right greeting (using the customer's name if we know it) and close with the correct signature for whichever mailbox is replying (Support, Lucy, etc.) — never mixed up.
- It knows not to pile on extra unrequested suggestions ("would you like me to also...") — it just answers what was actually asked.

### 4. 📤 Sending Replies
- Staff reviews the AI draft (or writes their own), edits if needed, and hits **Send**.
- Replies can now include file attachments.
- Replies are automatically threaded correctly, so they show up as part of the same email conversation in the customer's inbox — not as a brand-new email.

### 5. 📝 Compose (New Emails & Bulk Sending)
- Write a brand-new email to one person, or send the same message to up to 100 people at once.
- Bulk recipients can be typed in, uploaded as a CSV file, or pasted directly.
- Each recipient's name can be personalized automatically using `{{name}}` in the subject/body.
- Bulk sends happen in the background, so the page responds instantly instead of making you wait for 100 emails to go out one by one.
- A separate **Sent History** page shows everything sent this way, with search and date filters.

### 6. 🔄 Keeping Sent Mail in Sync
- If a staff member replies directly from Gmail itself (not through this app), the system automatically notices and pulls that reply in within the hour, so the conversation stays complete either way.
- There's also a manual "Sync Gmail Sent" button on any email for an instant check.

### 7. 🚫 Filtering Out Junk Automatically
- System notifications, password resets, newsletters, and similar automated emails are automatically recognized and kept out of the main inbox — so staff only sees emails that actually need attention.
- These filtering rules are stored in the database and can be adjusted without changing any code.

### 8. ⚡ Real-Time Email Reading
- New emails are picked up the moment they arrive (via Gmail's real-time notification system), with a backup check every 5 minutes just in case anything was missed.

### 9. 📎 Attachments
- Incoming attachments are saved and can be downloaded from the email view.
- Outgoing attachments are supported on both replies and Compose.

### 10. 🗑️ Trash & Restore
- Emails can be moved to Trash and restored back to their original folder if needed.

### 11. 📚 Learning Coral Academy's Writing Style
- Every real reply sent by staff is saved into a "style library" that future AI drafts learn from — so replies sound like they were actually written by the Coral Academy team.
- Before anything is saved into this library, personal details (email addresses, phone numbers) are automatically removed for privacy. Old entries are automatically cleaned up after 18 months.

### 12. 📊 AI Insights (Behind-the-Scenes Visibility)
- A dedicated page shows how the AI is performing: how many replies it's generated, how many errors happened, how many tokens (AI "words") were used, and how long replies took to generate.
- Any specific email's AI activity can be looked up directly — useful for understanding why a particular reply came out a certain way.

### 13. 🌍 Everyone Sees Their Own Time
- All dates and times are shown in whatever timezone the person viewing the page is actually in — not a fixed company timezone.

---

## 🛠️ Technical Details 

### The Core Pipeline

**`process_email.py`** — the main entry point for every incoming email. For each one, it:
1. Checks it isn't a duplicate — keyed on the email's own Message-ID header (`email_exists(message_id, ...)`)
2. Finds the parent message for threading — first via `In-Reply-To`, then falling back to walking the `References` header (needed because some mail clients send `References` without `In-Reply-To`; without this fallback those replies used to start a disconnected new thread instead of joining the real one). If no parent is found either way, the message isn't an orphan — its own Message-ID becomes the `thread_id`, anchoring a brand-new thread that later replies can attach to
3. Runs classification and content-retrieval **in parallel** (via `ThreadPoolExecutor`) for speed:
   - `ai_classifier.py` → category, priority, whether a reply is needed
   - `vector_search.py` → similar past emails (style examples)
   - `knowledge_search.py` → relevant Help Center / Class Knowledge content
   - Each of the two embedding lookups gets its own isolated embedding client (`new_embedding_client()`/`close_embedding_client()`) rather than sharing one — the shared default client isn't safe to call from two threads at once, so each concurrent lookup needs its own
4. Reranks the retrieved similar emails (`rag_reranker.py`) to keep only the genuinely relevant ones, dropping ones that only matched loosely
5. Calls `reply_generator.py` to draft the reply
6. Saves everything to the database (`database.py`)

*Contact Form enquiries branch off this same pipeline but are their own module from there — see the dedicated Contact Form Module document.*

**`ai_classifier.py`** — `ai_triage()` sends the subject/body to `gpt-5-nano` and gets back category, priority, a one-line summary, a confidence score, and whether AI can safely draft a reply or needs a human. A few rules are hardcoded in Python on top of the AI's own judgment (e.g., Teacher Portal notifications are always forced to category "Teacher"; certain sensitive keywords like "complaint," "refund," or "legal" always force human review, regardless of what the AI decided). **This step is now logged to `ai_logs`** (category `"Classification"`) — previously only the reply-drafting step was logged, so a wrong classification had no visible trail at all.

**`reply_generator.py`** + **`prompt_builder.py`** — the actual reply-writing step. `prompt_builder.py` holds the entire rulebook the AI follows — this grew substantially over this project:
- **Source priority**: Current Email > Knowledge Base > Historical Emails (and historical emails only count if 2–3 of them clearly agree *and* don't contradict the Knowledge Base — a single example is never enough)
- **Question-type routing**: Pricing/Refund/Policy/Schedule questions must come from the Knowledge Base only, never historical emails, no matter how consistent they look
- **Audience checks**: some Knowledge Base articles and historical emails are written for teachers/staff, not parents — the AI checks who content was actually written for before using it, so teacher-facing process details (like internal coordination emails) don't leak into a parent's reply
- **Plan-specific accuracy**: Pay Per Class and Coral Unlimited have different rules (e.g. only Coral Unlimited has a pause feature); the AI won't blend one plan's specific mechanics into an answer about the other
- **Date-aware reasoning**: the email's actual received date is given to the AI so it can correctly reason about "before/after" timing questions (e.g. refund eligibility) instead of guessing
- **Tone rules**: genuine apology only when something actually went wrong, always closes with thanks, never over-apologizes for routine questions, direct answers stay polite rather than blunt
- **Signature/greeting**: matched to the actual sending account (support@/lucy@/engineering@), with the customer's name if it's on file, otherwise a plain "Hi,"
- **Safety**: never invents policies/pricing/schedules, never claims an action was completed unless it genuinely was (the one exception: subscription cancellations, where staff has already processed it before the reply is sent)
- **Prompt-injection guard**: the customer's email is explicitly treated as data to respond to, never as instructions to follow — protects against emails trying to make the AI ignore its own rules

Every reply-generation call is logged to **`ai_logs`** via `ai_logger.py` — model used, tokens, response time, which Knowledge Base articles/historical examples were used, and the full error if something failed. `save_ai_log()` itself can never crash the calling function even if the log write fails — logging failures are caught and printed, never re-raised.

### Email Filtering

**`email_filter.py`** — `is_automated_email()` runs before AI ever sees an email. Checks (in order): headers like `Auto-Submitted`/`List-Unsubscribe`, known automated sender addresses/domains (hardcoded), then **database-driven rules** (`email_filter_rules` table — sender/domain/subject/body keyword rules, editable without a code change). One real bug found and fixed this project: overly broad subject rules ("payment", "subscription", "renewed") were catching genuine customer emails whose subject happened to contain those very common words — replaced with narrower, exact-phrase rules ("subscription renewed successfully", "subscription cancelled:") that only match real automated system messages.

### Real-Time Ingestion

**`gmail_watch.py`** — registers/renews Gmail push notification subscriptions (`users.watch`), renewed daily since Google requires re-registration periodically.
**`gmail_history.py`** — when a push notification arrives, fetches exactly what changed since the last known point (`historyId`), rather than re-scanning the whole mailbox.
**`email_reader.py`** — the polling backup (every 5 minutes), for anything a push notification might have missed. Handles both the "process all mailboxes" scheduled run and per-mailbox webhook-triggered runs, with a lock so overlapping runs queue instead of colliding.

### Sending

**`email_sender.py`** — sends replies (threading via `In-Reply-To`/`References` headers so Gmail groups them correctly), now supports attachments.
**`compose_email_sender.py`** — sends new/bulk emails from Compose, supports attachments via multipart MIME.
**`save_composed_email.py`** — persists what Compose actually sent (recipient, subject, body, attachment flag) for the Sent History page.

### Sent-Mail Sync (the most heavily reworked piece this project)

**`sync_sent_gmail.py`** — runs hourly, pulls in anything sent directly from Gmail (not through this app). Originally used a hardcoded date and a "last 50" slice — both replaced with a **real checkpoint**: only advances past messages it's actually confirmed handled, tracked in a `sync_log` table. Key correctness details:
- If a backlog ever exceeds the per-run safety cap (500 messages), the checkpoint advances only to the oldest message actually processed this run — not to "now" — so the next run picks up exactly where this one stopped, instead of silently skipping the untouched older messages forever.
- If some messages in a run fail but others succeed, the checkpoint advances to the newest *successfully* handled message — so one bad message can no longer block every future run indefinitely.
- Failed messages get **one bounded automatic retry** (tracked in `sync_failed_messages`, relocated by Message-ID since IMAP sequence numbers aren't stable across time) — if it fails twice, it's left for manual review rather than retried forever.

### Knowledge & Style Pipeline

**`vector_search.py`** — finds similar past emails by meaning (embeddings), not just keyword matching.
**`knowledge_search.py`** — same idea, but against the Help Center / Class Knowledge content.
**`learn_email_style.py`** — pulls real sent emails into the historical-style library, with PII (emails/phone numbers) automatically redacted before storage.
**`embed_classes.py` / `sync_classes.py`** — keeps Class Knowledge in sync with Coral Academy's real live class catalog (pulled directly from `api.coralacademy.com`).
**`embed_knowledge_base.py` / `sync_help_center.py`** (via `refresh_knowledge_base.py`) — keeps Help Center content in sync and embedded for search.
**`historical_email_redaction.py`** — the redaction logic itself (email/phone regex masking, applied both going-forward and in the one-time retroactive backfill of the existing historical archive).

### Scheduling & Reliability

**`scheduler.py`** — runs every background job (sent-mail sync hourly, class/knowledge refresh daily, email reader every 5 min, etc.) with staggered timing so heavy jobs never collide in the same moment (a past cause of an out-of-memory crash). **Every scheduled job now logs its success/failure durably to `sync_log`** via a shared `_run_logged_job()` helper — previously only the sent-mail sync did this; everything else was only visible as `print()` output that vanished whenever Render's log viewer rotated it out.

**`main.py`** — also has a global exception handler that logs any unhandled error from a live request, and background tasks (bulk sends, the Gmail push-notification handler, saving a reply into the style library) are wrapped with the same logging helper — background tasks run *after* the response is sent, so a global request-level exception handler alone can't see their errors; this closes that gap specifically.

### Database

**`database.py`** — the data layer for everything above: `messages` (every email, its AI draft, category, status, mailbox), `attachments`, `historical_emails` (18-month retention, auto-pruned), `ai_logs`, `sync_log`, `sync_failed_messages`, `email_filter_rules`, `knowledge_base`, `classes`.

---

## 📋 Quick Reference — All Files in This Module

| File | Role |
|---|---|
| `process_email.py` | Main ingestion pipeline for every incoming email |
| `ai_classifier.py` | Classifies category/priority/reply-safety |
| `reply_generator.py` | Generates the AI draft reply |
| `prompt_builder.py` | The full rulebook the AI follows when writing replies |
| `ai_logger.py` | Logs every AI call (classification + reply generation) |
| `email_filter.py` | Filters out automated/junk emails before AI sees them |
| `email_reader.py` | Polling + webhook-triggered email reading |
| `gmail_watch.py` | Registers/renews Gmail push notifications |
| `gmail_history.py` | Fetches what changed since the last notification |
| `gmail_message.py` / `gmail_fetch.py` | Gmail message lookup helpers |
| `email_sender.py` | Sends replies (with threading + attachments) |
| `compose_email_sender.py` | Sends new/bulk emails from Compose |
| `save_composed_email.py` | Records what Compose sent |
| `sync_sent_gmail.py` | Hourly sync of directly-sent Gmail replies, with checkpoint + retry |
| `emails_cleaner.py` | Strips quoted reply history from email bodies |
| `vector_search.py` | Finds similar past emails by meaning |
| `rag_reranker.py` | Filters retrieved historical emails down to the genuinely relevant ones |
| `embedding_service.py` | Creates/closes the embedding client used for meaning-based search |
| `knowledge_search.py` | Finds relevant Help Center / Class content |
| `learn_email_style.py` | Builds the historical-style library, with PII redaction |
| `historical_email_redaction.py` | The redaction logic itself |
| `sync_classes.py` / `embed_classes.py` | Keeps Class Knowledge in sync with the real class catalog |
| `sync_help_center.py` / `embed_knowledge_base.py` / `refresh_knowledge_base.py` | Keeps Help Center content in sync |
| `scheduler.py` | Runs and logs all background jobs |
| `database.py` | All database access |
| `main.py` | Routes, background task handling, global error logging |

---

*Document generated as part of project handover — covers the Email module as of this session's changes.*
