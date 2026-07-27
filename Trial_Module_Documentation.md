# 🌱 Trial Follow-Up Module — Full Documentation

*A gentle 3-email nurture sequence for families whose free trial just ended — always AI-drafted, never auto-sent.*

---

## 🌟 What This Module Does (Simple Version)

When a family's free trial ends without them enrolling, this module reaches back out — automatically, but never impulsively. Once a day, it checks who expired that day, writes a warm, personalized email with AI, and quietly saves it as a **draft**. Nothing goes out to a real family until a staff member actually opens it, reads it, and clicks Send.

---

## 🎬 Features

1. **Automatic Daily Check** — once a day, every free trial that expired that day is found automatically.
2. **AI-Written, Human-Sent** — each email is drafted by AI, but always waits for a staff member's review and click.
3. **Smart Enough to Stop** — if a family already enrolled after their trial, the sequence recognizes that and doesn't keep nudging them.
4. **Dedicated Dashboard** — see every draft, what's due, reply to responses, review completed campaigns.
5. **Trash & Restore** — drafts that shouldn't go out can be trashed, and brought back later if needed.

## The 3-Email Sequence (timed from the trial's real expiry date)

| Day | Tone |
|---|---|
| Day 1 | Thank-you for trying the trial |
| Day 3 | Nudge to continue the learning journey (only sent if Day 1 already went out) |
| Day 7 | Last reminder (only sent if Days 1 and 3 already went out; marks the sequence complete either way) |

---

## 🛠️ Technical Details

### Tables Used

*Confirmed by directly tracing the live code and querying the actual database schema (`information_schema.columns`, `to_regclass`) — not inferred from variable names or guessed.*

| Table | Source | What it's for |
|---|---|---|
| `FreeTrialPass` | Supabase | Trials that expired "today" (filtered by `expiry_at`) |
| `Enrollments` | Supabase | Resolves a trial to its `learner_id` |
| `Subscriptions` | Supabase | Used to exclude learners who already converted to a paid subscription after their trial started |
| `Users` | Supabase | Learner/parent names |
| Class titles lookup (shared with the Subscription module, from `subscription_cancel.py`) | Supabase | Resolves a learner to their class name |
| `trial_followup_campaigns` | Main app Postgres (`database.py`) | Tracks each candidate's own progress — `email1_sent_at`, `email2_sent_at`, `email3_sent_at`, `status` — created the first time a candidate is seen |

**No external Coral Academy REST API is involved** — candidates are pulled from these Supabase tables, same as the Subscription module.

### Cadence & Candidate Logic

Runs once a day, **9:00 AM** (`scheduler.py`, `CronTrigger(hour=9, minute=0)`), confirmed directly in the scheduler registration:
```python
scheduler.add_job(
    run_trial_followups,
    CronTrigger(hour=9, minute=0),
    id="trial_followups",
    ...
)
```

Based on `trial_expiry_at` compared to "now":
- **Email 1**: sent once ≥1 day since trial expired, and email 1 not yet sent.
- **Email 2**: sent once ≥3 days since expiry, and email 1 sent but email 2 not.
- **Email 3**: sent once ≥7 days since expiry, and emails 1 & 2 sent but email 3 not — also marks the campaign completed.

### AI Drafting

- Model: `gpt-5-nano` via OpenRouter (`followup_ai.py`). Each of the 3 emails has its own separately written prompt matching its day's tone.
- Same name-hiding technique as the Subscription module: the AI only ever sees `[PARENT_NAME]`/`[STUDENT_NAME]` placeholders while writing; real names are swapped back in afterward.
- Logged to `ai_logs` under category `"Trial Followup"`. Falls back to a hardcoded template on AI failure.
- ⚠️ **Known gap**: same as Subscription — no verification that the placeholder swap-back actually worked before a draft is shown to staff. Still open.

### Draft-First By Design

Sending is deliberately not automatic anywhere in this flow — the actual Gmail send call in `process_trial_followup.py` is intentionally commented out; every generated email is saved with `status="draft"` first. The real send only happens when a staff member clicks Send from the `/trial-followup` dashboard, via `followup_email.py`.

### Cleanup Note

Two old files in this area — `trial_followup_scheduler.py` (an earlier standalone scheduler prototype, not actually running) and `trial_email_sender.py` (an unused duplicate of the live sending code) — are not used by the running app and are safe candidates for removal.

---

## 📋 File Reference

| File | Role |
|---|---|
| `process_trial_followup.py` | Runs daily, finds due candidates, saves drafts |
| `followup_ai.py` | Writes each of the 3 AI-drafted emails |
| `trial_followup.py` | Powers the dashboard — viewing, replying, trash/restore |
| `followup_email.py` | Actually sends the email once staff click Send |
| `templates/trial_followup*.html` | Dashboard, single-email view, completed campaigns view |
| `trial_followup_scheduler.py` | Earlier standalone scheduler prototype, no longer used |
| `trial_email_sender.py` | Unused duplicate of `followup_email.py`, no longer used |

---


