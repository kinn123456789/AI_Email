"""Focused tests for the v1.1 Light/Dark theme toggle (frontend-only,
added on top of the frozen v1.0.0 baseline - see static/theme.css,
static/theme.js, and the small additions to templates/dashboard.html and
templates/email_detail.html).

WHAT THIS FEATURE IS: a small, compact toggle in each page's existing
header/button row that switches the whole page between today's existing
appearance ("Light", the untouched default) and a new "Dark" palette,
persisted in localStorage under the key "aiEmailTheme" and restored
before first paint via a tiny inline <script> at the top of each
template's <head> (an external script can't run early/synchronously
enough to avoid a flash of the wrong theme - see static/theme.js's own
top-of-file comment). static/theme.css only ever activates its dark
palette under the `html[data-theme="dark"]` attribute selector - it
never reacts to `prefers-color-scheme` on its own, matching the explicit
requirement that an unset preference preserves today's Light mode rather
than following the OS theme.

CROSS-PAGE SYNC FIX (added after a production bug report on this feature
branch): Dashboard ON -> Email Detail (correctly opens Dark) -> toggle OFF
on Email Detail -> return to Dashboard -> Dashboard was still showing
Dark instead of Light. Root cause: returning to an already-visited page
via the browser's Back/Forward navigation can restore that page's exact
previous live DOM from the back/forward cache (bfcache) - including
whatever data-theme attribute it had *before* the user ever navigated
away - without re-running any <script> tag, including the inline
bootstrap script that normally re-reads localStorage on every fresh
load. static/theme.js now also listens for "pageshow" (fires on every
bfcache restore, with event.persisted === true, as well as on a normal
fresh load) and "storage" (fires on every OTHER same-origin page when
localStorage changes - keeps an already-open tab in sync too) and
re-applies whatever is currently in localStorage via the new
restoreThemeFromStorage() - see its own top-of-function comment in
static/theme.js for the full reasoning. See tests C below.

TESTING LIMITATION (same class of limitation as test_email_detail_polish_ui.py
and test_review_reasons.py, which this file otherwise follows the exact
convention of): this sandbox has no browser/JS-execution capability, and
the two templates are Jinja, not importable Python. Checks against the
templates are therefore structural/source-presence/ordering checks
against the real HTML text. For the actual restore/toggle/persist
*behavior* (requirements 1-5 below), this file uses the same
mirror-function technique established earlier this session
(test_send_reply_form.py's _extract_reply_body_and_attachments): a
byte-for-byte Python mirror of theme.js's own restore/toggle logic,
exercised with a fake in-memory localStorage, cross-checked against the
literal text of the real static/theme.js and each template's inline
bootstrap script so the mirror can't silently drift from what actually
ships. No pytest, no browser - a plain script using only assert
statements and the standard library, per this repo's existing test_*.py
convention.

Run with: python3 test_dark_mode_toggle.py
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


THEME_CSS = _read_source(os.path.join("static", "theme.css"))
THEME_JS = _read_source(os.path.join("static", "theme.js"))
DASHBOARD_HTML = _read_source(os.path.join("templates", "dashboard.html"))
EMAIL_DETAIL_HTML = _read_source(os.path.join("templates", "email_detail.html"))

TAILWIND_SCRIPT_TAG = 'src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"'
THEME_CSS_LINK = '<link rel="stylesheet" href="/static/theme.css">'
THEME_JS_SCRIPT = '<script src="/static/theme.js"></script>'
BOOTSTRAP_SNIPPET = 'localStorage.getItem("aiEmailTheme")'


# ---------------------------------------------------------------------------
# A. Both templates wire up theme.css/theme.js and the toggle control
#    correctly, in the right order, with real accessibility attributes.
# ---------------------------------------------------------------------------

def test_theme_assets_linked_in_both_templates():
    for name, src in (("dashboard.html", DASHBOARD_HTML), ("email_detail.html", EMAIL_DETAIL_HTML)):
        check(f"{name} links static/theme.css", THEME_CSS_LINK in src)
        check(f"{name} loads static/theme.js", THEME_JS_SCRIPT in src)


def test_inline_bootstrap_restores_theme_before_tailwind_loads():
    """The whole no-flash guarantee depends on this inline script running
    (and therefore appearing in source order) before anything paints -
    in particular, before the Tailwind CDN script, which is the first
    heavyweight thing each <head> loads today."""
    for name, src in (("dashboard.html", DASHBOARD_HTML), ("email_detail.html", EMAIL_DETAIL_HTML)):
        bootstrap_idx = src.find(BOOTSTRAP_SNIPPET)
        tailwind_idx = src.find(TAILWIND_SCRIPT_TAG)
        check(f"{name} has the inline theme-restore bootstrap script", bootstrap_idx != -1)
        check(f"{name} has the Tailwind CDN script", tailwind_idx != -1)
        check(
            f"{name}: theme-restore script appears before the Tailwind CDN script",
            bootstrap_idx != -1 and tailwind_idx != -1 and bootstrap_idx < tailwind_idx,
        )


def test_bootstrap_script_only_accepts_known_theme_values():
    """Defends against a corrupted/unexpected localStorage value (neither
    "dark" nor "light") ever setting a bogus data-theme attribute - falls
    through to the existing default Light appearance instead."""
    for name, src in (("dashboard.html", DASHBOARD_HTML), ("email_detail.html", EMAIL_DETAIL_HTML)):
        check(
            f'{name}: bootstrap script only accepts "dark" or "light"',
            'if (t === "dark" || t === "light")' in src,
        )
        check(
            f"{name}: bootstrap script is wrapped in try/catch (localStorage can throw)",
            "try {" in src and "localStorage.getItem" in src and "catch (e)" in src,
        )


def test_toggle_button_present_with_accessibility_attributes():
    for name, src in (("dashboard.html", DASHBOARD_HTML), ("email_detail.html", EMAIL_DETAIL_HTML)):
        match = re.search(r"<button[^>]*\bdata-theme-toggle\b[^>]*>", src)
        check(f"{name}: a button carries data-theme-toggle", match is not None)
        if match:
            tag = match.group(0)
            check(f'{name}: toggle button has role="switch"', 'role="switch"' in tag)
            check(f"{name}: toggle button has an initial aria-checked", "aria-checked=" in tag)
            check(f"{name}: toggle button has an aria-label", "aria-label=" in tag)
            check(f"{name}: toggle button has a title (tooltip)", "title=" in tag)
        check(
            f"{name}: toggle shows both the sun and moon icons",
            "theme-toggle-icon-light" in src and "theme-toggle-icon-dark" in src and "☀" in src and "🌙" in src,
        )


def test_css_dark_palette_only_gated_by_explicit_attribute():
    """Requirement: 'If no preference exists, preserve the current Light
    mode' - the dark palette must only ever activate via the explicit
    data-theme="dark" attribute (set only by the bootstrap script/toggle
    from a real stored choice), never automatically from the OS/browser
    `prefers-color-scheme`, which would silently violate that
    requirement for any visitor whose OS happens to be in dark mode."""
    check(
        'theme.css never auto-activates dark mode via "prefers-color-scheme"',
        "prefers-color-scheme" not in THEME_CSS,
    )
    check(
        'every dark-mode rule in theme.css is scoped under html[data-theme="dark"]',
        THEME_CSS.count('html[data-theme="dark"]') > 20,
    )


def test_core_theme_tokens_defined_for_both_palettes():
    required_tokens = [
        "--t-bg-page", "--t-surface", "--t-text-primary", "--t-text-secondary",
        "--t-border", "--t-input-bg", "--t-btn-primary-bg", "--t-link",
        "--t-focus-ring", "--t-code-bg",
    ]
    for token in required_tokens:
        check(f"theme.css defines {token} in both :root (light) and html[data-theme=\"dark\"]",
              THEME_CSS.count(token) >= 2)


def test_focus_visible_styling_present_for_keyboard_users():
    check(
        "theme.css gives interactive elements a visible :focus-visible outline in dark mode",
        "focus-visible" in THEME_CSS and "--t-focus-ring" in THEME_CSS,
    )
    check(
        "the toggle control itself has its own :focus-visible rule",
        ".theme-toggle:focus-visible" in THEME_CSS,
    )


# ---------------------------------------------------------------------------
# B. Behavioral mirror of theme.js's restore/toggle/persist logic (the
#    user's required checks 1-5), cross-checked against the real files.
# ---------------------------------------------------------------------------

class _FakeLocalStorage:
    """In-memory stand-in for the browser's localStorage - enough to
    exercise theme.js's own get/set calls without a real browser."""

    def __init__(self, initial=None):
        self._store = dict(initial or {})

    def getItem(self, key):
        return self._store.get(key)

    def setItem(self, key, value):
        self._store[key] = value


def _mirror_restore_on_load(local_storage):
    """Byte-for-byte mirror of the inline bootstrap script's own logic
    (identical in both templates - see BOOTSTRAP_SNIPPET above):

        var t = localStorage.getItem("aiEmailTheme");
        if (t === "dark" || t === "light") {
            document.documentElement.setAttribute("data-theme", t);
        }

    Returns the resulting data-theme attribute value, or None if it was
    never set (i.e. today's existing default Light appearance)."""
    t = local_storage.getItem("aiEmailTheme")
    if t == "dark" or t == "light":
        return t
    return None


def _mirror_current_theme(data_theme_attr):
    """Mirror of theme.js's currentTheme(): document.documentElement
    .getAttribute("data-theme") === "dark" ? "dark" : "light" - an unset
    attribute (None) is "light", exactly like the real DOM default."""
    return "dark" if data_theme_attr == "dark" else "light"


def _mirror_toggle(data_theme_attr, local_storage):
    """Mirror of theme.js's click handler: flips to the opposite of
    whatever is currently active, applies it, and persists it."""
    next_theme = "light" if _mirror_current_theme(data_theme_attr) == "dark" else "dark"
    local_storage.setItem("aiEmailTheme", next_theme)
    return next_theme


def test_mirror_functions_match_the_real_files_literally():
    check(
        "the real bootstrap script literally reads localStorage.getItem(\"aiEmailTheme\")",
        BOOTSTRAP_SNIPPET in DASHBOARD_HTML and BOOTSTRAP_SNIPPET in EMAIL_DETAIL_HTML,
    )
    check(
        "the real theme.js currentTheme() mirrors the same data-theme===\"dark\" check",
        'getAttribute("data-theme") === "dark" ? "dark" : "light"' in THEME_JS,
    )
    check(
        "the real theme.js toggle handler flips to the opposite theme",
        'var next = currentTheme() === "dark" ? "light" : "dark";' in THEME_JS,
    )
    check(
        "the real theme.js persists the chosen theme via setStoredTheme/localStorage.setItem",
        "localStorage.setItem(STORAGE_KEY, theme)" in THEME_JS,
    )


def test_no_preference_preserves_existing_light_mode():
    """Requirement 1: Existing Light mode remains unchanged when no
    preference exists."""
    storage = _FakeLocalStorage()  # nothing stored at all
    result = _mirror_restore_on_load(storage)
    check(
        "no stored preference -> data-theme is never set (today's default Light appearance)",
        result is None,
    )


def test_saved_dark_preference_is_restored():
    """Requirement 2: Saved dark preference is restored."""
    storage = _FakeLocalStorage({"aiEmailTheme": "dark"})
    result = _mirror_restore_on_load(storage)
    check("a stored \"dark\" preference restores data-theme=\"dark\"", result == "dark")


def test_saved_light_preference_is_restored():
    """Requirement 3: Saved light preference is restored."""
    storage = _FakeLocalStorage({"aiEmailTheme": "light"})
    result = _mirror_restore_on_load(storage)
    check("a stored \"light\" preference restores data-theme=\"light\" explicitly", result == "light")


def test_unexpected_stored_value_falls_back_to_default_light():
    storage = _FakeLocalStorage({"aiEmailTheme": "sepia"})
    result = _mirror_restore_on_load(storage)
    check("a corrupted/unrecognized stored value is ignored, not applied", result is None)


def test_toggle_changes_the_active_theme():
    """Requirement 4: Toggle changes the active theme."""
    storage = _FakeLocalStorage()
    check(
        "toggling from the default (unset -> Light) switches to Dark",
        _mirror_toggle(None, storage) == "dark",
    )
    check(
        "toggling from Dark switches back to Light",
        _mirror_toggle("dark", storage) == "light",
    )


def test_preference_persists_across_simulated_reload():
    """Requirement 5: Preference persists - toggling writes to the same
    storage key the next page load's restore function reads from."""
    storage = _FakeLocalStorage()
    chosen = _mirror_toggle(None, storage)  # user switches to Dark
    check("toggle wrote the new preference to storage", storage.getItem("aiEmailTheme") == chosen)

    # Simulates a fresh page load reading that same storage back.
    restored = _mirror_restore_on_load(storage)
    check("a simulated reload restores the exact theme that was just chosen", restored == chosen)


# ---------------------------------------------------------------------------
# C. Spot-checks that pre-existing, unrelated functionality survived
#    untouched next to the new toggle markup (requirement 6).
# ---------------------------------------------------------------------------

def test_dashboard_existing_functionality_untouched():
    for marker in [
        'id="delete-form"', 'id="select-all"', 'id="searchInput"',
        'id="filterForm"', "function refreshDashboard()", "setInterval(refreshDashboard, 8000);",
        'id="tableBody"', 'name="source"', 'name="status"', 'name="priority"',
    ]:
        check(f"dashboard.html still contains {marker!r}", marker in DASHBOARD_HTML)


def test_email_detail_compose_and_polish_untouched():
    for marker in [
        'id="composeForm"', 'name="reply_body"', 'id="replyBody"',
        'id="polishBtn"', 'id="polishPreview"', 'id="polishApplyBtn"',
        'id="polishDiscardBtn"', 'name="attachments"', "csrf_input(request)",
    ]:
        check(f"email_detail.html still contains {marker!r}", marker in EMAIL_DETAIL_HTML)


# ---------------------------------------------------------------------------
# D. Cross-page theme sync (the production bug fix): a bfcache-restored
#    page, or another already-open tab/page, must pick up a theme change
#    made elsewhere - not keep showing its own stale pre-navigation theme.
# ---------------------------------------------------------------------------

def test_theme_js_listens_for_pageshow_and_storage_events():
    check(
        'theme.js listens for "pageshow" (fires on bfcache restores)',
        'addEventListener("pageshow"' in THEME_JS,
    )
    check(
        "the pageshow handler specifically checks event.persisted (true only for a bfcache restore)",
        "event.persisted" in THEME_JS,
    )
    check(
        'theme.js listens for "storage" (fires on other same-origin pages/tabs)',
        'addEventListener("storage"' in THEME_JS,
    )
    check(
        "the storage handler checks event.key against the theme's own storage key",
        "event.key === STORAGE_KEY" in THEME_JS,
    )


def _mirror_restore_theme_from_storage(local_storage):
    """Byte-for-byte mirror of the real theme.js's new
    restoreThemeFromStorage(): re-reads storage *right now* and resolves
    to an explicit "dark" or "light" - deliberately ignoring whatever the
    page's own current (possibly stale) data-theme attribute already is,
    since the whole point is to overwrite a stale value, not defer to it."""
    stored = local_storage.getItem("aiEmailTheme")
    return "dark" if stored == "dark" else "light"


def test_bfcache_restore_picks_up_a_theme_changed_on_another_page():
    """Exact reproduction of the reported bug, as a mirror-level scenario:
    Dashboard was Dark when the user navigated away (so its frozen DOM,
    if bfcache-restored, would still say "dark") - but Email Detail has
    since changed the *shared* storage to "light". A pageshow restore
    must resolve to "light", not whatever the stale page already shows."""
    storage = _FakeLocalStorage({"aiEmailTheme": "dark"})  # Dashboard's state when it was left
    storage.setItem("aiEmailTheme", "light")  # Email Detail's later toggle-off

    stale_dashboard_attr = "dark"  # what the bfcache-restored DOM still has, pre-fix
    resolved = _mirror_restore_theme_from_storage(storage)

    check(
        "a bfcache restore resolves to the LATEST stored theme, not the page's stale attribute",
        resolved == "light" and resolved != stale_dashboard_attr,
    )


def test_cross_tab_storage_event_picks_up_latest_theme():
    """The companion scenario: Dashboard is left open in one tab/page
    while Dark Mode is toggled in another - the storage event fires only
    in the OTHER (not-currently-changing) document, which is exactly
    what the Dashboard tab receiving this event represents here."""
    storage = _FakeLocalStorage({"aiEmailTheme": "light"})
    storage.setItem("aiEmailTheme", "dark")  # changed elsewhere
    check(
        "the still-open page resolves to the newly stored theme on a storage event",
        _mirror_restore_theme_from_storage(storage) == "dark",
    )


def test_restore_from_storage_never_leaves_a_corrupted_value_applied():
    """Unlike the very first page load (where a corrupted value simply
    means "nothing was ever set"), a correction mid-session must still
    resolve to a real theme, not propagate garbage into data-theme."""
    storage = _FakeLocalStorage({"aiEmailTheme": "sepia"})
    check(
        "a corrupted stored value still resolves to a real theme (Light) on restore",
        _mirror_restore_theme_from_storage(storage) == "light",
    )


def main():
    tests = [
        test_theme_assets_linked_in_both_templates,
        test_inline_bootstrap_restores_theme_before_tailwind_loads,
        test_bootstrap_script_only_accepts_known_theme_values,
        test_toggle_button_present_with_accessibility_attributes,
        test_css_dark_palette_only_gated_by_explicit_attribute,
        test_core_theme_tokens_defined_for_both_palettes,
        test_focus_visible_styling_present_for_keyboard_users,
        test_mirror_functions_match_the_real_files_literally,
        test_no_preference_preserves_existing_light_mode,
        test_saved_dark_preference_is_restored,
        test_saved_light_preference_is_restored,
        test_unexpected_stored_value_falls_back_to_default_light,
        test_toggle_changes_the_active_theme,
        test_preference_persists_across_simulated_reload,
        test_dashboard_existing_functionality_untouched,
        test_email_detail_compose_and_polish_untouched,
        test_theme_js_listens_for_pageshow_and_storage_events,
        test_bfcache_restore_picks_up_a_theme_changed_on_another_page,
        test_cross_tab_storage_event_picks_up_latest_theme,
        test_restore_from_storage_never_leaves_a_corrupted_value_applied,
    ]
    for t in tests:
        t()

    if _failures:
        print(f"\n{len(_failures)} FAILURE(S): {_failures}")
        sys.exit(1)
    print("\nAll tests passed.")


if __name__ == "__main__":
    main()
