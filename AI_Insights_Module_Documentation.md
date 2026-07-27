# 📊 AI Insights Module — Full Documentation

*A window into what the AI is actually doing — every call, every token, every error, all in one place.*

---

## 🌟 What This Module Does (Simple Version)

Every time the AI classifies or drafts a reply — anywhere in the app, not just regular email — it's logged: which model, how many tokens, how long it took, and whether it succeeded. This page is where that record actually gets read. Before it existed, this table was being **written to constantly and read by nobody** — a real gap found and fixed this session.

---

## 🎬 Features (at `/ai-insights`)

1. **Summary Stats** — total AI calls, how many failed, total tokens used, average response time.
2. **Broken Down by Category** — calls and error counts split by category (Classification, Billing, Admissions, Teacher, Reengagement, Trial Followup, etc.).
3. **Recent Errors** — the last 20 AI failures, with full error text.
4. **Look Up One Draft's Log** — paste a Message-ID to see exactly what happened for that reply; also reachable via "View AI Log" from any email's detail page.

> The full searchable/paginated/deletable log table that used to sit below this was removed this session — it showed raw internal entries (many labeled "no matching email — Teacher Portal or system entry") that weren't meaningful to staff. The underlying `ai_logs` table and its per-message lookup are untouched; only that bulk table view is gone.

---

## 🛠️ Technical Details

### Where the Logic Lives

- `get_ai_insights()` (`database.py`) — three queries: overall totals, per-category breakdown, last 20 errors — all from `ai_logs`.
- `get_ai_log_by_message_id()` — powers the single-message lookup box.
- (`get_ai_logs()`, `get_ai_log_categories()`, `delete_ai_log()` — removed this session along with the full-log-table UI, since nothing else called them.)
- `get_latest_reply_sources()` — added this session; pulls which specific Knowledge Base articles and historical emails were actually used for a given reply, now shown directly on the email detail page too, not just here.
- The route (`@app.get("/ai-insights")` in `main.py`) ties all of this together and handles deleting a log row.

### What Gets Logged, By What

- **Classification** (`ai_classifier.py`) — logs on both success and failure, category always `"Classification"`.
- **Reply generation** (`reply_generator.py`) — logs with the email's real category, plus which Knowledge Base articles/historical examples were used.
- **Teacher Portal** messages — same classifier/generator, tagged `teacher_portal:<message_id>`.
- **Subscription re-engagement** and **Trial follow-up** drafts — logged under `"Reengagement"` / `"Trial Followup"`.
- A logging failure itself can never crash the calling function — `save_ai_log()` catches its own errors and just prints, so a broken log write never destroys an already-generated draft.



---

## 📋 File Reference

| File | Role |
|---|---|
| `database.py` | All AI Insights queries — summary, by-category, errors, full log, single lookup, reply sources |
| `ai_logger.py` | Writes every AI call attempt to `ai_logs`, never lets a logging failure crash the caller |
| `main.py` — `/ai-insights` | The route and delete-log endpoint |
| `templates/ai_insights.html` | The page itself |

---
