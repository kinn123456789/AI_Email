# ✉️ Email Module — Full Documentation

*A simple document on what the Email module does, and how it works under the hood.*

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
   - Each of the two embedding lookups gets its own isolated embedding client (`new_embedding_client()`/`close_embedding_client()`) rather than sharing one — the shared default client isn't safe to call from two threads at once. This covers two separate concurrency cases with the same fix: the 2 parallel lookups *within* processing one email, **and** two different emails (e.g. from different mailboxes) being processed at the same time — each call to `process_email()` creates and closes its own fresh clients, so nothing is ever shared across threads either way
4. Reranks the retrieved similar emails (`rag_reranker.py`) to keep only the genuinely relevant ones, dropping ones that only matched loosely
5. Calls `reply_generator.py` to draft the reply
6. Saves everything to the database (`database.py`)

*Contact Form enquiries branch off this same pipeline but are their own module from there — see the dedicated Contact Form Module document.*

**`ai_classifier.py`** — `ai_triage()` sends the subject/body to `gpt-5-nano` and gets back category, priority, a one-line summary, a confidence score, and whether AI can safely draft a reply or needs a human. A few rules are hardcoded in Python on top of the AI's own judgment: Teacher Portal notifications are always forced to category "Teacher"; a fixed keyword list (`complaint`, `refund`, `legal`, `lawyer`, `sue`, `waiver`, `scholarship`, `bullying`, `harassment`, `teacher behaviour/behavior`) sets `requires_review=True` and `reply_type="human"` (lines 393–430). **In practice, every single email already sits in a human-reviewed queue before it can be sent — there's no code path that auto-sends anything** — so `requires_review`/`reply_type` don't currently change what staff sees (neither field is rendered in any template right now). The one override with a real, visible effect is that these keywords also bump `priority` up to "High" if it was Low/Medium, which *does* show as a colored badge on the dashboard. **This step is now logged to `ai_logs`** (category `"Classification"`) — previously only the reply-drafting step was logged, so a wrong classification had no visible trail at all.

**`reply_generator.py`** + **`prompt_builder.py`** — the actual reply-writing step. There are two parallel retrieval pipelines feeding into it (verified against the actual retrieval code, not assumed):

```
Knowledge Base path:
Email → Embedding → pgvector search → Top 5 articles ────────────┐
                                                                    ├──→ LLM → Draft Reply
Historical Emails path:
Email → Embedding → pgvector search → Top 30 candidates → LLM Reranker → ~2-3 selected examples ──┘
```

Knowledge Base articles go straight from vector search into the prompt (top 5, no reranking step). Historical emails get a wider net (top 30 by similarity) specifically *because* they then go through a second LLM pass that re-judges them for genuine relevance and writing-style fit — similarity score alone isn't trusted to pick the final examples.

`prompt_builder.py` holds the entire rulebook the AI follows for writing the actual reply — this grew substantially over this project:
- **Source priority**: Current Email > Knowledge Base > Historical Emails (and historical emails only count if 2–3 of them clearly agree *and* don't contradict the Knowledge Base — a single example is never enough)
- **Question-type routing (changed this session, then simplified)**: previously, Pricing/Refund/Policy/Schedule questions could *only* come from the Knowledge Base — historical emails were never checked for these, even if the Knowledge Base had nothing. That blanket restriction was deliberately relaxed so every question type checks the Knowledge Base first, with historical emails allowed to fill a gap under the same strict conditions as before (3–5 similar examples, at least 2-3 agreeing, no contradiction, genuinely parent-facing). Once that changed, the old 6-way classification (Policy/Pricing/Refund/Schedule/Operational/General) no longer actually branched to different behavior — 5 of those 6 categories became identical in practice. So it's now simplified to the one distinction that still matters: **Account-specific** (a question about this specific customer's own account/enrollment, which the AI was never given — ask for the detail or admit it doesn't know) vs. **everything else** (Knowledge Base first, historical fallback as above).
- If historical emails exist for a gap the Knowledge Base left open, but they're inconsistent, contradictory, or low-confidence, the reply falls back to the same honest "I don't have enough information" non-answer as when nothing at all is available — a dedicated human-review escalation for this specific case was tried and then reverted this session, since every email already sits in a human-reviewed queue before anything is sent (no code path auto-sends without a person clicking Send), so the extra flag added no real behavioral difference.
- **Audience checks**: some Knowledge Base articles and historical emails are written for teachers/staff, not parents — the AI checks who content was actually written for before using it, so teacher-facing process details (like internal coordination emails) don't leak into a parent's reply
- **Plan-specific accuracy**: Pay Per Class and Coral Unlimited have different rules (e.g. only Coral Unlimited has a pause feature); the AI won't blend one plan's specific mechanics into an answer about the other
- **Date-aware reasoning**: the email's actual received date is given to the AI so it can correctly reason about "before/after" timing questions (e.g. refund eligibility) instead of guessing — written in `prompt_builder.py`'s "DATE REASONING" section (~line 569), fed by the `date_received` value computed from the real `email_date` (~line 791), not the current server time
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
- The checkpoint itself is just **one saved timestamp** per mailbox (in `sync_log.finished_at`) — nothing fancier than "the last time we know for sure we made real progress, was this exact moment." Each run reads that one value back, uses it as its starting point, and (if it made progress) writes a new one when it finishes. It is deliberately **not** a Message-ID — those aren't ordered, so they can't tell you "how far along" a sync is; a timestamp can.
- **The 500-message safety cap, in plain terms:** imagine the sync job checks a mailbox every hour — almost always there are just a few new sent emails. But suppose it broke for two weeks; now there might be 2,000 emails waiting. The cap exists so one single run can't try to swallow all 2,000 at once (slow, or could crash). So it takes a bite of at most 500 and is supposed to remember where it left off, so it can come back for the rest next time. **Worst case, and how rare it is:** this only ever matters if a mailbox's backlog genuinely exceeds 500 unsynced messages in one go — at normal hourly-checked volume that basically never happens; it would take something like the sync being broken for an extended stretch. When it *is* used, the run only ever processes **at most 500 messages, never more** — the cap is a hard ceiling, not a target.
- ⚠️ **Known issue, found while verifying this:** the current code takes the *last* 500 IDs from IMAP's search results. Confirmed live against a real mailbox that these results come back oldest-first — so "last 500" is actually **the newest 500**, the opposite of what's intended (it should grab the oldest 500, so the checkpoint crawls forward through the backlog from the beginning). This only matters in that same rare "backlog exceeded 500" case, but when it does happen, it currently risks permanently skipping the truly old messages instead of catching up on them. Flagged for a fix, not yet applied.
- If some messages in a run fail but others succeed, the checkpoint advances to the newest *successfully* handled message — so one bad message can no longer block every future run indefinitely.
- Failed messages get **one bounded automatic retry** (tracked in `sync_failed_messages`, relocated by Message-ID since IMAP sequence numbers aren't stable across time) — if it fails twice, it's left for manual review. In code: `sync_sent_gmail.py`'s `_retry_pending_failures()` runs the automatic pass every sync cycle, and `retry_one_now(row_id)` powers the manual "Retry Now" button; both share the same relocate-by-Message-ID + `_process_sent_message()` logic. The database side (`save_failed_sync_message`, `get_failed_sync_messages`, `mark_failed_message_resolved`, `mark_failed_message_exhausted`) lives in `database.py`. There's now a small manual-review panel for this right on the main dashboard (above the inbox table), with one-click "Retry Now" / "Delete" per message — the routes are `main.py`'s `/dashboard/failed-sync/{row_id}/retry` and `/delete`.

### Knowledge & Style Pipeline

**`vector_search.py`** — finds similar past emails by meaning (embeddings), not just keyword matching.
**`knowledge_search.py`** — same idea, but against the Help Center / Class Knowledge content.
**`learn_email_style.py`** — pulls real sent emails into the historical-style library, with PII (emails/phone numbers) automatically redacted before storage. This is *additive*, not the only source of style: `prompt_builder.py`'s "WRITING STYLE" section (a fixed baseline — short paragraphs, no corporate language, apologize only when something genuinely went wrong, always close with thanks, etc.) applies to every single reply regardless of whether any historical examples were found; the 2-3 selected historical examples (when available) layer on top of that baseline as extra style reference, they don't replace it.
**`embed_classes.py` / `sync_classes.py`** — keeps Class Knowledge in sync with Coral Academy's real live class catalog (pulled directly from `api.coralacademy.com`).
**`embed_knowledge_base.py` / `sync_help_center.py`** (via `refresh_knowledge_base.py`) — keeps Help Center content in sync and embedded for search.
**`historical_email_redaction.py`** — the redaction logic itself (email/phone regex masking, applied both going-forward and in the one-time retroactive backfill of the existing historical archive).

### Scheduling & Reliability

**`scheduler.py`** — runs every background job (sent-mail sync hourly, class/knowledge refresh daily, email reader every 5 min, etc.) with staggered timing so heavy jobs never collide in the same moment (a past cause of an out-of-memory crash). **Every scheduled job now logs its success/failure durably to `sync_log`** via a shared `_run_logged_job()` helper — previously only the sent-mail sync did this; everything else was only visible as `print()` output that vanished whenever Render's log viewer rotated it out.

**`main.py`** — also has a global exception handler that logs any unhandled error from a live request, and background tasks (bulk sends, the Gmail push-notification handler, saving a reply into the style library) are wrapped with the same logging helper — background tasks run *after* the response is sent, so a global request-level exception handler alone can't see their errors; this closes that gap specifically.

### How Errors Are Handled

There isn't one single error-logging system — there are four, each covering a different *kind* of code, because each kind fails in a different way and needs a different safety net:

| Where the code runs | What catches a failure | Where it's visible |
|---|---|---|
| An AI call (classification or reply drafting) | Its own internal try/except, in `ai_classifier.py` / `reply_generator.py` | `ai_logs` table → AI Insights page |
| A scheduled job (`scheduler.py`, runs on a timer) | `_run_logged_job()` wrapper — never lets a job's exception kill the scheduler | `sync_log` table → *no dashboard yet* (direct query only) |
| A live web request (someone loading a page or clicking a button) | The global `@app.exception_handler(Exception)` in `main.py` | A local log file (`logs/app.log`) + stdout — **not** the database |
| A background task (work that continues after the page has already responded — bulk sends, saving a reply into the style library, the push-notification handler) | Individually wrapped, on a case-by-case basis, in `_run_logged_job()` | `sync_log` table (same as scheduled jobs) |

The important nuance: the global exception handler is scoped to *live requests only* — by the time a background task runs, the response has already been sent and that handler is no longer in the call stack, so it structurally cannot see background-task errors no matter what. That's why background tasks need their own, separate wrapping rather than being automatically covered. As of this session, every `background_tasks.add_task(...)` call in the app is accounted for: three are explicitly wrapped, and the fourth (`sync_sent_gmail.main`) already does its own internal logging to `sync_log`, so nothing currently runs unprotected — but any *new* background task added later would need the same wrapping applied deliberately, since it doesn't happen automatically.

Also worth knowing: the exception-handler log file lives on the server's local disk, which typically doesn't survive a deploy/restart — so it's only reliable for catching something *during* the current running session, not as a permanent record. `ai_logs` and `sync_log`, being in the database, are the durable ones.

### How the App Stays Fast (Background Work & Concurrency)

A few different techniques are used, for different reasons:

| Mechanism | Where | What it's for |
|---|---|---|
| `ThreadPoolExecutor` (3 workers) | `process_email.py` | Classification + similar-email search + Knowledge Base search run **simultaneously** for one incoming email — the biggest speed win in the pipeline, since an email finishes in roughly the time of the *slowest* of the three instead of the sum of all three |
| Per-thread isolated clients | `embedding_service.py`'s `new_embedding_client()`, `supabase_client.py` | Each concurrent thread gets its own client instead of sharing one — a shared client isn't thread-safe (root cause of two real bugs fixed this session) |
| One-time single-threaded warm-up | `ai_classifier.py` | Forces the OpenAI SDK's lazy imports to finish before any concurrent thread can race on them (this session's import-deadlock fix) |
| FastAPI `BackgroundTasks` | `main.py` — 4 total call sites | Work that continues *after* the page has already responded: `sync_sent_gmail.main` (after a manual reply), saving a reply into the style library, reacting to a Gmail push notification, sending a bulk batch |
| APScheduler background jobs | `scheduler.py` | Independent timers, not tied to any request: email polling (5 min), Teacher Portal sync (8 min), sent-mail sync (hourly), subscription cache + draft prefetch (1 min, offset so they never overlap each other), trial follow-ups (daily 9am), class/knowledge refresh, Gmail watch renewal — each staggered so heavy ones don't collide, and each capped at one running instance at a time |
| On-demand routes (`/sync-teacher`, `/sync-sent/{id}`) | `main.py` | *Under review — see note below.* These are simply buttons: instead of waiting 8 minutes (Teacher sync) or an hour (Sent-Mail sync) for the next scheduled run, a user clicks "Sync Now" and the exact same sync logic runs immediately. |

The common thread across all of these: never make a person wait for something that doesn't need to happen before they can move on, and never let two things that aren't safe to run together actually run together.

> **Note on the on-demand routes:** these were flagged as unexpected/unwanted during this session — the intent is for everything to run purely on the scheduler, with no manual trigger needed. Whether to remove `/sync-teacher` and `/sync-sent/{id}` entirely (since their scheduled equivalents already run independently regardless of whether anyone clicks them) is a pending decision — not yet acted on.

### How Speed Was Increased — Beyond Just Concurrency

Running things at the same time (above) is one lever. The other is simply **doing less work in the first place**. Several places in the app were changed this way, each for a real, concrete reason:

| Technique | Where | Why it mattered |
|---|---|---|
| Incremental cache refresh instead of full rebuild | Subscription cache (`subscription_cancel.py`), refreshed every 1 minute | Most cycles now only fetch+join rows that **changed since the last cycle** (tracked via a saved timestamp, `last_change_cutoff`) instead of re-fetching the entire 3-month window every single time. This was a real fix for repeated out-of-memory crashes on Render's 512Mi tier — the old full-rebuild-every-60-seconds approach was expensive enough to contribute to them. |
| Time-boxed, on-demand-only caching | Subscription All-Time view | Never proactively refreshed (unlike the 3-month view) — only fetched when someone actually clicks it, then held briefly so repeated clicks in the same session don't re-pay the full-history fetch cost. |
| Partial JS refresh instead of full page reload | Dashboard (`templates/dashboard.html`) | `setInterval(refreshDashboard, 8000)` calls a lightweight `/dashboard-data` route and swaps just the table body — not a full page reload every 8 seconds. |
| Narrowing before the expensive step | Historical-email retrieval (`vector_search.py` → `rag_reranker.py`) | Casts a wide net cheaply first (pgvector similarity search, top 30), then only sends the reranker's chosen ~2-3 into the final reply-writing prompt — keeps the expensive, per-reply LLM call's prompt small instead of stuffing it with 30 candidates. |
| Hard cap on prompt size | Teacher Portal thread history (`teacher_ai_processor1.py`) | Capped at the last 50 messages specifically because one real conversation grew past OpenRouter's 400,000-token limit and started failing on every attempt, permanently, since it could only keep growing. |
| Do the expensive thing once, not per-request | OpenAI client warm-up (`ai_classifier.py`) | The lazy-import fix from this session doubles as a speed detail — without it, the *first* concurrent request after a restart would pay an extra, unpredictable cost (or hit the deadlock) that every later request wouldn't. |

### Database

**`database.py`** — the data layer for everything above: `messages` (every email, its AI draft, category, status, mailbox), `attachments`, `historical_emails` (18-month retention, auto-pruned), `ai_logs`, `sync_log`, `sync_failed_messages`, `email_filter_rules`, `knowledge_base`, `classes`.

---

## 💡 Possible Future Enhancement: Manageable Email Accounts

Right now the three monitored mailboxes (support@/lucy@/engineering@coralacademy.com) are hardcoded — each `EMAIL_ACCOUNTS` list, repeated across `email_reader.py`, `sync_sent_gmail.py`, and `learn_email_style.py`, plus the `EMAIL_1`/`EMAIL_2`/`EMAIL_3` env vars. Adding or removing a mailbox today means editing code and redeploying.

A simple settings-page design for this, if it's ever wanted:

```
Settings
   ↓
Email Accounts
------------------------------------
Email Address            Status
admin@company.com        Active
sales@company.com        Active
hr@company.com           Active

[ + Add Email ]
```

**Add Email flow**: admin clicks "+ Add Email" → enters the address → it's saved to a new `email_accounts` table (address, status, added_at) → the app starts polling/watching it the next scheduler cycle, no restart needed. A "Delete" action would stop polling that mailbox and mark it inactive (not necessarily drop its historical data).

**Why this is now realistic to build, and wasn't before**: this session's migration to Domain-Wide Delegation (`service-account.json`, see `gmail_auth.py`) means a brand-new mailbox needs *no separate OAuth consent flow* — any `@coralacademy.com` address the service account is allowed to impersonate just works the moment it's added, since `gmail_auth.get_gmail_service(email)`/`imap_login(email)` take a plain email address. Under the old per-account token-file system, adding a mailbox meant a manual one-time consent flow (`generate_oauthtoken.py`) per address — this UI wouldn't have been practical to build before the migration.

This is a proposal, not implemented — the hardcoded `EMAIL_ACCOUNTS` lists would need consolidating into one shared source (the new table) before a Settings page could manage them.

---

## 📖 Terms You'll See in This Doc

**`email_date` vs `created_at`** — two different timestamps stored on every message, easy to mix up:
- `email_date` is the *real* date the email was actually sent/received — taken straight from the email's own `Date:` header. This is the one used for anything that needs to reason about "when did this actually happen" (sorting, refund-timing rules, etc.).
- `created_at` is simply *when our own database inserted the row* — normally that's within a second or two of the email arriving, so the two usually match closely. They can genuinely differ, though — for example, during a one-time historical backfill, `created_at` would be "whenever the backfill ran," while `email_date` still correctly reflects the email's real original date.

**`ai_logs` table vs. the exception-handler's log file** — these are easy to conflate since both are "logs," but they're not related:
- `ai_logs` is a real database table, specifically for AI calls (classification + reply drafting) — tokens used, model, category, any error. Durable, queryable, and it's what powers the AI Insights page.
- The global exception handler (for errors during a live page load/click) is a completely separate thing — it writes to a plain text file (`logs/app.log`) using Python's standard logging, not the database. There's no table backing it today, and since it's a local file, it typically doesn't survive a deploy/restart. It *could* be upgraded to also write into a database table (similar to how `sync_log` works for scheduled jobs) if durable request-error history becomes important — just not built yet.

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
