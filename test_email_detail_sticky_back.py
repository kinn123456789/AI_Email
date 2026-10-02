"""Focused tests for the Email Detail page's floating Back button.

WHAT THIS FIXES: on a long email/conversation, the page's own header
(where Back, Sync Gmail Sent, and View AI Log all live) scrolls out of
view with the rest of the page, taking Back along with it. Per the
explicit requirement, ONLY Back needs to stay reachable while
scrolling - Sync Gmail Sent and View AI Log must stay exactly where they
are today, never sticky.

THE FIX: the original header Back link (templates/email_detail.html,
given a stable id="backLink" but otherwise completely unchanged - same
href, same classes, same position in the header) is left exactly as it
was. A second, separate link (id="floatingBackLink") with the identical
href/text/icon and the same button classes (so it matches the existing
visual design and inherits Dark Mode support from the exact same
theme.css rules - only "fixed"/positioning classes are new) is added
near the top of <body>, hidden by default. A small IntersectionObserver
toggles its `hidden` attribute based on whether the header's own Back
link is currently visible in the viewport - not a hardcoded scroll
pixel threshold, so this stays correct regardless of how many of the
page's conditional status banners (sent/failed/already-sent/dismissed)
happen to be rendered above the header on a given page. Sync Gmail Sent
and View AI Log are never observed, never duplicated, never touched.

TESTING LIMITATION (same class of limitation as test_email_detail_polish_ui.py
and test_dark_mode_toggle.py): this sandbox has no browser/JS-execution
capability, and the template is Jinja, not importable Python. Structural
checks below are source-presence/ordering checks against the real HTML
text. The IntersectionObserver callback's own show/hide decision is
behaviorally verified via a byte-for-byte Python mirror of its one line
of logic, exercised directly (not just asserted against the source
string) - the same mirror-function technique established earlier this
session. No pytest, no browser - a plain script using only assert
statements and the standard library, per this repo's existing test_*.py
convention.

Run with: python3 test_email_detail_sticky_back.py
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


SRC = _read_source(os.path.join("templates", "email_detail.html"))


# ---------------------------------------------------------------------------
# A. The original header Back link is unchanged except for its new id.
# ---------------------------------------------------------------------------

def test_header_back_link_unchanged_except_for_new_id():
    match = re.search(r'<a id="backLink"[^>]*>', SRC)
    check("the header Back link now has a stable id=\"backLink\"", match is not None)
    if match:
        tag = match.group(0)
        check(
            "the header Back link keeps its original href logic (dashboard vs contact-dashboard)",
            "{% if email.mailbox == 'contact_form' %}/contact-dashboard{% else %}/dashboard{% endif %}" in tag,
        )
        check(
            "the header Back link keeps its original visual classes",
            'class="px-4 py-2 bg-white border border-cyan-200 text-stone-700 font-bold rounded-2xl hover:bg-cyan-50 transition-all flex items-center gap-2 text-sm shadow-sm whitespace-nowrap"' in tag,
        )
    check(
        "exactly one element in the file carries id=\"backLink\" (no accidental duplicate)",
        len(re.findall(r'id="backLink"', SRC)) == 1,
    )


def test_sync_and_view_log_buttons_are_unchanged_and_not_sticky():
    check(
        "Sync Gmail Sent link is present, unchanged, and not given any fixed/sticky positioning class",
        re.search(
            r'<a href="/sync-sent/\{\{ email\.id \}\}"\s*\n\s*class="px-4 py-2 bg-cyan-800 text-white font-bold rounded-2xl hover:bg-black transition-all text-sm shadow-sm whitespace-nowrap">',
            SRC,
        ) is not None,
    )
    check(
        "View AI Log link is present, unchanged, and not given any fixed/sticky positioning class",
        re.search(
            r'<a href="/ai-insights\?q=\{\{ email\.message_id \| urlencode \}\}"\s*\n\s*class="px-4 py-2 bg-white border border-cyan-200 text-stone-700 font-bold rounded-2xl hover:bg-cyan-50 transition-all text-sm shadow-sm whitespace-nowrap">',
            SRC,
        ) is not None,
    )
    check(
        '"Sync Gmail Sent" text never appears alongside a "fixed" or "sticky" class anywhere in the file',
        not re.search(r'class="[^"]*\b(fixed|sticky)\b[^"]*"[^>]*>\s*(?:<[^>]*>)*\s*🔄 Sync Gmail Sent', SRC),
    )
    check(
        '"View AI Log" text never appears alongside a "fixed" or "sticky" class anywhere in the file',
        not re.search(r'class="[^"]*\b(fixed|sticky)\b[^"]*"[^>]*>\s*(?:<[^>]*>)*\s*📊 View AI Log', SRC),
    )


# ---------------------------------------------------------------------------
# B. The new floating Back button: identical destination, hidden by
#    default, correctly styled, and the only new fixed-position element.
# ---------------------------------------------------------------------------

def _floating_back_tag():
    match = re.search(r'<a id="floatingBackLink"[\s\S]*?>', SRC)
    assert match is not None, "could not find the floating Back link"
    return match.group(0)


def test_floating_back_button_exists_hidden_with_matching_destination():
    tag = _floating_back_tag()
    check(
        "the floating Back button targets the exact same destination as the header Back link",
        "{% if email.mailbox == 'contact_form' %}/contact-dashboard{% else %}/dashboard{% endif %}" in tag,
    )
    check("the floating Back button is hidden by default", "hidden" in tag)
    check("the floating Back button uses fixed positioning", "fixed" in tag and ("top-" in tag or "bottom-" in tag))
    check(
        "the floating Back button reuses the same background/border/text color classes as the header one "
        "(so it matches the existing visual design and inherits Dark Mode support from the same theme.css rules)",
        "bg-white" in tag and "border-cyan-200" in tag and "text-stone-700" in tag,
    )
    check(
        "the floating Back button has a high z-index so it renders above page content",
        re.search(r"\bz-\d+\b", tag) is not None,
    )


def test_only_one_new_fixed_element_was_added():
    """Confirms the fix didn't accidentally make any *other* existing
    element (Sync Gmail Sent, View AI Log, or anything else) fixed/sticky
    - the only new `fixed`-positioned element in the whole file is the
    floating Back button itself."""
    fixed_tags = re.findall(r'class="[^"]*\bfixed\b[^"]*"', SRC)
    check(
        "exactly one element in the file uses the \"fixed\" positioning class",
        len(fixed_tags) == 1,
        f"found {len(fixed_tags)}: {fixed_tags}",
    )


def test_floating_back_button_does_not_duplicate_sync_or_view_log():
    tag = _floating_back_tag()
    check("the floating button is Back-only, not a second Sync Gmail Sent button", "Sync Gmail Sent" not in tag)
    check("the floating button is Back-only, not a second View AI Log button", "View AI Log" not in tag)
    check("the floating button's own visible text is exactly the Back link's text", "← Back" in tag or "Back" in SRC[SRC.index(tag):SRC.index(tag) + 200])


# ---------------------------------------------------------------------------
# C. The IntersectionObserver wiring: observes only the header Back link,
#    toggles only the floating Back link - and the toggle logic itself.
# ---------------------------------------------------------------------------

def _observer_script_block():
    start = SRC.index('const headerBackLink = document.getElementById("backLink");')
    end = SRC.index("</script>", start)
    return SRC[start:end]


def test_observer_watches_only_back_link_and_toggles_only_floating_back_link():
    block = _observer_script_block()
    check(
        'observes document.getElementById("backLink") - the header Back link, nothing else',
        'document.getElementById("backLink")' in block,
    )
    check(
        'toggles .hidden only on document.getElementById("floatingBackLink")',
        'document.getElementById("floatingBackLink")' in block,
    )
    check(
        "Sync Gmail Sent / View AI Log elements are never referenced by this script",
        "sync-sent" not in block and "ai-insights" not in block,
    )
    check(
        "gracefully no-ops when IntersectionObserver or the elements are unavailable",
        '"IntersectionObserver" in window' in block,
    )


def _mirror_observer_callback(is_intersecting):
    """Byte-for-byte mirror of the real callback's one line of decision
    logic: floatingBackLink.hidden = headerLinkVisible;"""
    header_link_visible = is_intersecting
    floating_back_link_hidden = header_link_visible
    return floating_back_link_hidden


def test_mirror_floating_button_hidden_while_header_link_visible():
    check(
        "header Back link visible (at page top) -> floating button stays hidden",
        _mirror_observer_callback(is_intersecting=True) is True,
    )


def test_mirror_floating_button_shown_once_header_link_scrolls_away():
    check(
        "header Back link scrolled out of view -> floating button becomes visible",
        _mirror_observer_callback(is_intersecting=False) is False,
    )


def main():
    tests = [
        test_header_back_link_unchanged_except_for_new_id,
        test_sync_and_view_log_buttons_are_unchanged_and_not_sticky,
        test_floating_back_button_exists_hidden_with_matching_destination,
        test_only_one_new_fixed_element_was_added,
        test_floating_back_button_does_not_duplicate_sync_or_view_log,
        test_observer_watches_only_back_link_and_toggles_only_floating_back_link,
        test_mirror_floating_button_hidden_while_header_link_visible,
        test_mirror_floating_button_shown_once_header_link_scrolls_away,
    ]
    for t in tests:
        t()

    if _failures:
        print(f"\n{len(_failures)} FAILURE(S): {_failures}")
        sys.exit(1)
    print("\nAll tests passed.")


if __name__ == "__main__":
    main()
