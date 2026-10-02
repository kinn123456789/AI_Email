// AI_Email · Quick Keys (v1.1)
//
// Minimal, dependency-free, frontend-only keyboard shortcut helper - the
// same architectural pattern as static/theme.js: one shared file holding
// the typing-safety guard, the dispatch logic, and the help-panel
// behavior; each page wires its own small keymap via QuickKeys.init().
//
// TYPING SAFETY (the single most important correctness property here):
// a shortcut must never fire while the user is typing anywhere, or while
// any modifier key is held - see isSafeToFire() below. This is checked
// on every keydown, before any binding or the "?" help toggle runs, so
// it protects every current and future shortcut uniformly.
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
        // Covers every text-entry surface this app has today: the
        // dashboard's search/filter/date controls (input, select) and
        // the Email Detail reply textarea (textarea) - plus any future
        // contenteditable area.
        if (isTypingTarget(document.activeElement)) {
            return false;
        }
        return true;
    }

    // ---- Help panel (role="dialog", Escape to close, focus restored) ----

    var helpPanelState = {
        panel: null,
        previouslyFocused: null,
    };

    function openHelpPanel(panel) {
        if (!panel || !panel.hidden) {
            return;
        }
        helpPanelState.panel = panel;
        helpPanelState.previouslyFocused = document.activeElement;
        panel.hidden = false;

        var closeTarget = panel.querySelector("[data-quick-keys-close]");
        if (closeTarget && typeof closeTarget.focus === "function") {
            closeTarget.focus();
        }
    }

    function closeHelpPanel() {
        var panel = helpPanelState.panel;
        if (!panel || panel.hidden) {
            return;
        }
        panel.hidden = true;

        var toRestore = helpPanelState.previouslyFocused;
        if (toRestore && typeof toRestore.focus === "function") {
            toRestore.focus();
        }
        helpPanelState.panel = null;
        helpPanelState.previouslyFocused = null;
    }

    function toggleHelpPanel(panel) {
        if (panel.hidden) {
            openHelpPanel(panel);
        } else {
            closeHelpPanel();
        }
    }

    // ---- Public init ----------------------------------------------------
    //
    // config = {
    //   helpPanelId: "quickKeysHelp",       (optional - id of this page's
    //                                        help dialog element)
    //   bindings: {
    //     "j": { handler: fn, repeatable: false },
    //     ...
    //   }
    // }
    //
    // Every binding's handler is only ever invoked after isSafeToFire()
    // passes. `repeatable: false` (the default when omitted) ignores
    // event.repeat for that key, so holding a key down never fires a
    // single-fire action (navigate, focus) more than once per physical
    // keypress. Set `repeatable: true` only for an action that is
    // genuinely safe to run repeatedly - none of this app's current
    // shortcuts need it.
    function init(config) {
        config = config || {};
        var bindings = config.bindings || {};
        var helpPanel = config.helpPanelId ? document.getElementById(config.helpPanelId) : null;

        document.addEventListener("keydown", function (event) {
            // Escape closes the help panel regardless of where focus is
            // (including inside the panel itself) and is exempt from the
            // typing-safety guard below - Escape never types a character,
            // so there is nothing for that guard to protect here.
            if (event.key === "Escape" && helpPanel && !helpPanel.hidden) {
                closeHelpPanel();
                return;
            }

            if (!isSafeToFire(event)) {
                return;
            }

            if (event.key === "?" && helpPanel) {
                event.preventDefault();
                toggleHelpPanel(helpPanel);
                return;
            }

            var binding = bindings[event.key];
            if (!binding) {
                return;
            }
            if (event.repeat && !binding.repeatable) {
                return;
            }

            event.preventDefault();
            binding.handler(event);
        });

        if (helpPanel) {
            var closeBtn = helpPanel.querySelector("[data-quick-keys-close]");
            if (closeBtn) {
                closeBtn.addEventListener("click", closeHelpPanel);
            }
        }
    }

    global.QuickKeys = {
        init: init,
        isSafeToFire: isSafeToFire,
        isTypingTarget: isTypingTarget,
    };
})(window);
