# Complete Project Report

**Prepared by:** Kinnera (with Claude Code assistant)
**Date:** 26 July 2026

This report explains, in simple words, what this whole project does and how it works underneath. It covers all 6 main parts (modules):
1. Emails
2. Teacher Portal
3. Trial Follow-up
4. Cancelled Subscription
5. Contact Form
6. AI Insights

Every file in the project was checked to write this report, so it also mentions a few small known issues that are honest to point out.

---

## 1. Emails

**What it is:**
This is the main part of the whole project. It watches 3 email inboxes for Coral Academy:
- support@coralacademy.com
- lucy@coralacademy.com
- engineering@coralacademy.com

**How new emails come in:**
- Gmail sends an instant alert the second a new email arrives (a "push notification"), and the system reads it right away.
- As a backup, the system also checks each inbox every 5 minutes, in case an alert was missed.

**What happens automatically to every email:**
1. Junk emails (newsletters, password resets, spam, automatic system alerts) are filtered out automatically using a mix of fixed rules and a rules list stored in the database. Staff don't need to see these — they go to a separate "Notifications" page, not the main inbox.
2. Every real email is read by AI (the AI model used is called **gpt-5-nano**), which decides:
   - What category it is (Admissions, Billing, Teacher, General, etc.)
   - How urgent it is (Urgent, High, Medium, Low)
   - A short one-line summary
   - Whether a staff member must check it before anything is sent
3. To help write a good reply, the AI also looks at:
   - The school's help-center articles (searched by meaning, not just keywords)
   - Real past emails Coral Academy staff have sent before, so the new reply sounds like Coral Academy wrote it (only the writing *style* is copied, never real facts, names, or promises from the old email)
4. The AI then writes a full draft reply.
5. Sensitive topics are always sent to a staff member to check first, no matter what — this is enforced twice: once by the AI's own judgment, and once again by the system double-checking for words like "complaint," "refund," "legal," "bullying," or "harassment." If either check trips, a human must review it.
6. Every email ends up as: "No Reply Needed", "Needs Review" (AI wrote a draft, staff must approve), or "Replied".

**What staff can do:**
- Search and filter emails (by mailbox, status, date, free text search)
- See unread emails, priority, and category at a glance, with the list refreshing itself automatically every 8 seconds
- Open a full email conversation, see the AI's draft, edit it, and send it
- Download attachments
- Delete emails (move to Trash)
- Write and send a brand-new email (Compose page) — including sending the *same* email to many people at once, either by typing addresses, pasting a list, or uploading a CSV file (capped at 100 people per send, to prevent accidental mass-sending)

**Other features:**
- Emails staff send manually straight from Gmail (outside this app) are also pulled back in every hour, so the full conversation always shows in one place here.
- Every reply that actually gets sent is automatically saved and added to the "learn from past emails" pool, so the AI keeps getting better real-world examples over time.
- Before anything gets added to that "learn from past emails" pool, any email address or phone number found inside it is automatically blanked out first (replaced with a label like `[EMAIL]` or `[PHONE]`) — this protects a different family's contact details from ever being shown to the AI while it drafts a reply to someone else's email. (Note: this only cleans up *new* items being added — the small number already saved before this fix was made still have the real contact details in them.)
- A Slack notification feature exists in the code but is currently switched off (the code to send the message is there, just commented out).

**Behind the scenes (technical details, simply explained):**
- Two databases are used together: one for the actual email messages and conversations, and one (Supabase) for other Coral Academy data.
- Finding "similar past emails" and "similar help articles" works by turning text into a list of numbers (called an "embedding") and finding the closest matches — this is a well-known AI search technique.
- A second AI check ("reranking") looks at the ~30 possible past-email matches and picks only the 2-3 that would genuinely help write a good reply, instead of just picking whichever matched best by raw similarity.
- Every single AI reply attempt (successful or failed) is logged in detail (how long it took, how many "tokens" it used, what information it was given) so problems can be traced later.

**Known small issues:**
- The "Restore" button on the main email Trash page is visible but doesn't actually work yet (it isn't connected to anything) — trashed emails currently can't be restored from there. (Restore does work correctly on the Trial Follow-up and Cancelled Subscription trash pages.)

**Status:** This is the most complete and most used part of the whole project. It is stable and production-ready.

---

## 2. Teacher Portal

**What it is:**
A place for staff to see and reply to chat messages between parents and teachers. These chats actually happen on a separate, outside system (the school's real Teacher Portal). This app pulls in a copy so staff can review and help from one place.

**How it works:**
- Every 8 minutes, the system automatically checks the outside Teacher Portal (over the internet, using a secret access key) for any new teachers, chats, and messages, and copies them into this app's own database.
- There is also a manual "Sync Now" option if staff want to check immediately instead of waiting.
- Once copied in, new parent messages are read by the same AI used for emails (**gpt-5-nano**), which gives a category, urgency level, a short summary, and — if a reply seems needed — a suggested draft reply, using the school's help articles for reference.
- A special rule always marks genuine parent-to-teacher messages as "Teacher" category and "Medium" priority, and (as of a recent fix) lets the AI decide for itself, case by case, whether that particular message actually needs a human to check it first — it is no longer automatically marked "safe, no review needed" just because it came from the Teacher Portal.

**What staff can do:**
- See a list of all teachers, with the number of chats and unread messages for each
- Open a teacher to see all their conversations with parents
- Use a 3-column inbox view: list of teachers → list of that teacher's chats → the full conversation with an AI assistant panel showing the summary and suggested reply
- Read the full conversation and reply — the reply is sent back out to the *real* Teacher Portal (so the parent actually receives it there), and a copy is also saved here
- Delete a message they sent by mistake (removes it from the real Teacher Portal too)

**Status:** This feature works, but it is less polished than the Emails module. There are quite a few older/backup versions of files left over in the project from earlier attempts at building this (an old sync method, an old sender, an old reply-generator) — none of these old versions are used anymore, only the newest versions are live. There's also one small broken link in the interface ("← Back" on one page points to a page that doesn't exist), and two slightly different "send reply" routes exist where really only one is needed. None of this stops the feature from working, but it shows this part is still a bit rough around the edges compared to Emails.

---

## 3. Trial Follow-up

**What it is:**
Coral Academy gives free trial classes. If a student's free trial ends and the parent doesn't join a paid membership, this system automatically follows up with the parent to try and get them to join.

**How it works:**
- Once every day, at 9:00 AM, the system checks for trials that have expired.
- It sends a total of 3 follow-up emails over time:
  - 1 day after the trial ends
  - 3 days after
  - 7 days after
- Each email is written by AI (**gpt-5-nano**), in a warm and friendly tone, and mentions the actual class the student was trying if that information is available.
- The AI never sees the parent's or student's real name directly — a placeholder like `[PARENT_NAME]`/`[STUDENT_NAME]` is used instead while writing the draft, and the real names are put back in afterwards. This keeps real family names from ever being sent to the outside AI service unnecessarily.
- If the parent joins a paid plan at any point, the follow-up sequence stops automatically — that student is no longer treated as a candidate.
- Every drafted email is saved first, then a staff member must review and click "Send" — nothing is emailed automatically without a human clicking Send.

**What staff can do:**
- See all follow-up emails, search and filter by date/status
- See how many students are on follow-up 1, 2, or 3
- Open any email to read it, review/edit the AI draft, and send it
- See a page of "Completed Campaigns" (students who got all 3 follow-ups)
- Delete (trash) and restore email records
- Send a further reply if the parent responds

**Behind the scenes (technical details, simply explained):**
- Finding which students count as trial candidates involves joining together several pieces of information stored in the Supabase database (trial records, class enrollments, subscription records, user names). Because this list can get large, the system fetches it in safe batches instead of all at once, to avoid errors that happen when asking a database for too much information in a single request.
- Several of these batch-fetching safety techniques were originally built for the Cancelled Subscription module (see below) and are simply reused here, since both features run into the same kind of database limits.

**Known small issue:**
- The "Active Campaigns" number shown on the dashboard is currently always blank — the code to calculate it exists but was never actually connected to the page. Everything else on the dashboard works correctly.

**Status:** Working well, and recently made faster and safer against large amounts of data.

---

## 4. Cancelled Subscription

**What it is:**
A dashboard (recently renamed internally from "Win-back" to "Re-engagement," though the page title still says "Cancelled Subscriptions") that shows students whose paid subscription was cancelled, or whose free trial expired without turning into a paid plan — so staff can send them a friendly email asking them to come back.

**How it works:**
- The system automatically finds:
  - Subscriptions that were cancelled
  - Expired free trials that never converted to a paid plan
- By default, it shows only the last 3 months (to keep the page fast). Staff can click "Show All-Time" to see everything, including older records (this view is a bit slower, since it's less commonly used).
- Staff can filter by status — Cancelled, Active, Payment Failed, Trial Expired, and more — not just "Cancelled."
- AI (**gpt-5-nano**) writes a warm "come back" email for each student, using details like how many classes they attended and which class they were in. As with Trial Follow-up, the real parent/student names are hidden from the AI while it writes, using placeholder words, and swapped back in afterward.
- These AI emails are prepared in advance in the background (a small batch every minute), so when a staff member opens a student's page, the draft is usually already there instead of making them wait ~20 seconds for the AI to write it live.

**What staff can do:**
- Search, filter by date and status
- See which class the student was in and how many sessions they attended
- Send the AI-written email (editing it first if needed)
- Delete (trash) and restore records
- See a list of all emails already sent

**Behind the scenes (technical details, simply explained) — this module had the most engineering work done on it:**
- **The "keep the list up to date" job used to redo all the work every single minute.** Every 60 seconds, it would completely re-fetch and re-combine every subscription and trial from the last 3 months, even if nothing had changed since the last check. This was heavy, repeated work happening constantly, and was found to be a real cause of the app running out of memory and crashing on the server.
- **This was fixed by making the refresh "smart."** Now, most minutes, it only asks the database "what changed since the last check?" and updates just those few records — instead of redoing everything. Once every ~30 minutes, it still does one full, complete refresh, to catch two things the quick check can't see on its own: a student attending a new class session (which doesn't count as the subscription itself "changing"), and a parent who subscribes again after their trial had already expired.
- **Database request limits were discovered and fixed.** The database this data comes from (Supabase) has hidden limits — it silently cuts off a result list at 1,000 rows, and it fails outright if you ask for too many specific records at once (roughly 500-700). The system now automatically splits big requests into safe smaller batches to work around both limits.
- **A memory leak was found and fixed.** Every time the system needed a fresh connection to the database for a background task, a new connection was being opened but never properly closed. Over time this built up and used more and more memory. Every connection is now explicitly closed right after it's used.
- **Background jobs were spaced out on purpose.** Several automatic jobs (refreshing this dashboard, preparing AI drafts, checking email, syncing the Teacher Portal) used to all happen to line up and fire at the exact same time every so often, which could overload the server. They are now deliberately staggered so they never collide.
- Because of everything above, the team deliberately chose to make this dashboard update slightly slower in exchange for using less memory and crashing less — this was a conscious trade-off, not an accident.

**Known small issue:**
- The page title and some button/menu text still say "Win-back," even though the underlying code has been renamed to "Re-engagement." This is just leftover labeling, not a functional problem.

**Status:** Working well, and this is the module that received the most reliability and performance work recently.

---

## 5. Contact Form

**What it is:**
When someone fills out the "Contact Us" form on the school's website, their message should end up here so staff can review and reply to it, separately from regular support email.

**How it actually works (this is more roundabout than it might sound):**
- The school's website does NOT send the enquiry directly into this app. Instead, when someone submits the form, the school's own separate website system sends a normal notification **email** (from `no-reply@coralacademy.com`, with a subject starting "New Contact Form Enquiry") to the support inbox — the same inbox this app already watches for regular emails.
- This app's regular email-checking system picks up that notification email like any other email, but recognizes it as a contact-form enquiry by its sender and subject line.
- **Field extraction (`process_email.py`), in simple words:** the email that arrives is just one plain block of text (`Name: ... / Email: ... / Phone: ... / Message: ... / Submitted at: ...`). If nobody separated this out, staff would see this whole messy block instead of a clean record. So the code reads it and pulls out each piece on its own:
  - **Name** — takes the text after `Name:`; if missing, just keeps whatever name was already on the email.
  - **Email** — takes the text after `Email:`, but only if it looks like a real email address (has an "@"); otherwise keeps the original sender address.
  - **Phone** — takes the text after `Phone:`; if missing, just left blank, nothing breaks.
  - **Message** — the actual question the person typed. Grabs everything between `Message:` and `Submitted at:` and shows only that. If `Submitted at:` is missing, it just grabs everything from `Message:` to the end instead — no harm done. Only real problem case: if `Message:` itself is missing, the code gives up and shows the whole raw email instead, so nothing silently disappears.
  - **Worth knowing:** the website's form requires Name, Email, Phone, and Message to be filled in before someone can even submit it — so in everyday use, none of these "what if it's missing" situations should actually happen. They're documented because that's genuinely what the code does if something unexpected ever comes through, not because they're expected day to day.
- The enquiry then gets the same AI treatment as a normal email — category, priority, summary, and a suggested draft reply — and is stored as its own type, so it shows up on its own dedicated page instead of mixing into the regular inbox.

**What staff can do:**
- Browse all website enquiries, newest first, on their own dedicated page
- Search by name, email, phone, or message
- Filter by date range
- See "All Enquiries" vs "Sent Mails" (already replied) separately
- Reply directly — this sends a real email straight to the actual person who filled out the form (not to the website's no-reply address), using the exact same reply screen as regular emails
- Select many at once and delete (trash) them


**Status:** Small but complete feature — it works like a mini customer-support inbox just for website enquiries, just through an email-based path rather than a direct connection.

---

## 6. AI Insights

**What it is:**
A behind-the-scenes page (not something a parent or teacher ever sees) where staff can check how the AI itself is actually doing — not the emails, the AI's own performance.

**How it works:**
- Every single time the AI classifies or drafts a reply — for regular email, Teacher Portal messages, Trial Follow-up, or Cancelled Subscription emails alike — that attempt gets logged: which AI model was used, how many tokens it cost, how long it took, and whether it succeeded or failed.
- Before this project's review, that log was being written constantly but nobody had ever built a page to actually read it. This page is that missing piece.
- It shows: overall totals (how many AI calls, how many failed, total tokens, average speed), a breakdown by category (so if one type of question is failing more than others, that's easy to spot), the last 20 failures with the full error message, and a way to look up exactly what happened for one specific email/reply.
- A more detailed, raw table of every single log entry also exists underneath, but it was hidden from the page since it showed internal technical entries that weren't meaningful to a staff member browsing it — the data itself is still fully there and queryable, just not shown as a giant raw table.

**What staff can do:**
- See at a glance whether the AI is working well or having a rough patch, without digging through server logs
- Spot which category (Billing, Admissions, Teacher, etc.) is generating the most errors
- Look up one specific reply and see exactly why the AI answered the way it did

**Status:** ✅ Small, complete feature — a diagnostics page rather than something end users interact with, but genuinely useful for catching AI problems early instead of only hearing about them from an unhappy parent.

---

## Overall Summary Table

| Module | What it does | AI Involved? | Status |
|---|---|---|---|
| Emails | Main inbox for 3 school email accounts, auto-sorts and drafts replies | Yes | ✅ Mature, main feature |
| Teacher Portal | Syncs parent-teacher chats from outside portal, lets staff reply | Yes | ⚠️ Working, still a bit rough in places |
| Trial Follow-up | Sends 3-stage follow-up emails after a free trial expires | Yes | ✅ Working, recently improved |
| Cancelled Subscription | Sends "come back" emails to cancelled/at-risk students | Yes | ✅ Working, biggest reliability improvements made here |
| Contact Form | Handles website "Contact Us" form submissions (via email, not direct connection) | Yes | ✅ Small, complete feature |
| AI Insights | Diagnostics page showing how well the AI itself is performing | No (reports on AI, doesn't call it) | ✅ Small, complete feature |

All 6 modules are connected to the same underlying databases and share the same AI system for reading and replying to messages. The AI model used everywhere in this project is called **gpt-5-nano**, reached through a service called OpenRouter.
