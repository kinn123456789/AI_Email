// AI_Email · Light/Dark theme toggle (v1.1)
//
// Minimal, dependency-free. The actual theme-restore-before-paint logic
// lives in a tiny inline <script> at the top of each template's <head>
// (an external file like this one can't run early/synchronously enough
// to avoid a flash of the wrong theme) - this file only wires up every
// [data-theme-toggle] button's click behavior and keeps its own
// aria-checked/label state in sync with whatever theme is active.
(function () {
    "use strict";

    var STORAGE_KEY = "aiEmailTheme";

    function getStoredTheme() {
        try {
            return localStorage.getItem(STORAGE_KEY);
        } catch (e) {
            // Private-mode/blocked storage - the toggle still works for
            // this page view, it just won't persist across reloads.
            return null;
        }
    }

    function setStoredTheme(theme) {
        try {
            localStorage.setItem(STORAGE_KEY, theme);
        } catch (e) {
            // Same fallback as above - nothing to recover from here.
        }
    }

    function currentTheme() {
        return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
    }

    function syncToggleButtons(theme) {
        var isDark = theme === "dark";
        var buttons = document.querySelectorAll("[data-theme-toggle]");
        for (var i = 0; i < buttons.length; i++) {
            var btn = buttons[i];
            btn.setAttribute("aria-checked", isDark ? "true" : "false");
            var label = isDark ? "Switch to light mode" : "Switch to dark mode";
            btn.setAttribute("aria-label", label);
            btn.setAttribute("title", label);
        }
    }

    function applyTheme(theme) {
        document.documentElement.setAttribute("data-theme", theme);
        syncToggleButtons(theme);
    }

    // Re-reads whatever is actually in storage right now and applies it -
    // unlike the inline <head> bootstrap script (which only ever runs once,
    // at initial document parse, and is intentionally left untouched here),
    // this is safe to call again later in the page's life. Needed for two
    // cases a one-time bootstrap script can never catch on its own:
    //
    // 1. Back/forward-cache (bfcache) restores. Returning to an already-
    //    visited page (browser Back/Forward) can restore its exact
    //    previous live DOM - including whatever data-theme attribute it
    //    had *before* the user navigated away - without re-running any
    //    <script> tag. If the theme was changed on a different page in
    //    between, the restored page would otherwise keep showing its own
    //    stale theme indefinitely, even though the correct preference is
    //    already sitting in localStorage. The "pageshow" event fires on
    //    every bfcache restore (with event.persisted === true) as well as
    //    on a normal fresh load, so re-applying here is a safe no-op on a
    //    fresh load and the actual fix on a bfcache restore.
    // 2. Another already-open tab/page changing the preference. The
    //    "storage" event fires on every other same-origin document when
    //    localStorage changes (never on the document that made the change
    //    itself) - this keeps a Dashboard tab left open in sync the
    //    moment Dark Mode is toggled on an Email Detail tab, instead of
    //    only catching up on its next full reload.
    //
    // Always resolves to an explicit "dark" or "light" (never leaves the
    // attribute at a stale, no-longer-correct value) - matching
    // currentTheme()'s own dark/light resolution, and deliberately
    // tolerant of a since-corrupted/cleared storage value the same way
    // the initial bootstrap script is.
    function restoreThemeFromStorage() {
        var stored = getStoredTheme();
        applyTheme(stored === "dark" ? "dark" : "light");
    }

    document.addEventListener("DOMContentLoaded", function () {
        // Reflects whatever the inline head script already applied before
        // first paint - never re-decides the theme itself here.
        syncToggleButtons(currentTheme());

        var buttons = document.querySelectorAll("[data-theme-toggle]");
        for (var i = 0; i < buttons.length; i++) {
            buttons[i].addEventListener("click", function () {
                var next = currentTheme() === "dark" ? "light" : "dark";
                applyTheme(next);
                setStoredTheme(next);
            });
        }
    });

    window.addEventListener("pageshow", function (event) {
        if (event.persisted) {
            restoreThemeFromStorage();
        }
    });

    window.addEventListener("storage", function (event) {
        if (event.key === STORAGE_KEY) {
            restoreThemeFromStorage();
        }
    });
})();
