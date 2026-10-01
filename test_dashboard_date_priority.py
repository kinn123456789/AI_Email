"""Focused tests for the dashboard date-first grouping + priority filter
feature (database.get_emails()'s new date-then-priority ORDER BY, the
`priority` filter param, the viewer-timezone plumbing, and the
TODAY/YESTERDAY/date-label + is_new_date_group per-row fields main.py and
templates/dashboard.html both consume).

Matches this repo's existing test_*.py convention (see test_performance_fixes.py,
test_review_reasons.py): a plain script using only assert statements and the
standard library plus whatever's already installed - no pytest. A new,
separate file rather than touching the existing suites.

THREE KINDS OF CHECK, SAME SPLIT AS test_performance_fixes.py:

1. database.py's get_emails()/_compute_date_label()/_sanitize_timezone() are
   checked with REAL imports against the same fake psycopg2/dotenv
   infrastructure the other test files already establish - a QueuePool fake
   cursor (identical technique to test_performance_fixes.py) so the
   pagination-fallback branch can be exercised with realistic, distinct
   results at each step.

2. main.py's /dashboard and /dashboard-data routes can't be imported (starts
   real scheduler.py background jobs, needs fastapi/apscheduler) - checked
   via source-presence checks against the real file, same technique every
   other test file touching main.py already uses.

3. templates/dashboard.html (the priority <select>, the tz cookie script,
   the Jinja/JS date-group header insertion) is checked via direct source
   inspection, same technique test_review_reasons.py already uses for this
   exact file.

Run with: python3 test_dashboard_date_priority.py
"""

import datetime
import inspect
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
# Fake infrastructure - identical technique to test_performance_fixes.py.
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
    global _pool
    _pool = QueuePool()
    database.db_pool = _pool


def _fake_row(id_, **overrides):
    row = {
        "id": id_, "sender": "parent@example.com", "subject": "s", "source": "support@coralacademy.com",
        "category": "General", "priority": "Medium", "status": "Needs Review", "reply_type": "automatic",
        "created_at": None, "first_reply_at": None, "resolved_at": None, "knowledge_url": None,
        "ai_confidence": 0.9, "ai_summary": "sum", "ai_draft_reply": "draft", "requires_review": True,
        "review_reason": None, "is_read": False, "has_attachment": False,
        "effective_ts": None, "local_date": None, "viewer_today": None,
    }
    row.update(overrides)
    return row


def _read_source(filename):
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), filename), "r", encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# 1. _compute_date_label() - pure function, no DB needed. This is the same
# logic that decides both the Jinja and the JS auto-refresh header text, so
# testing it directly here covers both rendering paths at once.
# ---------------------------------------------------------------------------

def test_date_label_today_yesterday_older():
    today = datetime.date(2026, 9, 29)
    check('today -> "TODAY · Sep 29"',
          database._compute_date_label(datetime.date(2026, 9, 29), today) == "TODAY · Sep 29")
    check('yesterday -> "YESTERDAY · Sep 28"',
          database._compute_date_label(datetime.date(2026, 9, 28), today) == "YESTERDAY · Sep 28")
    check('two days ago, same year -> "Sep 27" (no TODAY/YESTERDAY prefix)',
          database._compute_date_label(datetime.date(2026, 9, 27), today) == "Sep 27")
    check('a date from a prior year -> year is appended ("Sep 27, 2024")',
          database._compute_date_label(datetime.date(2024, 9, 27), today) == "Sep 27, 2024")
    check("a None local_date returns None rather than raising",
          database._compute_date_label(None, today) is None)
    check("a None viewer_today returns None rather than raising",
          database._compute_date_label(datetime.date(2026, 9, 29), None) is None)


# ---------------------------------------------------------------------------
# 2/3/4. Default ordering, per-priority filtering, unknown-priority safety.
# ---------------------------------------------------------------------------

def test_default_order_is_date_then_priority_then_time():
    """Scenario 1 (default ordering) + scenario 12 (unknown priority never
    crashes, and gets a sensible fallback tier) as one structural check on
    the actual ORDER BY text - a live DB isn't available in this sandbox
    (see this file's own docstring), so the SQL fragments are the
    authoritative check, matching every other test file's approach to
    database.py in this repo."""
    _reset_pool()
    _pool.fetchall_queue.append([_fake_row(1, total=1, needs_review_count=0, auto_reply_count=0)])

    database.get_emails(page=1, page_size=50)

    sql = _pool.sql_log[0]
    order_by = sql[sql.index("ORDER BY"):]

    check("date (local_date) is the primary sort key", "local_date DESC" in order_by)
    check("priority is the secondary sort key, in Urgent->High->Medium->Low->unknown order",
          "CASE priority" in order_by
          and "WHEN 'Urgent' THEN 1" in order_by
          and "WHEN 'High' THEN 2" in order_by
          and "WHEN 'Medium' THEN 3" in order_by
          and "WHEN 'Low' THEN 4" in order_by
          and "ELSE 5" in order_by)
    check("local_date appears before the priority CASE in the ORDER BY text",
          order_by.index("local_date DESC") < order_by.index("CASE priority"))
    check("the priority CASE appears before the final time tiebreaker",
          order_by.index("CASE priority") < order_by.index("effective_ts DESC"))
    check("newest-first is the final tiebreaker (effective_ts DESC)", "effective_ts DESC" in order_by)
    check("is_read/status are no longer sort keys (intentionally replaced, per approved design)",
          "is_read ASC" not in order_by and "CASE status" not in order_by)


def test_priority_filter_high_medium_low_urgent_and_all():
    """Scenarios 2, 3, 4 (High/Medium/Low filters) plus Urgent and All."""
    for value in ["Urgent", "High", "Medium", "Low"]:
        _reset_pool()
        _pool.fetchall_queue.append([_fake_row(1, total=1, needs_review_count=0, auto_reply_count=0, priority=value)])
        database.get_emails(priority=value, page=1, page_size=50)
        sql = _pool.sql_log[0]
        params = _pool.params_log[0]
        check(f'priority="{value}" adds "AND priority = %s" to the query', "AND priority = %s" in sql)
        check(f'priority="{value}" is present in the bound params (never string-interpolated)', value in params)
        check(f'priority="{value}": the literal value never appears inline in the SQL text',
              f"priority = '{value}'" not in sql)

    _reset_pool()
    _pool.fetchall_queue.append([_fake_row(1, total=1, needs_review_count=0, auto_reply_count=0)])
    database.get_emails(priority=None, page=1, page_size=50)
    check('priority=None ("All") adds no priority filter', "AND priority = %s" not in _pool.sql_log[0])

    _reset_pool()
    _pool.fetchall_queue.append([_fake_row(1, total=1, needs_review_count=0, auto_reply_count=0)])
    database.get_emails(priority="", page=1, page_size=50)
    check('priority="" ("All") adds no priority filter either', "AND priority = %s" not in _pool.sql_log[0])


def test_unknown_priority_value_does_not_crash():
    """Scenario 12: an unrecognized priority value must not raise - it's
    passed through as a normal (if unmatched) filter value, exactly like
    source/status already behave for any value this app didn't anticipate.
    The ORDER BY's own CASE...ELSE 5 (checked above) already gives any
    unknown/NULL priority a sensible fallback position rather than crashing
    or being silently dropped."""
    _reset_pool()
    _pool.fetchall_queue.append([_fake_row(1, total=1, needs_review_count=0, auto_reply_count=0, priority="Bogus")])
    try:
        result = database.get_emails(priority="Bogus", page=1, page_size=50)
        crashed = False
    except Exception as e:
        crashed = True
        result = None
    check("an unrecognized priority filter value does not raise", not crashed)
    if not crashed:
        check("it's still applied as a normal (if unmatched) filter", "AND priority = %s" in _pool.sql_log[0])


def test_same_date_and_priority_orders_newest_first():
    """Scenario 6: within the same date+priority, effective_ts DESC (the
    final ORDER BY key, checked structurally above) is exactly the
    email_date-with-created_at-fallback precedence the pre-existing
    ordering already used for its own final tiebreaker - unchanged
    semantics, just now also serving the within-day/within-priority case."""
    _reset_pool()
    _pool.fetchall_queue.append([_fake_row(1, total=1, needs_review_count=0, auto_reply_count=0)])
    database.get_emails(page=1, page_size=50)
    sql = _pool.sql_log[0]
    check("effective_ts is COALESCE(email_date, created_at AT TIME ZONE 'UTC') - same fallback precedence as before",
          "COALESCE(email_date, created_at AT TIME ZONE 'UTC') AS effective_ts" in sql)


# ---------------------------------------------------------------------------
# 5. Search + priority filter work together.
# ---------------------------------------------------------------------------

def test_search_and_priority_filter_combine():
    _reset_pool()
    _pool.fetchall_queue.append([_fake_row(1, total=1, needs_review_count=0, auto_reply_count=0, priority="High")])

    database.get_emails(search="finance", priority="High", page=1, page_size=50)

    sql = _pool.sql_log[0]
    params = _pool.params_log[0]
    check('both "AND priority = %s" and the search ILIKE fragment are present together',
          "AND priority = %s" in sql and "AND (subject ILIKE %s OR sender ILIKE %s OR body ILIKE %s)" in sql)
    check('"High" and the search wildcard are both present in the bound params',
          "High" in params and "%finance%" in params)
    check("date-first ordering is unaffected by adding search+priority together",
          "local_date DESC" in sql and "CASE priority" in sql)


# ---------------------------------------------------------------------------
# 6. Pagination: counts/page/total_pages remain correct, including on the
# fallback (page-past-last-page) branch, which also gets the new
# tz/date-label columns.
# ---------------------------------------------------------------------------

def test_pagination_counts_unaffected_by_date_grouping():
    _reset_pool()
    # First attempt (page 5) comes back empty - past the real last page.
    _pool.fetchall_queue.append([])
    _pool.fetchone_queue.append({"total": 137, "needs_review_count": 40, "auto_reply_count": 30})
    _fallback_local_date = datetime.date(2026, 9, 27)
    _pool.fetchall_queue.append([
        _fake_row(i, local_date=_fallback_local_date, viewer_today=_fallback_local_date)
        for i in range(1, 38)
    ])

    result = database.get_emails(page=5, page_size=50)

    check("3 round trips for the fallback path (combined attempt, COUNT, re-select) - unchanged shape",
          len(_pool.sql_log) == 3, f"got {len(_pool.sql_log)}")
    check("page is clamped to the real last page (3)", result["page"] == 3)
    check("total_pages computed correctly (137 / 50 -> 3 pages)", result["total_pages"] == 3)
    check("total reflects the true total, not the empty first attempt", result["total"] == 137)
    check("rows come from the corrected, re-run SELECT", len(result["rows"]) == 37)
    check("the fallback re-select also requests local_date/viewer_today (tz-aware grouping still works on this path)",
          "AS local_date" in _pool.sql_log[2] and "AS viewer_today" in _pool.sql_log[2])
    check("the fallback re-select's tz params are still the leading two bound params",
          _pool.params_log[2][:2] == ["UTC", "UTC"])
    check("every row on the fallback path still got a date_label computed",
          all(r["date_label"] is not None for r in result["rows"]))


def test_no_additional_per_row_queries():
    """Scenario 13: the common (in-range page) case must still resolve in
    exactly one round trip - date grouping/priority filtering/viewer
    timezone add columns and params to that SAME query, never a second
    query per row or per request."""
    _reset_pool()
    rows = [_fake_row(i, total=3, needs_review_count=1, auto_reply_count=1) for i in range(1, 4)]
    _pool.fetchall_queue.append(rows)

    database.get_emails(priority="High", viewer_timezone="America/Los_Angeles", page=1, page_size=50)

    check("exactly one DB round trip even with priority filter + a real viewer timezone set",
          len(_pool.sql_log) == 1, f"got {len(_pool.sql_log)}")


# ---------------------------------------------------------------------------
# is_new_date_group / date_label wiring on the returned rows themselves.
# ---------------------------------------------------------------------------

def test_is_new_date_group_wiring():
    _reset_pool()
    today = datetime.date(2026, 9, 29)
    rows = [
        _fake_row(1, total=3, needs_review_count=0, auto_reply_count=0, local_date=today, viewer_today=today),
        _fake_row(2, total=3, needs_review_count=0, auto_reply_count=0, local_date=today, viewer_today=today),
        _fake_row(3, total=3, needs_review_count=0, auto_reply_count=0,
                  local_date=datetime.date(2026, 9, 28), viewer_today=today),
    ]
    _pool.fetchall_queue.append(rows)

    result = database.get_emails(page=1, page_size=50)
    out = result["rows"]

    check("row 1 (first row) starts a new date group", out[0]["is_new_date_group"] is True)
    check('row 1 gets the "TODAY" label', out[0]["date_label"] == "TODAY · Sep 29")
    check("row 2 (same date as row 1) does NOT start a new group", out[1]["is_new_date_group"] is False)
    check("row 3 (a different date) DOES start a new group", out[2]["is_new_date_group"] is True)
    check('row 3 gets the "YESTERDAY" label', out[2]["date_label"] == "YESTERDAY · Sep 28")
    check("internal-only columns (local_date/viewer_today/effective_ts) are stripped from the returned rows",
          all("local_date" not in r and "viewer_today" not in r and "effective_ts" not in r for r in out))


def test_first_row_of_every_page_starts_a_new_group():
    """Documented, intentional pagination behavior: a date group spanning
    two pages shows its header again on page two, rather than get_emails()
    ever fetching extra rows across a page boundary just to avoid it."""
    _reset_pool()
    today = datetime.date(2026, 9, 29)
    rows = [_fake_row(1, total=51, needs_review_count=0, auto_reply_count=0, local_date=today, viewer_today=today)]
    _pool.fetchall_queue.append(rows)

    result = database.get_emails(page=2, page_size=50)
    check("the first row returned on page 2 still starts a new group, even mid-date",
          result["rows"][0]["is_new_date_group"] is True)


# ---------------------------------------------------------------------------
# _sanitize_timezone(): defends the SQL layer against a malformed/tampered
# `tz` cookie value without ever needing a real IANA lookup.
# ---------------------------------------------------------------------------

def test_sanitize_timezone():
    check("a real IANA zone passes through unchanged",
          database._sanitize_timezone("America/Los_Angeles") == "America/Los_Angeles")
    check('"UTC" passes through unchanged', database._sanitize_timezone("UTC") == "UTC")
    check("a 3-segment zone (e.g. America/Argentina/Buenos_Aires) passes through unchanged",
          database._sanitize_timezone("America/Argentina/Buenos_Aires") == "America/Argentina/Buenos_Aires")
    check("None falls back to UTC", database._sanitize_timezone(None) == "UTC")
    check('"" falls back to UTC', database._sanitize_timezone("") == "UTC")
    check("a SQL-injection-shaped value falls back to UTC",
          database._sanitize_timezone("UTC'; DROP TABLE messages; --") == "UTC")
    check("a value containing whitespace falls back to UTC",
          database._sanitize_timezone("not a zone") == "UTC")
    check("get_emails() itself defaults viewer_timezone to UTC when not passed",
          inspect.signature(database.get_emails).parameters["viewer_timezone"].default == "UTC")


def test_viewer_timezone_reaches_the_query_params():
    _reset_pool()
    _pool.fetchall_queue.append([_fake_row(1, total=1, needs_review_count=0, auto_reply_count=0)])
    database.get_emails(viewer_timezone="America/Los_Angeles", page=1, page_size=50)
    params = _pool.params_log[0]
    check("a real viewer timezone is used for both AT TIME ZONE params (local_date and viewer_today)",
          params[0] == "America/Los_Angeles" and params[1] == "America/Los_Angeles")

    _reset_pool()
    _pool.fetchall_queue.append([_fake_row(1, total=1, needs_review_count=0, auto_reply_count=0)])
    database.get_emails(viewer_timezone="not a zone; DROP TABLE messages;", page=1, page_size=50)
    check("a malformed viewer timezone is sanitized to UTC before ever reaching the query",
          _pool.params_log[0][0] == "UTC" and _pool.params_log[0][1] == "UTC")


# ---------------------------------------------------------------------------
# 8/9. Existing review_reason visibility and priority-assignment logic
# untouched by this task.
# ---------------------------------------------------------------------------

def test_review_reason_fields_still_present():
    _reset_pool()
    _pool.fetchall_queue.append([_fake_row(1, total=1, needs_review_count=0, auto_reply_count=0,
                                            requires_review=True, review_reason="classifier")])
    result = database.get_emails(page=1, page_size=50)
    row = result["rows"][0]
    check("requires_review is still present and unchanged", row["requires_review"] is True)
    check("review_reason is still present and unchanged", row["review_reason"] == "classifier")


def test_priority_assignment_logic_files_untouched():
    """Scenario 11 + this task's own explicit constraints: no AI/classifier/
    RAG/generation/safety/prompt/scheduler file may have changed. Checked
    via git diff, scoped only to the files THIS task must never touch (not
    a brittle exact-set pin like test_email_reader_batch_duplicate_check.py's
    own unrelated, pre-existing scope guard for a different task, which is
    left alone - see this session's final report).

    live_class_intent.py and coral_class_catalog.py are no longer checked
    here for the same reason database.py/main.py were previously retired
    from similar guards elsewhere in this session: the live-class
    parent-facing context cleanup (another later, separately-approved
    task - removing url_slug from the LLM context and formatting booleans
    as Yes/No) legitimately touches exactly these two files, and only
    these two.

    reply_generator.py is retired from this list for the same reason,
    one task later still: the generation-latency reasoning-token
    observability task adds a small, defensive, print-only
    reasoning_tokens extraction there (no model/temperature/prompt/RAG/
    safety change) - legitimately touching exactly that one file.

    vector_search.py is retired from this list for the same reason, later
    still: the mailbox history onboarding fix replaces its fixed 3-address
    STAFF_EMAIL_ADDRESSES constant with a small TTL-cached list derived
    from database.get_all_email_accounts() - a retrieval-eligibility change
    only (same SQL, same similarity/rerank/limit/is_unedited_ai_reply
    behavior), not an AI/classifier/RAG/generation/safety/prompt/scheduler
    change, and legitimately touching exactly that one file in this area.

    ai_classifier.py/rag_reranker.py/email_reader.py are retired from this
    list for the same reason, later still: the final pre-freeze reliability
    fixes (1) raise email_reader.py's hardcoded mailbox-worker-pool capacity
    from 3 to 4, and (2) add an explicit, conservative request timeout to
    every OpenAI/OpenRouter client construction across 9 files (including
    these two) via a new shared llm_client_config.py constant - neither
    changes any model, prompt, temperature, retrieval behavior, or
    generation/safety logic. teacher_reply_generator1.py/process_email.py/
    prompt_builder.py/knowledge_search.py/scheduler.py all remain untouched
    by every task above and are still checked below."""
    import subprocess
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    result = subprocess.run(
        ["git", "diff", "--name-only"],
        cwd=repo_dir, capture_output=True, text=True, check=True,
    )
    changed = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    for forbidden in [
        "process_email.py", "prompt_builder.py",
        "teacher_reply_generator1.py",
        "knowledge_search.py",
        "scheduler.py",
    ]:
        check(f"{forbidden} was not modified by this task", forbidden not in changed)


# ---------------------------------------------------------------------------
# main.py wiring (source-presence checks - main.py isn't importable here,
# same limitation every other test file touching it already documents).
# ---------------------------------------------------------------------------

def test_main_py_dashboard_route_wiring():
    src = _read_source("main.py")
    start = src.find('@app.get("/dashboard")')
    end = src.find('@app.get("/dashboard/sent")')
    body = src[start:end]
    check('"priority: str = None" is a parameter of the /dashboard route', "priority: str = None" in body)
    check("the viewer timezone is resolved from the request and passed through",
          "_resolve_viewer_timezone(request)" in body and "viewer_timezone=viewer_timezone" in body)
    check("priority is passed through to get_emails()", "priority=priority" in body)
    check('"selected_priority": priority is in the template context', '"selected_priority": priority' in body)


def test_main_py_dashboard_data_route_wiring():
    src = _read_source("main.py")
    start = src.find('@app.get("/dashboard-data")')
    end = src.find('@app.get("/category/{category}")')
    body = src[start:end]
    check("/dashboard-data now takes a `request: Request` param (needed to read the tz cookie)",
          "def dashboard_data(request: Request" in body)
    check('"priority: str = None" is a parameter of the /dashboard-data route', "priority: str = None" in body)
    check("the viewer timezone is resolved from the request and passed through",
          "_resolve_viewer_timezone(request)" in body and "viewer_timezone=viewer_timezone" in body)
    check("priority is passed through to get_emails()", "priority=priority" in body)
    check('date_label is included in the per-email JSON response', '"date_label": e["date_label"]' in body)
    check('is_new_date_group is included in the per-email JSON response',
          '"is_new_date_group": e["is_new_date_group"]' in body)


def test_resolve_viewer_timezone_helper():
    src = _read_source("main.py")
    check("_resolve_viewer_timezone() reads the `tz` cookie", 'request.cookies.get(_TIMEZONE_COOKIE_NAME)' in src)
    check('_resolve_viewer_timezone() falls back to "UTC" when the cookie is absent',
          'request.cookies.get(_TIMEZONE_COOKIE_NAME) or "UTC"' in src)


# ---------------------------------------------------------------------------
# templates/dashboard.html wiring.
# ---------------------------------------------------------------------------

def test_dashboard_html_priority_select():
    src = _read_source("templates/dashboard.html")
    check('a <select name="priority"> exists', '<select name="priority" onchange="this.form.submit()"' in src)
    for label, value in [("All Priorities", ""), ("Urgent", "Urgent"), ("High", "High"),
                          ("Medium", "Medium"), ("Low", "Low")]:
        check(f'priority option "{label}" is present',
              f'<option value="{value}"' in src and f">{label}</option>" in src)
    check('the "Clear" link condition includes selected_priority',
          "selected_read_status or selected_priority" in src)
    check("base_qs (pagination links) now includes priority",
          "'priority': selected_priority or ''" in src)


def test_dashboard_html_tz_cookie_script():
    src = _read_source("templates/dashboard.html")
    check("the browser IANA timezone is read via Intl.DateTimeFormat()",
          "Intl.DateTimeFormat().resolvedOptions().timeZone" in src)
    check('it is written to a "tz" cookie', 'document.cookie = "tz="' in src)
    check("the cookie-setting script comes right after local-time.js (runs on every page load)",
          src.index('<script src="/static/local-time.js"></script>') < src.index("Intl.DateTimeFormat"))
    check("a failure (Intl unsupported / cookies blocked) is caught and silently ignored, never breaks the page",
          "catch (e)" in src and "keeps working with" in src)


def test_dashboard_html_date_group_header_jinja_and_js():
    src = _read_source("templates/dashboard.html")
    check("the Jinja row loop inserts a header row when is_new_date_group is true",
          "{% if email.is_new_date_group %}" in src)
    check("the Jinja header row spans all 8 columns", 'colspan="8"' in src)
    check("the JS auto-refresh path has a matching dateGroupHeaderHtml() helper",
          "function dateGroupHeaderHtml(label)" in src)
    check("the JS header also spans all 8 columns", "colspan=\"8\"" in src and "dateGroupHeaderHtml" in src)
    check("refreshDashboard() now builds rows via buildRowsHtml() (grouping-aware), not a bare .map(buildRowHtml)",
          "tbody.innerHTML = buildRowsHtml(data.emails);" in src
          and "tbody.innerHTML = data.emails.map(buildRowHtml).join" not in src)
    check("buildRowsHtml() defers to the same is_new_date_group/date_label fields the server computed",
          "email.is_new_date_group ? dateGroupHeaderHtml(email.date_label)" in src)


def test_dashboard_html_auto_refresh_mechanism_untouched():
    """Scenario 9: the auto-refresh preserving the selected priority filter
    is a direct, zero-extra-code consequence of the pre-existing
    fetch("/dashboard-data" + window.location.search) call (already
    reflects the current URL's full query string, priority included, since
    priority is a normal <select> inside the same GET filterForm) - so the
    fix here is confirming that mechanism itself is still exactly intact,
    not reinventing it."""
    src = _read_source("templates/dashboard.html")
    check('fetch("/dashboard-data" + window.location.search) is unchanged',
          'fetch("/dashboard-data" + window.location.search)' in src)
    form_start = src.index('id="filterForm"')
    form_end = src.index("</form>", form_start)
    check("the priority <select> lives inside the same #filterForm as every other filter",
          form_start < src.index('<select name="priority"') < form_end)
    check("the auto-refresh interval itself is unchanged (still 8 seconds)", "setInterval(refreshDashboard, 8000);" in src)


def main():
    tests = [
        test_date_label_today_yesterday_older,
        test_default_order_is_date_then_priority_then_time,
        test_priority_filter_high_medium_low_urgent_and_all,
        test_unknown_priority_value_does_not_crash,
        test_same_date_and_priority_orders_newest_first,
        test_search_and_priority_filter_combine,
        test_pagination_counts_unaffected_by_date_grouping,
        test_no_additional_per_row_queries,
        test_is_new_date_group_wiring,
        test_first_row_of_every_page_starts_a_new_group,
        test_sanitize_timezone,
        test_viewer_timezone_reaches_the_query_params,
        test_review_reason_fields_still_present,
        test_priority_assignment_logic_files_untouched,
        test_main_py_dashboard_route_wiring,
        test_main_py_dashboard_data_route_wiring,
        test_resolve_viewer_timezone_helper,
        test_dashboard_html_priority_select,
        test_dashboard_html_tz_cookie_script,
        test_dashboard_html_date_group_header_jinja_and_js,
        test_dashboard_html_auto_refresh_mechanism_untouched,
    ]
    for t in tests:
        t()

    if _failures:
        print(f"\n{len(_failures)} FAILURE(S): {_failures}")
        sys.exit(1)
    print("\nAll tests passed.")


if __name__ == "__main__":
    main()
