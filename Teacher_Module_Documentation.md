# 🍎 Teacher Portal Module — Full Documentation

*How messages between teachers and parents get synced in, understood by AI, and answered — all from one inbox.*

---

## 🌟 What This Module Does (Simple Version)

Parents can message their child's teacher directly through Coral Academy's Teacher Portal. This module pulls those conversations into the same kind of unified inbox as regular email — every new parent message gets **automatically classified** by AI (what's it about, how urgent is it) and, where it's safe to, gets a **draft reply ready to review**. A staff member opens the Teacher Inbox, reads the conversation, and sends the reply straight back to the parent through the Teacher Portal.

---

## 🎬 Features (what's actually usable today, at `/teacher-inbox`)

1. **Teacher Inbox** — pick a teacher, see their list of parent conversations sorted by **unread first**, then **most recent activity**, then **priority as a final tiebreaker**. Open any chat to see the full message thread.
2. **Auto-Sync Every 8 Minutes** — new parent messages are pulled in automatically.
3. **Manual "Sync Now"** — a one-click trigger to pull the very latest messages immediately.
4. **AI Classification** — every parent message gets a category, a priority, and a one-sentence summary.
5. **AI Draft Replies** — where it's safe to, a suggested reply is pre-written, grounded in Help Center content (same engine as regular email).
6. **Sending Replies** — edit the draft (or write your own) and send — goes straight back through the Teacher Portal, saved into the thread.
7. **Deleting a Message** — removes it both from the Teacher Portal itself and the local copy shown here.

---

## 🛠️ Technical Details

### Data Flow

Coral Academy's Teacher Portal REST API (`api.preprod.coralacademy.com`, key-authenticated) → pulled and upserted into `conversations` / `conversation_messages` → classified and drafted by AI → shown in `/teacher-inbox`. Sending goes the other way: app → Teacher Portal API → success saved locally too.

- **Checkpoint/dedup**: a chat's messages are only re-fetched if its latest message isn't already stored (`conversation_message_exists`); inserts also use `ON CONFLICT DO NOTHING` as a second safety net.
- **Sync cadence**: every 8 minutes, offset 70 seconds from other scheduled jobs so it doesn't collide with them; only one run at a time, missed runs are simply skipped.
- Every run is logged (success/failure/duration).

> **Note**: Teacher Portal data lives in the **same** main Postgres database as the rest of the app — not a separate Supabase project. (The genuinely separate Supabase project is used by the Subscription and Trial Follow-up modules, for their own data — worth not confusing the two.)

### Classification & Drafting

- Uses the exact same classifier (`ai_triage`) and reply engine (`reply_generator.generate_reply`) as regular email, just fed Teacher Portal content. Draft replies do **not** use historical-email style examples, only Help Center knowledge.
- **Context cap**: only the last 50 messages of a chat are given to the AI (fixed a real incident where one long-running thread grew to ~443,000 tokens and failed permanently against OpenRouter's 400,000 limit). This cap only affects what the AI sees — the full chat is still shown to staff in the UI.
- **Safety override**: messages containing words like "complaint," "refund," "legal," or "bullying" are always forced to human review and bumped to at least High priority, regardless of the AI's own judgment.
- Every classification/draft attempt is logged, tagged `teacher_portal:<message_id>`.

### Known Limitations Worth Flagging

- The Teacher Portal API is only ever read one page at a time (`page=0`) — an extremely long chat history beyond that first page is never pulled from the source at all, separate from the local 50-message AI cap.
- Two older routes/templates (`/teacher-dashboard`, `/teacher/{teacher_id}`) still work but aren't linked from the main navigation — `/teacher-inbox` is the one screen actually used day to day. One of their "back" links even points to a route that no longer exists.
- Several duplicate/backup files from earlier versions of this feature (`teacher_ai_processor.py`, `teacher_sync.py`, `teacher_db_reader.py`, and others) still sit in the repo but aren't used by the running app.

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

