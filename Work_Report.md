# Work Report

**Date:** 25 July 2026
**Prepared by:** Kinnera (with Claude Code assistant)

This report explains, in simple words, what work was done today. It is divided by module (part of the system).

---

## 1. Subscription Cancel Page (Cancelled Students Dashboard)

**What it is:** A page that shows students who cancelled their subscription, so staff can send them a "come back" email.

**What was done:**
- Added a new "Class" column. Now staff can see which class the student was taking.
- This Class info is also saved when a row is deleted (moved to trash) or when an email is sent.
- The page was slow to load. We made it load faster by fetching data at the same time instead of one by one.
- Added a "Show All-Time" button. By default the page shows only last 3 months (faster). If staff need older records, they can click this button to see everything.
- Added a filter to search by status (Active, Cancelled, Payment Failed, etc.), not just "Cancelled".
- Found and fixed a crash bug: when there were more than 1000 records, the system was silently missing some of them, and in some cases it crashed. This is now fixed.
- The "win-back" email (AI-written email) used to take 20 seconds to prepare when staff opened a student's record. Now these emails are prepared in advance in the background, so they open instantly.

**Status:** Done and working.

---

## 2. Trial Follow-up Page

**What it is:** A page that manages follow-up emails to students whose free trial expired.

**What was done:**
- Added the same "Class" info here too (which class the student was in), shown in the email and on the page.
- Fixed the same 1000-record and crash-risk issue here as well, so it will not break even if data grows a lot.
- Made data loading faster using the same method as the Subscription Cancel page.

**Status:** Done and working.

---

## 3. Server Crash Fix (Render)

**What happened:** The server crashed two times this morning due to "out of memory" (it ran out of space to work).

**Why it happened (in simple words):**
The server runs some background tasks automatically:
- Check emails — every 5 minutes
- Sync teacher data — every 8 minutes
- Update subscription list — every 1 minute
- Prepare AI emails — every 1 minute

All four of these were set up to start at the same time when the server starts. Because of simple math (5, 8, and 1 minute schedules line up every 40 minutes), **all four tasks were running together every 40 minutes**, at the exact same second. This used too much memory at once, and the server crashed.

**What was fixed:**
- Changed the timing so these 4 tasks now start at different times. They will never run together again.
- Added a safety lock so the two subscription-cancel tasks cannot run at the same time as each other, even by accident.
- Also found and fixed a missing password setting (`TEACHER_PORTAL_API_KEY`) that was making the teacher-sync task fail every 8 minutes. This is now fixed too.

**Status:** Fixed and confirmed working. No crashes since the fix went live.

---

## 4. Bulk Mail / Compose Page

**What it is:** The page used to send one email to many people at once (bulk email).

**What was done:**
- Before, to send a CSV list of people, staff had to upload a CSV file.
- Now, staff can also **paste** the CSV text directly into a box on the same page — no need to upload a file.
- Limit stays the same: maximum 100 people per send (for both file upload and paste).

**Status:** Done and working.

---

## Summary Table

| Module | Work Done | Status |
|---|---|---|
| Subscription Cancel Page | Class info, faster loading, all-time view, status filter, crash fix, instant emails | ✅ Done |
| Trial Follow-up Page | Class info, crash fix, faster loading | ✅ Done |
| Server (Render) | Fixed crash cause, fixed missing password | ✅ Fixed |
| Bulk Mail Page | Added "paste CSV" option | ✅ Done |

All changes have been saved (committed) and are live on the server.
