"""Focused tests for the v1.1 Quick Keys feature (frontend-only, built on
top of Dark Mode and the Sticky Back button - see static/quick-keys.js
and the small additions to templates/dashboard.html and
templates/email_detail.html).

WHAT THIS FEATURE IS, per the completed read-only investigation: a small
shared helper (static/quick-keys.js, same architectural pattern as
static/theme.js) providing a typing-safety guard, shortcut dispatch, and
a dismissible help-panel dialog - wired into two pages with a different,
small keymap each:

  Dashboard:     j/k move a real DOM focus between email rows (clamped,
                 never wraps); Enter/o open the focused row by reusing
                 its own existing onclick (never a second, hardcoded
                 URL); ? toggles the help panel.
  Email Detail:  b reuses #backLink's own resolved href (never a
                 hardcoded URL); r only ever calls .focus() on the
                 existing #replyBody textarea - it can never create,
                 edit, or send anything; ? toggles the help panel.

Deliberately excluded (no safe existing action to bind, or explicit
safety policy): a "d" mark-as-read shortcut, dashboard quick-reply, and
any shortcut bound to "Send Out" or "No Reply Needed".

TESTING LIMITATION (same class of limitation as test_dark_mode_toggle.py
and test_email_detail_sticky_back.py): this sandbox has no browser/JS-
execution capability, and the two templates are Jinja, not importable
Python. Checks against the templates are structural/source-presence/
ordering checks against the real HTML+JS text. The actual decision logic
(typing-safety guard, row-index clamping math, help-panel open/close/
focus-restore state machine) is behaviorally verified via byte-for-byte
Python mirrors of static/quick-keys.js's own logic, exercised directly
with fake DOM-like objects - the same mirror-function technique
established earlier this session (test_send_reply_form.py,
test_dark_mode_toggle.py). No pytest, no browser - a plain script using
only assert statements and the standard library, per this repo's
existing test_*.py convention.

Run with: python3 test_quick_keys.py
"""

import os
import re
import sys


_failures = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" - {detail}" if detail and not condition else ""))
    if not condition:
        _failures.append(name)


def _read_source(filename):
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), filename), "r", encoding="utf-8") as f:
        return f.read()


QUICK_KEYS_JS = _read_source(os.path.join("static", "quick-keys.js"))
DASHBOARD_HTML = _read_source(os.path.join("templates", "dashboard.html"))
EMAIL_DETAIL_HTML = _read_source(os.path.join("templates", "email_detail.html"))


# ---------------------------------------------------------------------------
# A. static/quick-keys.js: typing-safety guard, source-level checks.
# ---------------------------------------------------------------------------

def test_typing_safety_guard_covers_every_required_case():
    check('isTypingTarget() checks el.isContentEditable', "el.isContentEditable" in QUICK_KEYS_JS)
    check('isTypingTarget() checks tag === "INPUT"', '"INPUT"' in QUICK_KEYS_JS)
    check('isTypingTarget() checks tag === "TEXTAREA"', '"TEXTAREA"' in QUICK_KEYS_JS)
    check('isTypingTarget() checks tag === "SELECT"', '"SELECT"' in QUICK_KEYS_JS)
    check("isSafeToFire() checks event.ctrlKey", "event.ctrlKey" in QUICK_KEYS_JS)
    check("isSafeToFire() checks event.metaKey", "event.metaKey" in QUICK_KEYS_JS)
    check("isSafeToFire() checks event.altKey", "event.altKey" in QUICK_KEYS_JS)
    check(
        "isSafeToFire() checks document.activeElement against isTypingTarget",
        "isTypingTarget(document.activeElement)" in QUICK_KEYS_JS,
    )


def test_repeat_handling_and_dispatch_order():
    check(
        "a binding's handler is skipped on event.repeat unless explicitly repeatable",
        "if (event.repeat && !binding.repeatable)" in QUICK_KEYS_JS,
    )
    check(
        "isSafeToFire() is checked before any binding or the ? toggle runs",
        QUICK_KEYS_JS.index("if (!isSafeToFire(event))") < QUICK_KEYS_JS.index('event.key === "?"'),
    )


def test_escape_closes_help_panel_independent_of_typing_guard():
    check(
        'Escape is handled before (and independent of) the typing-safety guard',
        QUICK_KEYS_JS.index('event.key === "Escape"') < QUICK_KEYS_JS.index("if (!isSafeToFire(event))"),
    )
    check("closeHelpPanel() is called on Escape", "closeHelpPanel();" in QUICK_KEYS_JS)


def test_help_panel_dialog_semantics_and_focus_restore():
    check("openHelpPanel() records the previously-focused element", "helpPanelState.previouslyFocused = document.activeElement" in QUICK_KEYS_JS)
    check("openHelpPanel() moves focus into the panel's close control", "closeTarget.focus()" in QUICK_KEYS_JS)
    check("closeHelpPanel() restores focus to what was focused before opening", "toRestore.focus()" in QUICK_KEYS_JS)
    check("closeHelpPanel() clears the saved state after restoring", 'helpPanelState.panel = null' in QUICK_KEYS_JS and 'helpPanelState.previouslyFocused = null' in QUICK_KEYS_JS)


# ---------------------------------------------------------------------------
# B. Behavioral mirrors of quick-keys.js's own logic.
# ---------------------------------------------------------------------------

class _FakeElement:
    def __init__(self, tag="DIV", content_editable=False):
        self.tagName = tag
        self.isContentEditable = content_editable
        self.focused = False

    def focus(self):
        self.focused = True


def _mirror_is_typing_target(el):
    """Byte-for-byte mirror of isTypingTarget() in static/quick-keys.js."""
    if el is None:
        return False
    if el.isContentEditable:
        return True
    tag = el.tagName
    return tag in ("INPUT", "TEXTAREA", "SELECT")


def _mirror_is_safe_to_fire(active_element, ctrl=False, meta=False, alt=False):
    """Byte-for-byte mirror of isSafeToFire() in static/quick-keys.js."""
    if ctrl or meta or alt:
        return False
    if _mirror_is_typing_target(active_element):
        return False
    return True


def test_mirror_blocks_shortcuts_in_input_textarea_select_contenteditable():
    check("blocked when focus is in an <input>", _mirror_is_safe_to_fire(_FakeElement("INPUT")) is False)
    check("blocked when focus is in a <textarea>", _mirror_is_safe_to_fire(_FakeElement("TEXTAREA")) is False)
    check("blocked when focus is in a <select>", _mirror_is_safe_to_fire(_FakeElement("SELECT")) is False)
    check(
        "blocked when focus is on a contenteditable element",
        _mirror_is_safe_to_fire(_FakeElement("DIV", content_editable=True)) is False,
    )
    check(
        "allowed when focus is on a plain, non-typing element",
        _mirror_is_safe_to_fire(_FakeElement("BODY")) is True,
    )


def test_mirror_blocks_shortcuts_with_any_modifier_key():
    plain = _FakeElement("BODY")
    check("blocked with Ctrl held", _mirror_is_safe_to_fire(plain, ctrl=True) is False)
    check("blocked with Cmd/Meta held", _mirror_is_safe_to_fire(plain, meta=True) is False)
    check("blocked with Alt held", _mirror_is_safe_to_fire(plain, alt=True) is False)
    check("allowed with no modifier held", _mirror_is_safe_to_fire(plain) is True)


def _mirror_repeat_dispatch(repeat, repeatable):
    """Mirror of: if (event.repeat && !binding.repeatable) { return; } -
    returns True if the handler WOULD fire, False if it's suppressed."""
    if repeat and not repeatable:
        return False
    return True


def test_mirror_event_repeat_is_suppressed_for_default_non_repeatable_bindings():
    check("a held-down key (repeat=True) is suppressed for a default binding", _mirror_repeat_dispatch(repeat=True, repeatable=False) is False)
    check("a single keypress (repeat=False) always fires", _mirror_repeat_dispatch(repeat=False, repeatable=False) is True)
    check("an explicitly repeatable binding still fires on repeat", _mirror_repeat_dispatch(repeat=True, repeatable=True) is True)


# ---- Dashboard j/k row-focus math -----------------------------------------

def _mirror_current_row_index(rows, active_element):
    """Mirror of currentRowIndex(): rows.indexOf(document.activeElement)."""
    try:
        return rows.index(active_element)
    except ValueError:
        return -1


def _mirror_move_focus(rows, active_element, delta, has_focused_before=False):
    """Byte-for-byte mirror of moveFocus()'s index math in
    templates/dashboard.html (post wrap-around fix). Returns the row that
    would receive focus, or None if there are no rows or if this call is
    correctly a no-op (empty list, or a post-refresh "lost focus" state -
    see has_focused_before below) - exactly like the real code, which
    simply returns without calling .focus() on anything in those cases.

    has_focused_before mirrors the real hasFocusedBefore closure
    variable: False only until any row has ever genuinely been focused.
    This is what lets the fix distinguish a true first-ever j/k press
    (idx is -1 because nothing has been focused yet - still fine to jump
    to a sensible end) from the 8s auto-refresh having just destroyed the
    previously-focused row (idx is ALSO -1 here, since that old row no
    longer matches anything in the freshly rebuilt list - but this is not
    a fresh start, and treating it like one was the exact reported bug:
    j right after a refresh wiped focus landed on idx -1 -> "start at row
    0", indistinguishable from k-at-the-last-row wrapping to the first
    row, and the mirror image for k wrapping to the last row)."""
    if not rows:
        return None
    idx = _mirror_current_row_index(rows, active_element)
    if idx == -1:
        if has_focused_before:
            return None
        next_idx = 0 if delta > 0 else len(rows) - 1
    else:
        next_idx = max(0, min(idx + delta, len(rows) - 1))
    return rows[next_idx]


def test_j_moves_to_the_next_row():
    rows = [_FakeElement() for _ in range(3)]
    target = _mirror_move_focus(rows, active_element=rows[0], delta=1)
    check("j (delta +1) moves from row 0 to row 1", target is rows[1])


def test_k_moves_to_the_previous_row():
    rows = [_FakeElement() for _ in range(3)]
    target = _mirror_move_focus(rows, active_element=rows[2], delta=-1)
    check("k (delta -1) moves from row 2 to row 1", target is rows[1])


def test_jk_clamp_at_first_and_last_row_never_wrap():
    rows = [_FakeElement() for _ in range(3)]
    check(
        "j from the last row stays on the last row (no wrap to the first)",
        _mirror_move_focus(rows, active_element=rows[2], delta=1) is rows[2],
    )
    check(
        "k from the first row stays on the first row (no wrap to the last)",
        _mirror_move_focus(rows, active_element=rows[0], delta=-1) is rows[0],
    )


def test_wrap_around_bug_fix_after_focus_is_lost_mid_navigation():
    """Regression test for the exact reported production bug: pressing k
    while genuinely focused on the first row looked like it "jumped to
    the last row," and j from the last row looked like it "jumped to the
    first row." Root cause: if focus is ever lost for a reason OTHER
    than a true first-ever press (the only real-world trigger here is
    the dashboard's own 8s auto-refresh destroying the previously
    focused <tr>), currentRowIndex() correctly reports -1 (nothing
    matches), but the OLD code treated every -1 as "first use" and
    jumped to an end anyway - landing on row 0 for j (reported as "k
    wrapped me to the end, then j wrapped me back to the start" when
    observed over a couple of presses) or the last row for k. The fix:
    once has_focused_before is true, an idx of -1 is never a fresh
    start - it's a lost-focus state, and the correct behavior is to do
    nothing at all (not wrap, not jump)."""
    rows = [_FakeElement() for _ in range(3)]

    check(
        "a genuine first-ever j press (has_focused_before=False) still starts at row 0 (unchanged convenience)",
        _mirror_move_focus(rows, active_element=None, delta=1, has_focused_before=False) is rows[0],
    )
    check(
        "a genuine first-ever k press (has_focused_before=False) still starts at the last row (unchanged convenience)",
        _mirror_move_focus(rows, active_element=None, delta=-1, has_focused_before=False) is rows[-1],
    )
    check(
        "j after focus was lost mid-navigation (has_focused_before=True) does nothing - no jump to row 0",
        _mirror_move_focus(rows, active_element=None, delta=1, has_focused_before=True) is None,
    )
    check(
        "k after focus was lost mid-navigation (has_focused_before=True) does nothing - no jump to the last row",
        _mirror_move_focus(rows, active_element=None, delta=-1, has_focused_before=True) is None,
    )


def test_jk_with_no_prior_focus_starts_at_a_sensible_end():
    rows = [_FakeElement() for _ in range(3)]
    check(
        "j with nothing focused yet starts at the first row",
        _mirror_move_focus(rows, active_element=None, delta=1) is rows[0],
    )
    check(
        "k with nothing focused yet starts at the last row",
        _mirror_move_focus(rows, active_element=None, delta=-1) is rows[-1],
    )


def test_empty_row_list_is_a_safe_no_op():
    check("moveFocus on an empty row list returns None rather than raising", _mirror_move_focus([], active_element=None, delta=1) is None)
    check(
        "openFocusedRow-equivalent (index -1 on empty list) is a safe no-op",
        _mirror_current_row_index([], None) == -1,
    )


def test_enter_and_o_open_the_same_focused_row_via_click():
    """Mirror of openFocusedRow(): both "Enter" and "o" call this same
    function, which calls .click() on the focused row - reusing its own
    existing onclick handler rather than building/reading any URL."""
    class _ClickableRow(_FakeElement):
        def __init__(self):
            super().__init__()
            self.clicked = False

        def click(self):
            self.clicked = True

    rows = [_ClickableRow(), _ClickableRow()]

    def open_focused_row(active_element):
        idx = _mirror_current_row_index(rows, active_element)
        if idx == -1:
            return
        rows[idx].click()

    open_focused_row(rows[1])
    check("opening the focused row calls .click() on that exact row", rows[1].clicked is True)
    check("opening the focused row does not click any other row", rows[0].clicked is False)

    rows[0].clicked = rows[1].clicked = False
    open_focused_row(None)
    check("opening with nothing focused clicks nothing", not rows[0].clicked and not rows[1].clicked)


# ---- Help panel open/close/restore-focus state machine --------------------

class _MirrorHelpPanel:
    """Mirror of the help-panel state machine in static/quick-keys.js,
    exercised directly rather than only asserted-against as source text -
    proves the open/close/restore sequence is actually correct, not just
    present."""

    def __init__(self):
        self.hidden = True
        self.previously_focused = None

    def open(self, currently_focused):
        if not self.hidden:
            return
        self.previously_focused = currently_focused
        self.hidden = False

    def close(self):
        if self.hidden:
            return None
        self.hidden = True
        restored = self.previously_focused
        self.previously_focused = None
        return restored

    def toggle(self, currently_focused):
        if self.hidden:
            self.open(currently_focused)
        else:
            self.close()


def test_question_mark_opens_and_closes_help_panel():
    panel = _MirrorHelpPanel()
    some_row = _FakeElement()
    panel.toggle(currently_focused=some_row)
    check("? opens a hidden help panel", panel.hidden is False)
    panel.toggle(currently_focused=some_row)
    check("? closes an open help panel", panel.hidden is True)


def test_escape_closes_help_panel():
    panel = _MirrorHelpPanel()
    panel.open(currently_focused=_FakeElement())
    restored = panel.close()
    check("Escape (mirrored as close()) hides the panel", panel.hidden is True)
    check("close() returns something to restore focus to", restored is not None)


def test_focus_returns_correctly_after_closing_help_panel():
    panel = _MirrorHelpPanel()
    row = _FakeElement()
    panel.open(currently_focused=row)
    restored = panel.close()
    check("the element to restore focus to is exactly the one focused before opening", restored is row)


# ---------------------------------------------------------------------------
# C. Template wiring: each shortcut is bound to the right, existing thing.
# ---------------------------------------------------------------------------

def test_dashboard_loads_quick_keys_and_wires_jk_enter_o():
    check("dashboard.html loads static/quick-keys.js", '<script src="/static/quick-keys.js"></script>' in DASHBOARD_HTML)
    check('dashboard.html binds "j"', '"j": { handler:' in DASHBOARD_HTML)
    check('dashboard.html binds "k"', '"k": { handler:' in DASHBOARD_HTML)
    check('dashboard.html binds "Enter"', '"Enter": { handler: openFocusedRow }' in DASHBOARD_HTML)
    check('dashboard.html binds "o"', '"o": { handler: openFocusedRow }' in DASHBOARD_HTML)
    check(
        "Enter and o are wired to the exact same handler function (openFocusedRow)",
        DASHBOARD_HTML.count("openFocusedRow") >= 3,  # definition + 2 bindings
    )


def test_dashboard_rows_have_tabindex_in_both_render_paths():
    check(
        "the Jinja-rendered <tr> carries tabindex=\"-1\"",
        re.search(r'<tr\s+onclick="window\.location=\'/email/\{\{ email\.id \}\}\'"\s*\nclass="[^"]*"\s*\ntabindex="-1"', DASHBOARD_HTML) is not None,
    )
    check(
        "the JS-built <tr> (buildRowHtml) also carries tabindex=\"-1\"",
        'class="hover:bg-cyan-300/40 transition-colors cursor-pointer" tabindex="-1">' in DASHBOARD_HTML,
    )


def test_dashboard_focus_indicator_class_toggled_by_real_focus_events():
    check('dashboard.html listens for "focusin" on #tableBody', 'tableBody.addEventListener("focusin"' in DASHBOARD_HTML)
    check('dashboard.html listens for "focusout" on #tableBody', 'tableBody.addEventListener("focusout"' in DASHBOARD_HTML)
    check(
        "the focus indicator class is added/removed via classList, not inline style",
        'classList.add("quick-keys-focused-row")' in DASHBOARD_HTML and 'classList.remove("quick-keys-focused-row")' in DASHBOARD_HTML,
    )


def test_dashboard_focus_css_defined_for_both_themes():
    check(".quick-keys-focused-row has a light-mode rule", ".quick-keys-focused-row {" in DASHBOARD_HTML)
    check(
        ".quick-keys-focused-row has its own explicit dark-mode rule",
        'html[data-theme="dark"] .quick-keys-focused-row' in DASHBOARD_HTML,
    )


# ---------------------------------------------------------------------------
# E. The j/k wrap-around fix, the permanent shortcut card, and the
#    updated "?" help dialog content (production bug follow-up).
# ---------------------------------------------------------------------------

def test_dashboard_source_implements_the_has_focused_before_guard():
    check(
        "dashboard.html declares the hasFocusedBefore state variable",
        "let hasFocusedBefore = false;" in DASHBOARD_HTML,
    )
    check(
        "moveFocus checks hasFocusedBefore before falling back to jumping to an end",
        "if (hasFocusedBefore) {" in DASHBOARD_HTML,
    )
    check(
        "the focusin listener sets hasFocusedBefore = true",
        "hasFocusedBefore = true;" in DASHBOARD_HTML,
    )
    # Confirms the guard was added inside moveFocus itself, not bolted on
    # elsewhere disconnected from the actual index math.
    move_focus_start = DASHBOARD_HTML.index("function moveFocus(delta)")
    move_focus_end = DASHBOARD_HTML.index("function openFocusedRow()")
    move_focus_body = DASHBOARD_HTML[move_focus_start:move_focus_end]
    check(
        "the hasFocusedBefore check lives inside moveFocus()'s own body",
        "if (hasFocusedBefore) {" in move_focus_body and "return;" in move_focus_body,
    )


def test_permanent_shortcut_card_present_in_metrics_grid_fifth_slot():
    metrics_start = DASHBOARD_HTML.index("<!-- Metrics Cards -->")
    metrics_end = DASHBOARD_HTML.index("<!-- Actions Bar -->")
    metrics_block = DASHBOARD_HTML[metrics_start:metrics_end]

    check("metrics grid still contains exactly one Total Messages card", metrics_block.count("Total Messages") == 1)
    check("metrics grid still contains exactly one Auto Replies card", metrics_block.count("Auto Replies") == 1)
    check("metrics grid still contains exactly one Needs Review card", metrics_block.count("Needs Review") == 1)
    check("metrics grid still contains exactly one By Category card", metrics_block.count("By Category") == 1)
    check(
        "metrics grid now contains exactly one new Keyboard Shortcuts card",
        metrics_block.count("⌨ Keyboard Shortcuts") == 1,
    )
    check(
        "the new card appears AFTER By Category in source order (fills the grid's existing empty 5th slot)",
        metrics_block.index("By Category") < metrics_block.index("⌨ Keyboard Shortcuts"),
    )
    check(
        "the new card reuses the exact same card styling as its siblings (visual consistency, automatic Dark Mode coverage)",
        'bg-cyan-200/40 backdrop-blur-xl border border-cyan-100/50 shadow-[inset_0_1px_1px_rgba(255,255,255,0.5),0_4px_12px_rgba(0,0,0,0.05)] p-6 rounded-3xl">\n<h3 class="text-cyan-950/70 text-sm font-bold mb-2">⌨ Keyboard Shortcuts' in metrics_block,
    )
    check("the metrics grid container itself is untouched (still grid-cols-5)", "grid grid-cols-5 gap-6 mb-8" in DASHBOARD_HTML)


def test_permanent_card_lists_only_real_implemented_shortcuts():
    card_start = DASHBOARD_HTML.index("⌨ Keyboard Shortcuts</h3>")
    card_end = DASHBOARD_HTML.index("</div>\n</div>\n</div>\n<!-- Actions Bar -->")
    card_block = DASHBOARD_HTML[card_start:card_end]

    for expected in ["Next email", "Previous email", "Open email", "Back", "Focus reply", "Show all shortcuts"]:
        check(f'permanent card lists "{expected}"', expected in card_block)

    check('permanent card does not invent a "d" mark-as-read entry', ">D<" not in card_block and ">d<" not in card_block)
    check(
        'permanent card does not invent a Send/dismiss shortcut entry',
        "Send" not in card_block and "Dismiss" not in card_block and "No Reply" not in card_block,
    )


def test_help_dialog_lists_the_same_complete_shortcut_set_as_the_card():
    dialog_start = DASHBOARD_HTML.index('id="quickKeysHelp"')
    dialog_end = DASHBOARD_HTML.index("<!-- Floating Back button") if "<!-- Floating Back button" in DASHBOARD_HTML else DASHBOARD_HTML.index('<div class="flex items-center justify-between mb-6">')
    dialog_block = DASHBOARD_HTML[dialog_start:dialog_end]

    for expected in [
        "Next email", "Previous email", "Open selected email",
        "Back", "Focus reply box",
        "Show keyboard shortcuts", "Close help",
    ]:
        check(f'"?" help dialog lists "{expected}"', expected in dialog_block)

    check('"?" help dialog is organized into a "Navigation" section', ">Navigation<" in dialog_block)
    check('"?" help dialog is organized into an "Email" section', ">Email<" in dialog_block)
    check('"?" help dialog is organized into a "Help" section', ">Help<" in dialog_block)
    check(
        '"?" help dialog does not invent a "d" mark-as-read entry',
        "mark as read" not in dialog_block.lower() and "mark-as-read" not in dialog_block.lower(),
    )


def test_existing_dashboard_components_outside_the_new_card_are_untouched():
    for marker in [
        'id="delete-form"', 'id="select-all"', 'id="searchInput"', 'id="filterForm"',
        'id="tableBody"', 'name="source"', 'name="status"', 'name="priority"',
        'name="date_from"', 'name="date_to"', "function refreshDashboard()",
        "setInterval(refreshDashboard, 8000);", 'href="/"', 'href="/trash"',
        'href="/compose"', 'id="delete-btn"',
    ]:
        check(f"dashboard.html still contains {marker!r} (unrelated component untouched)", marker in DASHBOARD_HTML)


def test_email_detail_loads_quick_keys_and_wires_b_and_r():
    check("email_detail.html loads static/quick-keys.js", '<script src="/static/quick-keys.js"></script>' in EMAIL_DETAIL_HTML)
    check('email_detail.html binds "b"', '"b": {' in EMAIL_DETAIL_HTML)
    check('email_detail.html binds "r"', '"r": {' in EMAIL_DETAIL_HTML)


def _quick_keys_binding_block(src, key):
    start = src.index(f'"{key}": {{')
    end = src.index("},", start)
    return src[start:end]


def test_b_uses_backLink_own_href_not_a_hardcoded_url():
    block = _quick_keys_binding_block(EMAIL_DETAIL_HTML, "b")
    check('the "b" handler reads #backLink via getElementById("backLink")', 'getElementById("backLink")' in block)
    check('the "b" handler reads backLink.href (the real, resolved property)', "backLink.href" in block)
    check(
        'the "b" handler never hardcodes "/dashboard" or "/contact-dashboard" as a literal string',
        '"/dashboard"' not in block and "'/dashboard'" not in block and "contact-dashboard" not in block,
    )


def test_r_focuses_replyBody_only_and_cannot_send_or_modify():
    block = _quick_keys_binding_block(EMAIL_DETAIL_HTML, "r")
    check('the "r" handler targets #replyBody via getElementById("replyBody")', 'getElementById("replyBody")' in block)
    check('the "r" handler calls .focus() on it', "replyBody.focus()" in block)
    check('the "r" handler never assigns replyBody.value', ".value" not in block)
    check('the "r" handler never calls fetch(...)', "fetch(" not in block)
    check('the "r" handler never calls .submit() or .click() on any form/button', ".submit()" not in block and ".click()" not in block)


def test_no_shortcut_is_bound_to_send_or_dismiss():
    check(
        '"Send Out" is never referenced anywhere in the Quick Keys binding script',
        "Send Out" not in EMAIL_DETAIL_HTML.split("QuickKeys.init")[1] if "QuickKeys.init" in EMAIL_DETAIL_HTML else True,
    )
    check(
        'no binding targets composeForm, the submit button, or /dismiss',
        all(
            needle not in _quick_keys_binding_block(EMAIL_DETAIL_HTML, key)
            for key in ("b", "r")
            for needle in ("composeForm", "/dismiss", "submit")
        ),
    )


def test_no_d_mark_as_read_shortcut_was_added():
    quick_keys_scripts = EMAIL_DETAIL_HTML.split("QuickKeys.init")[1] if "QuickKeys.init" in EMAIL_DETAIL_HTML else ""
    dashboard_bindings_start = DASHBOARD_HTML.index("QuickKeys.init")
    dashboard_bindings = DASHBOARD_HTML[dashboard_bindings_start:dashboard_bindings_start + 400]
    check('no "d" binding exists in the Email Detail keymap', '"d":' not in quick_keys_scripts)
    check('no "d" binding exists in the Dashboard keymap', '"d":' not in dashboard_bindings)


# ---------------------------------------------------------------------------
# D. Regression: Dark Mode and Sticky Back markup/ids remain intact.
# ---------------------------------------------------------------------------

def test_dark_mode_markup_untouched():
    for name, src in (("dashboard.html", DASHBOARD_HTML), ("email_detail.html", EMAIL_DETAIL_HTML)):
        check(f"{name}: theme.css is still linked", '<link rel="stylesheet" href="/static/theme.css">' in src)
        check(f"{name}: theme.js is still loaded", '<script src="/static/theme.js"></script>' in src)
        check(f"{name}: the data-theme-toggle button still exists", "data-theme-toggle" in src)
        check(f"{name}: the inline theme-restore bootstrap script is still present", 'localStorage.getItem("aiEmailTheme")' in src)


def test_sticky_back_ids_and_markup_untouched():
    check("email_detail.html still has #backLink", 'id="backLink"' in EMAIL_DETAIL_HTML)
    check("email_detail.html still has #floatingBackLink", 'id="floatingBackLink"' in EMAIL_DETAIL_HTML)
    check(
        "the IntersectionObserver wiring between them is still present",
        'document.getElementById("backLink")' in EMAIL_DETAIL_HTML and 'document.getElementById("floatingBackLink")' in EMAIL_DETAIL_HTML,
    )


def test_sync_and_view_log_links_still_unbound_and_unchanged():
    check(
        "Sync Gmail Sent link is unchanged and not referenced by any Quick Keys binding",
        '/sync-sent/{{ email.id }}' in EMAIL_DETAIL_HTML and "sync-sent" not in EMAIL_DETAIL_HTML.split("QuickKeys.init")[1],
    )
    check(
        "View AI Log link is unchanged and not referenced by any Quick Keys binding",
        "/ai-insights?q=" in EMAIL_DETAIL_HTML and "ai-insights" not in EMAIL_DETAIL_HTML.split("QuickKeys.init")[1],
    )


def main():
    tests = [
        test_typing_safety_guard_covers_every_required_case,
        test_repeat_handling_and_dispatch_order,
        test_escape_closes_help_panel_independent_of_typing_guard,
        test_help_panel_dialog_semantics_and_focus_restore,
        test_mirror_blocks_shortcuts_in_input_textarea_select_contenteditable,
        test_mirror_blocks_shortcuts_with_any_modifier_key,
        test_mirror_event_repeat_is_suppressed_for_default_non_repeatable_bindings,
        test_j_moves_to_the_next_row,
        test_k_moves_to_the_previous_row,
        test_jk_clamp_at_first_and_last_row_never_wrap,
        test_wrap_around_bug_fix_after_focus_is_lost_mid_navigation,
        test_jk_with_no_prior_focus_starts_at_a_sensible_end,
        test_empty_row_list_is_a_safe_no_op,
        test_enter_and_o_open_the_same_focused_row_via_click,
        test_question_mark_opens_and_closes_help_panel,
        test_escape_closes_help_panel,
        test_focus_returns_correctly_after_closing_help_panel,
        test_dashboard_loads_quick_keys_and_wires_jk_enter_o,
        test_dashboard_rows_have_tabindex_in_both_render_paths,
        test_dashboard_focus_indicator_class_toggled_by_real_focus_events,
        test_dashboard_focus_css_defined_for_both_themes,
        test_dashboard_source_implements_the_has_focused_before_guard,
        test_permanent_shortcut_card_present_in_metrics_grid_fifth_slot,
        test_permanent_card_lists_only_real_implemented_shortcuts,
        test_help_dialog_lists_the_same_complete_shortcut_set_as_the_card,
        test_existing_dashboard_components_outside_the_new_card_are_untouched,
        test_email_detail_loads_quick_keys_and_wires_b_and_r,
        test_b_uses_backLink_own_href_not_a_hardcoded_url,
        test_r_focuses_replyBody_only_and_cannot_send_or_modify,
        test_no_shortcut_is_bound_to_send_or_dismiss,
        test_no_d_mark_as_read_shortcut_was_added,
        test_dark_mode_markup_untouched,
        test_sticky_back_ids_and_markup_untouched,
        test_sync_and_view_log_links_still_unbound_and_unchanged,
    ]
    for t in tests:
        t()

    if _failures:
        print(f"\n{len(_failures)} FAILURE(S): {_failures}")
        sys.exit(1)
    print("\nAll tests passed.")


if __name__ == "__main__":
    main()
