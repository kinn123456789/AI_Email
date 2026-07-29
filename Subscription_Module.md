# Subscription & Re-engagement Module — Full Documentation

*Reaching out automatically when a subscription is cancelled or a free trial runs out — without ever guessing who someone is.*

---

## 🌟 What This Module Does (Simple Version)

When a family's subscription is cancelled, or their free trial runs out without converting, this module **automatically notices** — no one has to go looking for these families manually. It quietly writes a personalized "we'd love to have you back" draft in the background, ahead of time, so that when a staff member opens it up, the email is already there, already sounds right, and just needs a quick read and a click to send.

---

## 🎬 Features

1. **Automatic Detection** — every minute, the latest cancelled subscriptions and expired free trials are pulled directly from Coral Academy's live records — nothing is entered by hand.
2. **Drafts Ready Before You Open Them** — a background job writes up to 5 win-back drafts every minute, so when staff open a row, the AI's suggestion is already sitting there.
3. **Personalized, But Safe** — the real names of the parent and child are hidden from the AI while it writes, then swapped back in afterward.
4. **Review, Edit, Send** — open any row, read or tweak the draft, and send it via Gmail.
5. **Dismiss & Restore** — rows that don't need a follow-up can be dismissed, and brought back later if that turns out to be the wrong call.
6. **Recent & All-Time Views** — a fast, always-warm 3-month view for daily use, plus a slower, on-demand full-history view.

---

## 🛠️ Technical Details

### Tables Used

*Confirmed by directly tracing the live code and querying the actual database schema (`information_schema.columns`, `to_regclass`) — not inferred from variable names or guessed.*

| Table | Source | What it's for |
|---|---|---|
| `Subscriptions` | Supabase (separate project, via `supabase_client.py`) | Which subscriptions were cancelled and when |
| `FreeTrialPass` | Supabase | Which free trials expired without converting |
| `Enrollments` → `Batches` → `Classes` | Supabase | Resolves a learner to their class name(s) for display |
| `Learners`, `Users` | Supabase | Learner/parent names |
| `EmailDeliveryStatus` | Supabase | Parent contact/email info |
| `SessionInteraction` | Supabase | Whether the learner actually attended sessions (used in the draft's context) |
| `subscription_cancel_dismissed` | Main app Postgres (`database.py`) | Rows staff have dismissed |
| `subscription_cancel_sent` | Main app Postgres | Record of every re-engagement email actually sent |
| `subscription_cancel_drafts` | Main app Postgres | Cached AI drafts, so opening a row is instant |

⚠️ Note: `subscription_cancel_dismissed`, `subscription_cancel_sent`, and `subscription_cancel_drafts` have no `CREATE TABLE` statement in any checked-in schema file — they're referenced only via raw `INSERT`/`SELECT` in `subscription_cancel.py`. Their schema isn't version-controlled anywhere in the repo, worth fixing for a future developer.

**No external Coral Academy REST API is involved anywhere in this module** — everything comes from these Supabase tables directly.

### Cache Logic (corrected — not daily)

- `refresh_subscription_cache()` runs **every 1 minute**, not daily.
- Most cycles are cheap: they only fetch+join rows that **changed** since the last cycle (`_fetch_subscriptions_and_trials(since=last_change_cutoff)`) and merge them into the existing cache.
- A full from-scratch rebuild (re-fetching the entire 3-month window) only happens periodically (every N cycles) or if the cache is empty — e.g., right after a restart/deploy.
- `prefetch_reengagement_drafts()` also runs every 1 minute, offset 20 seconds from the cache refresh (and sharing a lock with it) so the two never collide — picks up to 5 rows without a cached draft yet and generates one.
- **The 3-Month view** (`get_cancelled_subscriptions()`) just reads this pre-warmed cache — fast, since the scheduler already did the work.
- **The All-Time view** (`get_all_time_cancelled_subscriptions()`) is a completely separate, on-demand dataset — fetched with **no date limit** only when someone actually opens it, then held in its own short-lived cache so repeated clicks in the same session don't re-pay the full fetch. It is *not* proactively kept warm the way the 3-month view is.

### AI Drafting

- Model: `gpt-5-nano` via OpenRouter. The draft is built from row data (subscription type, sessions attended, cancelled vs. trial-expired) — not grounded in the Knowledge Base or historical sent emails.
- Real parent/learner names are replaced with placeholder tokens (`[PARENT_NAME]`, `[STUDENT_NAME]`) before the AI ever sees the prompt, then swapped back in locally afterward.
- Logged to `ai_logs` under category `"Reengagement"`. Falls back to a hardcoded template email if the AI call fails.
- **Placeholder-leak check** (fixed this session, previously an open gap): after the swap-back, the body is checked with `_PLACEHOLDER_LEAK_PATTERN` for any leftover bracketed placeholder-shaped text (not just the 2 exact tokens — catches wrong casing/spacing too). If one's still there, the draft is discarded and the safe hardcoded fallback template is used instead, logged with `error="Placeholder leak detected after swap-back; used fallback template"` — a leaked placeholder can no longer reach Send.

### Sending

`followup_email.py`'s `send_email()` — authenticates via Domain-Wide Delegation (`gmail_auth.get_gmail_service()`, no per-account OAuth token file), sends via the Gmail API, logs the send into `subscription_cancel_sent`.

---

## 📋 File Reference

| File | Role |
|---|---|
| `subscription_cancel.py` | Refreshes the cancelled/expired list, pre-writes AI drafts |
| `followup_email.py` | Sends the finished re-engagement email via Gmail |
| `supabase_client.py` | Connects to the Supabase tables this module reads from |
| `templates/subscription_cancel*.html` | Dashboard, trash, and sent-history views |

---
