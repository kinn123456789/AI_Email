"""Focused tests for the dashboard-performance P0 sprint (view_email
parallelization, get_emails() combined COUNT+SELECT, and the Tailwind
duplicate-script investigation).

Matches this repo's existing test_*.py convention (see test_accuracy_fixes.py,
test_review_reasons.py): a plain script using only assert statements and the
standard library plus whatever's already installed - no pytest. A new,
separate file rather than touching the existing suites.

TWO KINDS OF CHECK, SAME SPLIT AS test_review_reasons.py:

1. database.py's get_emails() is checked with REAL imports against the same
   fake psycopg2/dotenv infrastructure the other test files already
   establish - a fake cursor here additionally queues per-call fetchall/
   fetchone results so the fallback branch (empty first attempt -> recompute
   total -> re-select) can be exercised realistically.

2. main.py's view_email() can't be imported (starts real scheduler.py
   background jobs, needs fastapi/apscheduler) - checked via source-presence
   checks against the real file, same technique test_p0_fixes.py and
   test_review_reasons.py already use for main.py.

Run with: python3 test_performance_fixes.py
"""

import os
import sys
import types


_failures = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" - {detail}" if detail and not condition else ""))
    if not condition:
        _failures.append(name)


# ---------------------------------------------------------------------------
# Fake infrastructure - identical technique to test_review_reasons.py, but
# with per-call fetchall/fetchone queues so get_emails()'s fallback branch
# (combined query returns 0 rows -> recompute total -> re-select) can be
# exercised with realistic, distinct results at each step.
# ---------------------------------------------------------------------------

def _install_fake_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


class QueueCursor:
    def __init__(self, pool):
        self._pool = pool

    def execute(self, sql, params=None):
        self._pool.sql_log.append(sql)
        self._pool.params_log.append(params)

    def fetchall(self):
        return self._pool.fetchall_queue.pop(0)

    def fetchone(self):
        return self._pool.fetchone_queue.pop(0)

    def close(self):
        pass


class QueueConnection:
    def __init__(self, pool):
        self._pool = pool

    def cursor(self, cursor_factory=None):
        return QueueCursor(self._pool)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


class QueuePool:
    def __init__(self, *a, **kw):
        self.sql_log = []
        self.params_log = []
        self.fetchall_queue = []
        self.fetchone_queue = []

    def getconn(self):
        return QueueConnection(self)

    def putconn(self, conn):
        pass


def _install_fakes():
    _install_fake_module("dotenv", load_dotenv=lambda *a, **kw: None)
    _install_fake_module("openai", OpenAI=lambda *a, **kw: types.SimpleNamespace())

    pool_mod = _install_fake_module("psycopg2.pool", SimpleConnectionPool=QueuePool)
    extras_mod = _install_fake_module("psycopg2.extras", RealDictCursor=dict)
    psycopg2_mod = _install_fake_module("psycopg2")
    psycopg2_mod.pool = pool_mod
    psycopg2_mod.extras = extras_mod
    psycopg2_mod.connect = lambda *a, **kw: QueueConnection(QueuePool())


_install_fakes()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import database  # noqa: E402

_pool = QueuePool()
database.db_pool = _pool


def _reset_pool():
    _pool.sql_log.clear()
    _pool.params_log.clear()
    _pool.fetchall_queue.clear()
    _pool.fetchone_queue.clear()


def _fake_row(id_, **overrides):
    row = {
        "id": id_, "sender": "parent@example.com", "subject": "s", "source": "support@coralacademy.com",
        "category": "General", "priority": "Medium", "status": "Needs Review", "reply_type": "automatic",
        "created_at": None, "first_reply_at": None, "resolved_at": None, "knowledge_url": None,
        "ai_confidence": 0.9, "ai_summary": "sum", "ai_draft_reply": "draft", "requires_review": True,
        "is_read": False, "has_attachment": False,
    }
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# B) get_emails(): combined COUNT + SELECT
# ---------------------------------------------------------------------------

def test_get_emails_combined_query_used_when_rows_found():
    """The common case (requested page is in range) must resolve in exactly
    one round trip: one execute(), carrying window-function total/count
    columns, no separate COUNT query and no fallback re-select."""
    _reset_pool()
    rows = [
        _fake_row(1, total=2, needs_review_count=1, auto_reply_count=1),
        _fake_row(2, total=2, needs_review_count=1, auto_reply_count=1, status="Replied", reply_type="human"),
    ]
    _pool.fetchall_queue.append(rows)

    result = database.get_emails(page=1, page_size=50)

    check("exactly one DB round trip for the common (in-range page) case", len(_pool.sql_log) == 1,
          f"got {len(_pool.sql_log)} execute() calls")
    check("the single query uses COUNT(*) OVER() (combined, not a separate COUNT query)",
          "OVER()" in _pool.sql_log[0])
    check("result total matches the window-function value", result["total"] == 2)
    check("result needs_review_count matches the window-function value", result["needs_review_count"] == 1)
    check("result auto_reply_count matches the window-function value", result["auto_reply_count"] == 1)
    check("result page/total_pages computed correctly", result["page"] == 1 and result["total_pages"] == 1)
    check("returned rows have the window-function columns stripped (total)",
          all("total" not in r for r in result["rows"]))
    check("returned rows have the window-function columns stripped (needs_review_count)",
          all("needs_review_count" not in r for r in result["rows"]))
    check("returned rows have the window-function columns stripped (auto_reply_count)",
          all("auto_reply_count" not in r for r in result["rows"]))
    check("row count/order preserved (2 rows, id=1 then id=2)",
          [r["id"] for r in result["rows"]] == [1, 2])
    check("handled_by is still derived per row (unrelated existing behavior preserved)",
          result["rows"][0]["handled_by"] == "AI" and result["rows"][1]["handled_by"] == "Human")


def test_get_emails_zero_matching_rows():
    """A genuinely empty filtered set: the combined query legitimately
    returns zero rows, so the fallback COUNT must run once to confirm
    total=0 - but the fallback re-select must NOT run, since a 0-row total
    can't have any rows to fetch (matches this endpoint's pre-existing
    total=0 -> total_pages=1, page=1, rows=[] behavior)."""
    _reset_pool()
    _pool.fetchall_queue.append([])  # combined query: no matches
    _pool.fetchone_queue.append({"total": 0, "needs_review_count": 0, "auto_reply_count": 0})

    result = database.get_emails(page=1, page_size=50, status="NoSuchStatus")

    check("exactly 2 round trips for a genuinely empty result (combined attempt + fallback COUNT)",
          len(_pool.sql_log) == 2, f"got {len(_pool.sql_log)}")
    check("the fallback re-select is skipped when total is 0",
          "OVER()" not in _pool.sql_log[1] and "LIMIT" not in _pool.sql_log[1])
    check("total/total_pages/page/rows match the pre-existing zero-result behavior",
          result == {
              "rows": [], "total": 0, "needs_review_count": 0, "auto_reply_count": 0,
              "page": 1, "total_pages": 1,
          })


def test_get_emails_page_beyond_last_page_falls_back_correctly():
    """A requested page past the real last page: the combined query's
    optimistic OFFSET overshoots and returns 0 rows even though total>0.
    The fallback must recompute the true total, clamp page to the real
    last page (matching the pre-existing min(page, total_pages) clamp),
    and re-run the SELECT with the corrected offset."""
    _reset_pool()
    _pool.fetchall_queue.append([])  # combined query at the requested (too-high) offset: nothing there
    _pool.fetchone_queue.append({"total": 137, "needs_review_count": 40, "auto_reply_count": 30})
    clamped_page_rows = [_fake_row(i) for i in range(101, 138)]  # page 3 of a 137-row, 50-per-page set: 37 rows
    _pool.fetchall_queue.append(clamped_page_rows)

    result = database.get_emails(page=10, page_size=50)  # only 3 real pages exist

    check("3 round trips for the out-of-range-page fallback (combined attempt + COUNT + re-select)",
          len(_pool.sql_log) == 3, f"got {len(_pool.sql_log)}")
    check("page is clamped to the real last page (3), matching the pre-existing clamp behavior",
          result["page"] == 3)
    check("total_pages computed from the true total (137 / 50 -> 3 pages)", result["total_pages"] == 3)
    check("total reflects the true total, not the (empty) first attempt", result["total"] == 137)
    check("rows come from the corrected, re-run SELECT", len(result["rows"]) == 37)
    check("needs_review_count/auto_reply_count come from the fallback COUNT",
          result["needs_review_count"] == 40 and result["auto_reply_count"] == 30)


def test_get_emails_preserves_filters_search_and_order():
    """Every existing filter/search/order fragment must still be present
    (and still parameterized, never string-interpolated) in the combined
    query - this function's whole point is a pure round-trip optimization,
    not a behavior change."""
    _reset_pool()
    _pool.fetchall_queue.append([_fake_row(1, total=1, needs_review_count=0, auto_reply_count=0)])

    database.get_emails(
        source="lucy@coralacademy.com", search="tuition", status="Needs Review",
        date_from="2026-01-01", date_to="2026-01-31", read_status="unread",
        page=1, page_size=50,
    )

    sql = _pool.sql_log[0]
    params = _pool.params_log[0]

    for fragment in [
        "AND source = %s", "AND status = %s", "AND is_read = FALSE",
        "AND created_at::date >= %s", "AND created_at::date <= %s",
        "AND (subject ILIKE %s OR sender ILIKE %s OR body ILIKE %s)",
        "WHERE mailbox = 'inbox'", "AND status != 'Resolved'",
        "ORDER BY", "is_read ASC", "CASE status", "CASE priority",
        "email_date DESC NULLS LAST", "created_at DESC", "LIMIT %s OFFSET %s",
    ]:
        check(f'combined query still includes "{fragment}"', fragment in sql)

    check("status='Needs Review' does not drop the gmail_manual exclusion (only 'Replied' does)",
          "AND reply_type IS DISTINCT FROM 'gmail_manual'" in sql)
    check("search term is parameterized (ILIKE wildcards), not string-interpolated into the SQL",
          "tuition" not in sql and any(p == "%tuition%" for p in params))
    check("all filter param values are present, in filter-application order",
          params[:-2] == ["lucy@coralacademy.com", "Needs Review", "2026-01-01", "2026-01-31",
                           "%tuition%", "%tuition%", "%tuition%"])
    check("LIMIT/OFFSET params are appended last", params[-2] == 50 and params[-1] == 0)


def test_get_emails_replied_status_drops_gmail_manual_filter():
    """Existing behavior: the Sent Mails view (status='Replied') must NOT
    exclude reply_type='gmail_manual' rows, unlike every other view."""
    _reset_pool()
    _pool.fetchall_queue.append([_fake_row(1, total=1, needs_review_count=0, auto_reply_count=0, status="Replied")])

    database.get_emails(status="Replied", page=1, page_size=50)

    check("status='Replied' drops the gmail_manual exclusion (unchanged pre-existing behavior)",
          "gmail_manual" not in _pool.sql_log[0])


# ---------------------------------------------------------------------------
# A) view_email(): parallelized lookups + removed debug round trip.
# main.py can't be imported here (starts real scheduler.py background jobs,
# needs fastapi/apscheduler) - same limitation test_p0_fixes.py and
# test_review_reasons.py already document for this file. Checked via
# source-presence against the real file instead.
# ---------------------------------------------------------------------------

def _read_main_source():
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py"), "r", encoding="utf-8") as f:
        return f.read()


def _view_email_body():
    src = _read_main_source()
    start = src.find("def view_email(request: Request, email_id: int):")
    end = src.find("\n@app.get(\"/attachments/{attachment_id}\")")
    assert start != -1 and end != -1 and end > start, "could not locate view_email() body"
    return src[start:end]


def test_view_email_redundant_select_is_read_removed():
    body = _view_email_body()
    check("the redundant post-update SELECT is_read query is gone",
          "SELECT is_read FROM messages WHERE id = %s" not in body)
    check('its debug print ("AFTER UPDATE:") is gone', '"AFTER UPDATE:"' not in body)
    check("mark_email_read(email_id) is still called (real behavior preserved)",
          "mark_email_read(email_id)" in body)
    check("get_email_by_id(email_id) is still called (real behavior preserved)",
          "get_email_by_id(email_id)" in body)


def test_view_email_four_lookups_run_through_threadpoolexecutor():
    body = _view_email_body()
    check("uses ThreadPoolExecutor (the same concurrency pattern already used elsewhere in this repo)",
          "with ThreadPoolExecutor(max_workers=4) as executor:" in body)
    for fn in ["get_latest_thread_ai", "get_latest_reply_sources", "get_thread", "get_attachments"]:
        check(f"{fn} is submitted to the executor (runs concurrently, not sequentially)",
              f"executor.submit({fn}" in body)


def test_view_email_preserves_thread_id_and_message_id_guards():
    """The four lookups are independent of each other, but two of them
    (get_latest_thread_ai, get_thread) still depend on thread_id being
    present, and get_attachments still depends on message_id being present -
    exactly as before parallelization. A falsy id must still skip the DB
    call entirely rather than querying with NULL."""
    body = _view_email_body()
    check("get_latest_thread_ai is only submitted when thread_id is truthy",
          "executor.submit(get_latest_thread_ai, thread_id) if thread_id else None" in body)
    check("get_thread is only submitted when thread_id is truthy",
          "executor.submit(get_thread, thread_id) if thread_id else None" in body)
    check("get_attachments is only submitted when message_id is truthy",
          "executor.submit(get_attachments, message_id) if message_id else None" in body)
    check("a missing thread_id still yields an empty conversation list (fallback preserved)",
          "conversation_future.result() if conversation_future else []" in body)
    check("a missing message_id still yields an empty attachments list (fallback preserved)",
          "attachments_future.result() if attachments_future else []" in body)


def test_view_email_result_merge_logic_unchanged():
    """The actual field-by-field merge of latest_ai/reply_sources into
    email_data - the part that determines what the template sees - must be
    byte-for-byte the same condition/assignment logic as before
    parallelization, just no longer nested inside `if thread_id:`."""
    body = _view_email_body()
    for expected in [
        'email_data["ai_summary"] = latest_ai["ai_summary"]',
        'email_data["ai_draft_reply"] = latest_ai["ai_draft_reply"]',
        'email_data["category"] = latest_ai["category"]',
        'email_data["priority"] = latest_ai["priority"]',
        'email_data["ai_confidence"] = latest_ai["ai_confidence"]',
        'email_data["requires_review"] = latest_ai["requires_review"]',
        'email_data["review_reason"] = latest_ai["review_reason"]',
        'email_data["knowledge_used"] = reply_sources["knowledge_used"]',
        'email_data["historical_examples"] = reply_sources["historical_examples"]',
    ]:
        check(f"template-facing assignment preserved: {expected}", expected in body)


def test_view_email_template_response_unchanged():
    body = _view_email_body()
    check('renders "email_detail.html" with the same 4 template variables as before',
          all(s in body for s in [
              '"email_detail.html"', '"request": request', '"email": email_data',
              '"conversation": conversation', '"school_email": school_email', '"attachments": attachments',
          ]))


def test_main_py_operational_logs_still_present():
    """P0-6 (already-reviewed safe logging) is untouched by this sprint -
    same markers test_p0_fixes.py already checks for VIEW_EMAIL START."""
    src = _read_main_source()
    for safe_marker in ["VIEW_EMAIL START", "Loaded email: id=", "Loaded thread: thread_present="]:
        check(f'safe operational log "{safe_marker}" still present', safe_marker in src)


def test_dashboard_data_route_untouched():
    """This sprint did not touch /dashboard-data - it already only called
    get_emails() (no combined/separate COUNT distinction visible to it) and
    already built its own whitelisted response dict, so get_emails()'s
    internal round-trip change is fully transparent to it."""
    src = _read_main_source()
    start = src.find('@app.get("/dashboard-data")')
    end = src.find('@app.get("/category/{category}")')
    body = src[start:end]
    check('dashboard-data still calls get_emails() with the same parameters',
          "get_emails(source=source, search=q, status=status, date_from=date_from, date_to=date_to, "
          "page=page, page_size=page_size, read_status=read_status)" in body)
    check("dashboard-data still returns the same whitelisted per-email fields",
          all(f'"{k}":' in body for k in [
              "id", "subject", "sender", "source", "category", "priority",
              "status", "created_at", "is_read", "has_attachment",
          ]))
    check("dashboard-data still returns the same top-level response keys",
          all(f'"{k}":' in body for k in [
              "emails", "total", "needs_review_count", "auto_reply_count",
              "current_page", "total_pages", "page_size",
          ]))


# ---------------------------------------------------------------------------
# C) Tailwind duplicate-script investigation.
#
# The audit's premise ("dashboard.html loads a second Tailwind compiler even
# though base.html already loads one") does not hold up under inspection:
# dashboard.html is a fully standalone document (own <html>/<head>/<body>,
# no {% extends %}) and no template anywhere extends base.html, so
# base.html's script is never loaded on the dashboard page at all.
# dashboard.html was already loading Tailwind exactly once before this
# sprint. No script was removed, since there was no actual duplicate to
# remove without breaking the page's styling entirely. These tests document
# that finding rather than a code change.
# ---------------------------------------------------------------------------

def _read_templates_source(name):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", name)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def test_dashboard_html_loads_tailwind_exactly_once():
    src = _read_templates_source("dashboard.html")
    tailwind_script_count = src.count("cdn.tailwindcss.com") + src.count("@tailwindcss/browser")
    check("dashboard.html loads exactly one Tailwind CDN script (no duplicate - none existed to remove)",
          tailwind_script_count == 1, f"found {tailwind_script_count}")


def test_dashboard_html_does_not_extend_base_html():
    src = _read_templates_source("dashboard.html")
    check("dashboard.html is a standalone document, not a {% extends \"base.html\" %} child "
          "(confirms base.html's own Tailwind script is irrelevant to this page)",
          "{% extends" not in src)


def test_no_template_extends_base_html():
    """If nothing in the whole app extends base.html, base.html's script tag
    is dead/orphaned - never actually loaded on any real page - which is
    exactly why grepping both files in isolation (as the source audit did)
    suggested a duplicate that isn't real on any single rendered page."""
    templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
    extending_files = []
    for fname in os.listdir(templates_dir):
        if not fname.endswith(".html"):
            continue
        with open(os.path.join(templates_dir, fname), "r", encoding="utf-8") as f:
            if "{% extends \"base.html\" %}" in f.read() or "{% extends 'base.html' %}" in f.read():
                extending_files.append(fname)
    check("no template in the app extends base.html", extending_files == [],
          f"found: {extending_files}")


def main():
    test_get_emails_combined_query_used_when_rows_found()
    test_get_emails_zero_matching_rows()
    test_get_emails_page_beyond_last_page_falls_back_correctly()
    test_get_emails_preserves_filters_search_and_order()
    test_get_emails_replied_status_drops_gmail_manual_filter()

    test_view_email_redundant_select_is_read_removed()
    test_view_email_four_lookups_run_through_threadpoolexecutor()
    test_view_email_preserves_thread_id_and_message_id_guards()
    test_view_email_result_merge_logic_unchanged()
    test_view_email_template_response_unchanged()
    test_main_py_operational_logs_still_present()
    test_dashboard_data_route_untouched()

    test_dashboard_html_loads_tailwind_exactly_once()
    test_dashboard_html_does_not_extend_base_html()
    test_no_template_extends_base_html()

    if _failures:
        print(f"\n{len(_failures)} FAILURE(S): {_failures}")
        sys.exit(1)
    else:
        print("\nAll tests passed.")


if __name__ == "__main__":
    main()
