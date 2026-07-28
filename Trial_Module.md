# 🌱 Trial Follow-Up Module — Full Documentation

*A gentle 3-email nurture sequence for families whose free trial just ended — always AI-drafted, never auto-sent.*

---

## 🌟 What This Module Does (Simple Version)

When a learner's free trial ends without them enrolling, this module reaches back out — automatically. Once a day, it checks whose trial reached the 1-day, 3-day, or 7-day mark since expiry, writes a warm, personalized email with AI, and quietly saves it as a **draft**. Nothing goes out to a real family until a staff member actually opens it, reads it, and clicks Send.

---

## 🎬 Features

1. **Automatic Daily Check** — once a day, every free trial that has reached its 1/3/7-day follow-up mark is found automatically.
2. **AI-Written, Human-Sent** — each email is drafted by AI, but always waits for a staff member's review and click.
3. **Smart Enough to Stop** — if a learner already enrolled after their trial, the sequence recognizes that and doesn't keep nudging them.
4. **Dedicated Dashboard** — see every draft, what's due, reply to responses, review completed campaigns.
5. **Trash & Restore** — drafts that shouldn't go out can be trashed, and brought back later if needed.

## The 3-Email Sequence (timed from the trial's real expiry date)

| Day | Tone |
|---|---|
| Day 1 | Thank-you for trying the trial |
| Day 3 | Nudge to continue the learning journey (only drafted if Day 1 was already drafted) |
| Day 7 | Last reminder (only drafted if Days 1 and 3 were already drafted; marks the sequence complete either way) |

---

## 🛠️ Technical Details

### Tables Used

*Confirmed by directly tracing the live code and querying the actual database schema (`information_schema.columns`, `to_regclass`) — not inferred from variable names or guessed.*

| Table | Source | What it's for |
|---|---|---|
| `FreeTrialPass` | Supabase | Looks at every trial that ended in the last 30 days, not just today. The job runs once a day and checks each of these trials again and again — that is how it knows when day 1, day 3, and day 7 arrive for each one. |
| `Enrollments` | Supabase | Tells us which child (learner) a trial belongs to. |
| `Subscriptions` | Supabase | Used to exclude learners who already converted to a paid subscription after their trial started |
| `Users` | Supabase | Learner/parent names |
| Class titles lookup (shared with the Subscription module, from `subscription_cancel.py`) | Supabase | Tells us which class the learner was trying out, so the email can mention it by name. |
| `trial_followup_campaigns` | Main app Postgres (`database.py`) | Tracks each candidate's own progress — `email1_drafted_at`, `email2_drafted_at`, `email3_drafted_at`, `status` — created the first time a candidate is seen |

**No external Coral Academy REST API is involved** — candidates are pulled from these Supabase tables, same as the Subscription module.

### How "Already Converted" Is Actually Checked

The "Smart Enough to Stop" feature (`trial_followup.py`'s `get_trial_followup_candidates()`) isn't detecting a change or an event — it's a simple snapshot check on two timestamps, re-run fresh every single day the job runs (not just once when the campaign starts):

```python
if subscribed_at and start:
    subscribed_at = isoparse(subscribed_at)
    if subscribed_at >= start:
        converted = True
```

- `start` is the trial's own `enrollment_start_timestamp` — when *this* free trial began, not when it expires.
- `subscribed_at` is when the learner's currently-**active** subscription began (`subscription_status == "active"` is filtered at the query level before this check even runs).
- `subscribed_at >= start` answers a genuine before/after question: **"did the subscription start at or after this trial started?"** That's what actually matters for "did this trial lead to a conversion" — not an equality check like `subscribed_at != expiry`, which would almost always be `True` anyway (two independently-recorded timestamps are essentially never identical down to the second, so that comparison wouldn't tell you anything meaningful).

**Worked example:** trial starts July 1, expires July 15, subscription starts July 10 → `July 10 >= July 1` → `True` → correctly counted as converted (subscribed during the trial, before it even ended). If instead the learner had some unrelated old active subscription from back in March → `March >= July 1` → `False` → correctly *not* counted, since that subscription predates this trial and has nothing to do with it.

Because this check re-runs fresh every day, subscribing partway through the sequence (e.g., between email 1 and email 3) correctly stops later emails from being generated. **Fixed this session**: previously, the exclusion only skipped them from that day's candidate list without writing anything back, so a converted learner's campaign row just silently stayed at `status="active"` forever. Now `mark_followup_converted(learner_id)` is called at the exact point conversion is detected, setting `status='converted'` (only on a still-`active` row, so it never overwrites an already-`completed` campaign) — the same pattern as `update_followup_email3_sent()`'s `status='completed'`, just a distinct outcome. `'converted'` rows are correctly excluded from the separate "Completed Campaigns" count (`get_completed_campaign_count()`, which strictly filters `status = 'completed'`), since converting mid-sequence and finishing all 3 emails without converting are different outcomes worth tracking separately.

⚠️ **Also worth knowing**: the conversion check only looks for `subscription_status == "active"` — not "anything other than expired." A learner who subscribed and then had that subscription cancelled or a payment fail would **not** be caught by this check (their subscription is no longer "active"), so they'd still be treated as a valid follow-up candidate and keep getting nudged, even though they did convert at some point.

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
- **Placeholder-leak check**  the body is checked for any leftover bracketed placeholder-shaped text after swap-back; if found, the draft is discarded in favor of the safe hardcoded fallback template instead of ever reaching staff.

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


