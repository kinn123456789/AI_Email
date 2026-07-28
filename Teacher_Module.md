# 🍎 Teacher Portal Module — Full Documentation

*How messages between teachers and parents get synced in, understood by AI, and answered — all from one inbox.*

---

## 🌟 What This Module Does (Simple Version)

Parents can message their child's teacher directly through Coral Academy's Teacher Portal. This module pulls those conversations into the same kind of unified inbox as regular email — every new parent message gets **automatically classified** by AI (what's it about, how urgent is it) and, where it's safe to, gets a **draft reply ready to review**. A staff member opens the Teacher Inbox, reads the conversation, and sends the reply straight back to the parent through the Teacher Portal.

---

## 🎬 Features (what's actually usable today, at `/teacher-inbox`)

1. **Teacher Inbox** — pick a teacher, see their list of parent conversations sorted by **unread first**, then **most recent activity**, then **priority as a final tiebreaker**. Open any chat to see the full message thread.
2. **Auto-Sync Every 8 Minutes** — new parent messages are pulled in automatically.
3. **AI Classification** — every parent message gets a category, a priority, and a one-sentence summary.
4. **AI Draft Replies** — where it's safe to, a suggested reply is pre-written, grounded in Help Center content (same engine as regular email).
5. **Sending Replies** — edit the draft (or write your own — it's a plain editable text box, not locked to the AI's wording) and send — goes straight back through the Teacher Portal, saved into the thread.
6. **Deleting a Message** — removes it both from the Teacher Portal itself and the local copy shown here.

---

## 🛠️ Technical Details

### Data Flow

Coral Academy's Teacher Portal REST API (`api.preprod.coralacademy.com`, key-authenticated) → pulled and upserted into `conversations` / `conversation_messages` → classified and drafted by AI → shown in `/teacher-inbox`. Sending goes the other way: app → Teacher Portal API → success saved locally too.

**Auth:** a single, permanent API key (`TEACHER_PORTAL_API_KEY`, sent as the `x-api-key` header on every request) was generated for this app's access to the preprod Teacher Portal API — unlike Gmail's Domain-Wide Delegation elsewhere in this project, this key doesn't expire or need periodic renewal, so there's no equivalent of `gmail_watch.py`'s renewal job needed here.

- **Checkpoint/dedup**: a chat's messages are only re-fetched if its latest message isn't already stored (`conversation_message_exists`); inserts also use `ON CONFLICT DO NOTHING` as a second safety net.
- **Sync cadence**: every 8 minutes, offset 70 seconds from other scheduled jobs so it doesn't collide with them; only one run at a time, missed runs are simply skipped.
- Every run is logged (success/failure/duration).

> **Note**: Teacher Portal data lives in the **same** main Postgres database as the rest of the app — not a separate Supabase project. (The genuinely separate Supabase project is used by the Subscription and Trial Follow-up modules, for their own data — worth not confusing the two.)

*APIs and tables below confirmed by directly tracing the live code, not guessed:*
- **Teacher Portal API endpoints used**: `GET /ai-email/teachers`, `GET /ai-email/chats?teacher_id=`, `GET /ai-email/chats/{chat_id}/messages?teacher_id=&page=0`, `POST /ai-email/reply` (sending), `DELETE /ai-email/chats/{chat_id}/messages/{message_id}?teacher_id=` (deleting).
- **Tables used**: `conversations` (one row per chat) and `conversation_messages` (every message, plus the AI's category/priority/summary/draft columns) — both in the main app Postgres, per the Note above.

### Classification & Drafting

- Uses the exact same classifier (`ai_triage`) and reply engine (`reply_generator.generate_reply`) as regular email, just fed Teacher Portal content. Draft replies do **not** use historical-email style examples, only Help Center knowledge.
- **Context cap**: only the last 50 messages of a chat are given to the AI (fixed a real incident where one long-running thread grew to ~443,000 tokens and failed permanently against OpenRouter's 400,000 limit). This cap only affects what the AI sees — the full chat is still shown to staff in the UI.
- **Safety override**: messages containing words like "complaint," "refund," "legal," or "bullying" are always forced to human review and bumped to at least High priority, regardless of the AI's own judgment.
- Every classification/draft attempt is logged, tagged `teacher_portal:<message_id>`.

### Known Limitations Worth Flagging

- The Teacher Portal API is only ever read one page at a time (`page=0`) — an extremely long chat history beyond that first page is never pulled from the source at all, separate from the local 50-message AI cap.
- Two older routes/templates (`/teacher-dashboard`, `/teacher/{teacher_id}`) still work but aren't linked from the main navigation — `/teacher-inbox` is the one screen actually used day to day. One of their "back" links even points to a route that no longer exists.
- Several duplicate/backup files from earlier versions of this feature (`teacher_ai_processor.py`, `teacher_sync.py`, `teacher_db_reader.py`, and others) still sit in the repo but aren't used by the running app.

### ⚠️ Current Issue: Teacher Portal API returning 405 on all endpoints (as of 2026-07-28)

The original Teacher Portal integration used an `Authorization: Bearer` token obtained from the pre-production Teacher Portal. This authentication method was working successfully, but the bearer token expired approximately every 30 minutes, requiring manual renewal, which made it unsuitable for an automated background service.

To eliminate the need for manual token renewal, an API key generated by a user with administrative access to the pre-production environment was provided. The application was updated to authenticate using the `x-api-key` header instead of the short-lived bearer token. This API key authentication was also working successfully until approximately two days before this document was prepared.

**At the time of writing, all requests to the pre-production Teacher Portal AI Email API (`/ai-email/*`) are returning HTTP 405 (Method Not Allowed)**, including read, reply, and delete operations. Since the same response is returned across all endpoints and HTTP methods, the issue does not appear to be specific to any individual operation in this application and requires further investigation of the pre-production API environment before AI Email functionality can be tested further.

**Verification performed (2026-07-28):**

| Endpoint | Method | Result |
|---|---|---|
| `/ai-email/teachers` | GET | `405 Method Not Allowed` |
| `/ai-email/chats?teacher_id=...` | GET | `405 Method Not Allowed` |
| `/ai-email/reply` (dummy `chat_id`/`teacher_id`) | POST | `405 Method Not Allowed` |
| `/ai-email/chats/{chat_id}/messages/{message_id}` (dummy ids) | DELETE | `405 Method Not Allowed` |

- Response body was identical across all four calls: `{"response":"Method Not Allowed","placements":[]}`.
- Response headers included `access-control-allow-methods: POST, GET, OPTIONS, PUT, DELETE` — i.e. the server's own CORS header claims all four tested methods are allowed, yet every one of them was rejected with 405. This inconsistency (allowed per header, rejected per status) suggests the request may be failing earlier in the gateway/auth layer (e.g. a routing rule or an expired/misconfigured API key being caught before reaching the real handler) rather than a per-endpoint method restriction.
- Requests were served directly by Cloudflare (`server: cloudflare`, `cf-ray` present on each response) with no timeout — confirming the pre-production API is reachable and responding, just uniformly rejecting these requests.
- No code in this repository (`teacher_portal_api_reader.py`, `teacher_api_sync.py`, `teacher_api_sender.py`) has been modified in the days surrounding the onset of this issue — `git log` shows the last change to the reader/sync files predates the failure by several commits, ruling out a regression on the application side.
- **Recommended next step:** confirm with whoever manages the pre-production Teacher Portal API/infrastructure whether the `TEACHER_PORTAL_API_KEY` currently configured in this app's environment is still valid, and whether any gateway/routing change was deployed to `api.preprod.coralacademy.com` around 2026-07-26.

**Possible last-resort fallback (not recommended right now):** the permanent API key (`TEACHER_PORTAL_API_KEY`) is not working consistently — most likely due to a gateway/auth-layer issue on the pre-production side rather than the key itself being revoked (the identical 405 across every method/endpoint points upstream of the actual API logic, not to a per-endpoint restriction). `teacher_portal_reader.py` and `teacher_portal_sender.py` are older, still-functional integrations that hit real Teacher Portal endpoints using a short-lived `Authorization: Bearer` token instead of the API key. That token can only be obtained by logging into the Teacher Portal UI, so it can't be renewed by a plain scheduled script — in theory, Playwright could drive a browser session to log in and capture that token automatically. In practice this isn't a good option today: it requires running a headless Chromium browser on a schedule, and this app already runs on a memory-constrained 512MB Render instance that has suffered repeated OOM kills, one of them already tied to Chromium memory usage from an existing feature (`sync_help_center.py`). Adding a second, heavier Chromium-based job here would risk causing further crashes rather than fixing anything, and it doesn't address the actual root cause. This app is also built as a unified, API-first inbox — Gmail and the Teacher Portal are both integrated via clean REST/API calls, not browser scraping — so a Playwright-based workaround would be an architectural mismatch, not just a resource risk. It's noted here only as a theoretical last resort if the pre-production API issue turns out to be unfixable; the priority right now should stay on getting the API/gateway issue resolved at the source.

---

## 📋 File Reference

| File | Role |
|---|---|
| `teacher_portal_api_reader.py` | Reads teachers/chats/messages from the Teacher Portal API |
| `teacher_api_sync.py` | Syncs conversations/messages into the database every 8 minutes |
| `teacher_ai_processor1.py` | Classifies parent messages, builds capped thread history |
| `teacher_reply_generator1.py` | Generates the AI draft reply |
| `teacher_api_sender.py` | Sends/deletes messages through the Teacher Portal API |
| `teacher_ai_processor.py` | Old version — actually broken, imports a file that no longer exists |
| `teacher_reply_generator..py` | Predecessor of `teacher_reply_generator1.py`, no longer used |
| `teacher_sync.py` · `teacher_sync_backup.py` | Old sync logic, unused |
| `teacher_portal_reader.py` · `teacher_portal_sender.py` | Earlier versions of the reader/sender, no longer used |
| `teacher_db_reader.py` · `teacher_db_sync.py` | Old architecture that read Teacher Portal data from a separate Supabase project directly — since replaced |

---

