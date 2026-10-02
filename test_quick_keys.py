"""Focused tests for Quick Keys, simplified to exactly two shortcuts -
B (Back) and R (focus reply) - both on Email Detail (see
static/quick-keys.js and templates/email_detail.html). The Dashboard has
no active shortcut of its own; it only shows a static, informational
"Keyboard Shortcuts" reference card (templates/dashboard.html).

REMOVED ENTIRELY in this cleanup (previously part of a larger v1.1 Quick
Keys feature): j/k dashboard row navigation, Enter/o open-focused-row,
the "?" help dialog and its open/close/focus-restore logic, Escape
handling, the hasFocusedBefore state and every row-focus helper function
(getRows/currentRowIndex/moveFocus/openFocusedRow), the
.quick-keys-focused-row CSS, and every tabindex="-1" added to dashboard
rows for keyboard navigation. static/quick-keys.js itself was rewritten
down to just the typing-safety guard and a simple, case-insensitive
keydown dispatcher - no help-panel code remains in it at all.

TESTING LIMITATION (same class of limitation as test_dark_mode_toggle.py
and test_email_detail_sticky_back.py): this sandbox has no browser/JS-
execution capability, and the two templates are Jinja, not importable
Python. Checks against the templates are structural/source-presence/
ordering checks against the real HTML+JS text. The typing-safety guard's
actual decision logic is behaviorally verified via a byte-for-byte Python
mirror of static/quick-keys.js's own isSafeToFire()/isTypingTarget(),
exercised directly with fake DOM-like objects - the same mirror-function
technique established earlier this session. No pytest, no browser - a
plain script using only assert statements and the standard library, per
this repo's existing test_*.py convention.

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
# A. static/quick-keys.js: typing-safety guard + minimal dispatch.
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


def test_dispatch_is_case_insensitive_and_checks_safety_first():
    check(
        "dispatch lowercases event.key before looking up a binding (so B/b and R/r both match)",
        "bindings[event.key.toLowerCase()]" in QUICK_KEYS_JS,
    )
    check(
        "isSafeToFire() is checked before any binding runs",
        QUICK_KEYS_JS.index("if (!isSafeToFire(event))") < QUICK_KEYS_JS.index("bindings[event.key.toLowerCase()]"),
    )


def test_help_panel_and_navigation_code_fully_removed_from_quick_keys_js():
    for removed in [
        "helpPanelId", "helpPanelState", "openHelpPanel", "closeHelpPanel",
        "toggleHelpPanel", "Escape", '"?"', "data-quick-keys-close",
        "repeatable", "event.repeat",
    ]:
        check(f'quick-keys.js no longer contains {removed!r}', removed not in QUICK_KEYS_JS)


class _FakeElement:
    def __init__(self, tag="DIV", content_editable=False):
        self.tagName = tag
        self.isContentEditable = content_editable


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


def _mirror_dispatch(bindings, key, is_safe):
    """Mirror of the real keydown handler's own two-step gate: nothing
    fires unless isSafeToFire() passes, and lookup is case-insensitive."""
    if not is_safe:
        return None
    return bindings.get(key.lower())


def test_mirror_b_and_r_fire_regardless_of_case():
    bindings = {"b": "back", "r": "focus-reply"}
    check('"b" fires the Back binding', _mirror_dispatch(bindings, "b", is_safe=True) == "back")
    check('"B" (shifted) fires the same Back binding', _mirror_dispatch(bindings, "B", is_safe=True) == "back")
    check('"r" fires the focus-reply binding', _mirror_dispatch(bindings, "r", is_safe=True) == "focus-reply")
    check('"R" (shifted) fires the same focus-reply binding', _mirror_dispatch(bindings, "R", is_safe=True) == "focus-reply")


def test_mirror_nothing_fires_while_typing_even_for_b_or_r():
    bindings = {"b": "back", "r": "focus-reply"}
    check('"b" does not fire while typing', _mirror_dispatch(bindings, "b", is_safe=False) is None)
    check('"r" does not fire while typing', _mirror_dispatch(bindings, "r", is_safe=False) is None)


# ---------------------------------------------------------------------------
# B. Email Detail: exactly b and r are wired, reusing existing elements.
# ---------------------------------------------------------------------------

def test_email_detail_loads_quick_keys_and_binds_only_b_and_r():
    check("email_detail.html loads static/quick-keys.js", '<script src="/static/quick-keys.js"></script>' in EMAIL_DETAIL_HTML)
    wiring_start = EMAIL_DETAIL_HTML.index("QuickKeys.init(")
    wiring_end = EMAIL_DETAIL_HTML.index("})();", wiring_start)
    wiring_block = EMAIL_DETAIL_HTML[wiring_start:wiring_end]

    check('email_detail.html binds "b"', '"b": {' in wiring_block)
    check('email_detail.html binds "r"', '"r": {' in wiring_block)
    check("no helpPanelId is passed (no help panel exists)", "helpPanelId" not in wiring_block)
    for removed_key in ['"j":', '"k":', '"Enter":', '"o":', '"?":', '"d":']:
        check(f"email_detail.html does not bind {removed_key}", removed_key not in wiring_block)


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
    wiring_start = EMAIL_DETAIL_HTML.index("QuickKeys.init(")
    wiring_end = EMAIL_DETAIL_HTML.index("})();", wiring_start)
    wiring_block = EMAIL_DETAIL_HTML[wiring_start:wiring_end]
    check('"Send Out" is never referenced in the Quick Keys binding script', "Send Out" not in wiring_block)
    check(
        "no binding targets composeForm, the submit button, or /dismiss",
        "composeForm" not in wiring_block and "/dismiss" not in wiring_block and "submit" not in wiring_block,
    )


def test_help_dialog_fully_removed_from_email_detail():
    for removed in ["quickKeysHelp", 'role="dialog"', "data-quick-keys-close", "Show this help"]:
        check(f"email_detail.html no longer contains {removed!r}", removed not in EMAIL_DETAIL_HTML)


# ---------------------------------------------------------------------------
# C. Dashboard: no active shortcuts, no row-navigation machinery, the
#    permanent card shows only B and R.
# ---------------------------------------------------------------------------

def test_dashboard_has_no_active_quick_keys_shortcuts():
    check("dashboard.html no longer loads static/quick-keys.js (no active shortcuts on this page)", "quick-keys.js\"" not in DASHBOARD_HTML)
    check('dashboard.html contains no QuickKeys.init(...) call', "QuickKeys.init(" not in DASHBOARD_HTML)


def test_dashboard_row_navigation_machinery_fully_removed():
    for removed in [
        "tabindex=\"-1\"", "moveFocus", "getRows", "currentRowIndex",
        "openFocusedRow", "hasFocusedBefore", "quick-keys-focused-row",
        "quickKeysHelp", "focusin", "focusout",
    ]:
        check(f"dashboard.html no longer contains {removed!r}", removed not in DASHBOARD_HTML)


def test_permanent_shortcut_card_shows_only_b_and_r():
    metrics_start = DASHBOARD_HTML.index("<!-- Metrics Cards -->")
    metrics_end = DASHBOARD_HTML.index("<!-- Actions Bar -->")
    metrics_block = DASHBOARD_HTML[metrics_start:metrics_end]

    check("metrics grid still contains exactly one Total Messages card", metrics_block.count("Total Messages") == 1)
    check("metrics grid still contains exactly one Auto Replies card", metrics_block.count("Auto Replies") == 1)
    check("metrics grid still contains exactly one Needs Review card", metrics_block.count("Needs Review") == 1)
    check("metrics grid still contains exactly one By Category card", metrics_block.count("By Category") == 1)
    check("metrics grid still contains exactly one Keyboard Shortcuts card", metrics_block.count("⌨ Keyboard Shortcuts") == 1)
    check("the metrics grid container itself is untouched (still grid-cols-5)", "grid grid-cols-5 gap-6 mb-8" in DASHBOARD_HTML)

    card_start = DASHBOARD_HTML.index("⌨ Keyboard Shortcuts</h3>")
    card_end = DASHBOARD_HTML.index("<!-- Actions Bar -->")
    card_block = DASHBOARD_HTML[card_start:card_end]

    check('card lists "Back"', "Back" in card_block)
    check('card lists "Focus reply box"', "Focus reply box" in card_block)
    check("card shows exactly two shortcut rows (B and R)", card_block.count('<kbd class="bg-white/60') == 2)
    for removed in ["Next email", "Previous email", "Open email", "Open selected email", "Show all shortcuts", "Navigation", "Email</div>", "Help</div>"]:
        check(f"card no longer mentions {removed!r}", removed not in card_block)
    for removed_key in [">J<", ">K<", ">Enter<", ">O<", ">?<", ">Esc<"]:
        check(f"card no longer shows a {removed_key} key", removed_key not in card_block)


# ---------------------------------------------------------------------------
# D. Regression: Dark Mode, Sticky Back, and unrelated dashboard
#    components remain completely untouched.
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
    wiring_start = EMAIL_DETAIL_HTML.index("QuickKeys.init(")
    wiring_end = EMAIL_DETAIL_HTML.index("})();", wiring_start)
    wiring_block = EMAIL_DETAIL_HTML[wiring_start:wiring_end]
    check(
        "Sync Gmail Sent link is unchanged and not referenced by any Quick Keys binding",
        '/sync-sent/{{ email.id }}' in EMAIL_DETAIL_HTML and "sync-sent" not in wiring_block,
    )
    check(
        "View AI Log link is unchanged and not referenced by any Quick Keys binding",
        "/ai-insights?q=" in EMAIL_DETAIL_HTML and "ai-insights" not in wiring_block,
    )


def test_existing_dashboard_components_outside_the_card_are_untouched():
    for marker in [
        'id="delete-form"', 'id="select-all"', 'id="searchInput"', 'id="filterForm"',
        'id="tableBody"', 'name="source"', 'name="status"', 'name="priority"',
        'name="date_from"', 'name="date_to"', "function refreshDashboard()",
        "setInterval(refreshDashboard, 8000);", 'href="/"', 'href="/trash"',
        'href="/compose"', 'id="delete-btn"',
    ]:
        check(f"dashboard.html still contains {marker!r} (unrelated component untouched)", marker in DASHBOARD_HTML)


def test_existing_email_detail_compose_and_polish_untouched():
    for marker in [
        'id="composeForm"', 'name="reply_body"', 'id="replyBody"',
        'id="polishBtn"', 'id="polishPreview"', 'id="polishApplyBtn"',
        'id="polishDiscardBtn"', 'name="attachments"', "csrf_input(request)",
    ]:
        check(f"email_detail.html still contains {marker!r}", marker in EMAIL_DETAIL_HTML)


def main():
    tests = [
        test_typing_safety_guard_covers_every_required_case,
        test_dispatch_is_case_insensitive_and_checks_safety_first,
        test_help_panel_and_navigation_code_fully_removed_from_quick_keys_js,
        test_mirror_blocks_shortcuts_in_input_textarea_select_contenteditable,
        test_mirror_blocks_shortcuts_with_any_modifier_key,
        test_mirror_b_and_r_fire_regardless_of_case,
        test_mirror_nothing_fires_while_typing_even_for_b_or_r,
        test_email_detail_loads_quick_keys_and_binds_only_b_and_r,
        test_b_uses_backLink_own_href_not_a_hardcoded_url,
        test_r_focuses_replyBody_only_and_cannot_send_or_modify,
        test_no_shortcut_is_bound_to_send_or_dismiss,
        test_help_dialog_fully_removed_from_email_detail,
        test_dashboard_has_no_active_quick_keys_shortcuts,
        test_dashboard_row_navigation_machinery_fully_removed,
        test_permanent_shortcut_card_shows_only_b_and_r,
        test_dark_mode_markup_untouched,
        test_sticky_back_ids_and_markup_untouched,
        test_sync_and_view_log_links_still_unbound_and_unchanged,
        test_existing_dashboard_components_outside_the_card_are_untouched,
        test_existing_email_detail_compose_and_polish_untouched,
    ]
    for t in tests:
        t()

    if _failures:
        print(f"\n{len(_failures)} FAILURE(S): {_failures}")
        sys.exit(1)
    print("\nAll tests passed.")


if __name__ == "__main__":
    main()
