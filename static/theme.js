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
})();
