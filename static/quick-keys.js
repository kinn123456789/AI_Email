// AI_Email · Quick Keys (B/R only)
//
// Minimal, dependency-free, frontend-only keyboard shortcut helper.
// Exactly two shortcuts exist in the app - B (Back) and R (focus reply) -
// both wired in templates/email_detail.html. The Dashboard has no active
// shortcuts; it only shows a static, informational reference card.
//
// TYPING SAFETY (the single most important correctness property here):
// a shortcut must never fire while the user is typing anywhere (input,
// textarea, select, contenteditable), or while any modifier key is
// held - checked on every keydown, before dispatch.
(function (global) {
    "use strict";

    function isTypingTarget(el) {
        if (!el) {
            return false;
        }
        if (el.isContentEditable) {
            return true;
        }
        var tag = el.tagName;
        return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
    }

    function isSafeToFire(event) {
        // A held modifier means this keystroke is (or could be) a real
        // browser/OS shortcut (Cmd+R, Ctrl+F, Alt+Tab, ...) - never shadow
        // those, regardless of focus location.
        if (event.ctrlKey || event.metaKey || event.altKey) {
            return false;
        }
        // Covers every text-entry surface this app has: the dashboard's
        // search/filter/date controls and the Email Detail reply textarea.
        if (isTypingTarget(document.activeElement)) {
            return false;
        }
        return true;
    }

    // config = { bindings: { "b": { handler: fn }, "r": { handler: fn } } }
    // Keys are matched case-insensitively (event.key is lowercased before
    // lookup), so both "B"/"b" and "R"/"r" fire the same binding.
    function init(config) {
        config = config || {};
        var bindings = config.bindings || {};

        document.addEventListener("keydown", function (event) {
            if (!isSafeToFire(event)) {
                return;
            }

            var binding = bindings[event.key.toLowerCase()];
            if (!binding) {
                return;
            }

            event.preventDefault();
            binding.handler(event);
        });
    }

    global.QuickKeys = {
        init: init,
        isSafeToFire: isSafeToFire,
        isTypingTarget: isTypingTarget,
    };
})(window);
