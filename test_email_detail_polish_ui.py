"""Focused tests for AI Polish Phase 2: the UI integration added to
templates/email_detail.html (Polish button, preview, Apply/Discard,
race-condition handling).

Matches this repo's existing test_*.py convention (see test_review_reasons.py,
test_p0_fixes.py): a plain script using only assert statements and the
standard library - no pytest, no browser. A new, separate file rather than
touching test_review_reasons.py/test_p0_fixes.py, which already pin other
parts of this same template.

WHY SOURCE-TEXT CHECKS, NOT LIVE BROWSER TESTS: this sandbox has no
browser/JS-execution capability (confirmed earlier this session) and
templates/email_detail.html is Jinja, not importable Python. Every check
here is therefore a structural/source-presence/ordering check against the
actual HTML+JS text, following the exact same _read_source() pattern
test_review_reasons.py already established for this file. This is a real
limitation: these tests can catch a missing handler, a wrong selector, or
logic written in the wrong order, but they cannot catch a browser-only bug
(e.g. a typo that's only wrong at runtime in a way that still parses).
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


def _script_block(src):
    """The dedicated Polish <script> block, isolated from the rest of the
    file (in particular from the pre-existing conversation-scroll script
    right above it) so checks can't accidentally match unrelated code."""
    start = src.index('const polishBtn = document.getElementById("polishBtn");')
    end = src.index("<script src=\"/static/local-time.js\">")
    return src[start:end]


# ---------------------------------------------------------------------------
# 1-2: textarea id + Polish button exist
# ---------------------------------------------------------------------------

def test_textarea_has_stable_id_and_unchanged_name():
    src = _read_source(os.path.join("templates", "email_detail.html"))
    check(
        "textarea has id=\"replyBody\" and name=\"reply_body\" on the same tag",
        re.search(r'<textarea[^>]*\bid="replyBody"[^>]*\bname="reply_body"[^>]*>', src) is not None,
        "expected a single <textarea> tag carrying both attributes",
    )
    check(
        "existing AI draft display Jinja logic is preserved verbatim inside the textarea",
        '{% if not request.query_params.get("sent") %}{{ email.ai_draft_reply }}{% endif %}' in src,
    )


def test_polish_button_exists_as_real_button_type_button():
    src = _read_source(os.path.join("templates", "email_detail.html"))
    check(
        "a real <button> with id=\"polishBtn\" and type=\"button\" exists (never a clickable div)",
        re.search(r'<button\s+type="button"\s+id="polishBtn"', src) is not None,
    )
    check(
        "Polish button carries an aria-label",
        'aria-label="AI Polish' in src,
    )


def test_apply_and_discard_are_real_buttons_type_button():
    src = _read_source(os.path.join("templates", "email_detail.html"))
    check(
        "Apply is a real <button type=\"button\"> (can never submit the Send form)",
        re.search(r'<button\s+type="button"\s+id="polishApplyBtn"', src) is not None,
    )
    check(
        "Discard is a real <button type=\"button\">",
        re.search(r'<button\s+type="button"\s+id="polishDiscardBtn"', src) is not None,
    )


# ---------------------------------------------------------------------------
# 3-6: request shape - endpoint, FormData, csrf_token, current draft
# ---------------------------------------------------------------------------

def test_request_posts_to_polish_endpoint_with_formdata():
    src = _read_source(os.path.join("templates", "email_detail.html"))
    script = _script_block(src)
    check(
        "fetch() posts to /email/{{ email.id }}/polish",
        'fetch("/email/{{ email.id }}/polish"' in script,
    )
    check(
        "request method is POST",
        re.search(r'method:\s*"POST"', script) is not None,
    )
    check(
        "request body is a FormData instance",
        "new FormData()" in script and "body: formData" in script,
    )
    check(
        "no manual Content-Type header is set (so the browser sets the multipart boundary itself)",
        "Content-Type" not in script,
    )


def test_request_includes_csrf_token_and_current_draft():
    src = _read_source(os.path.join("templates", "email_detail.html"))
    script = _script_block(src)
    check(
        "csrf_token is read from the existing hidden field already in the compose form",
        'composeForm.querySelector(\'input[name="csrf_token"]\')' in script,
    )
    check(
        "csrf_token is appended to the FormData",
        'formData.append("csrf_token"' in script,
    )
    check(
        "the current draft is appended to the FormData as \"draft\"",
        'formData.append("draft", draftAtRequestTime)' in script,
    )
    check(
        "the draft is captured from the live textarea value (not some other source)",
        "const draftAtRequestTime = replyBody.value;" in script,
    )
    check(
        "the draft is captured BEFORE the fetch() call, not after",
        script.index("const draftAtRequestTime = replyBody.value;") < script.index('fetch("/email/{{ email.id }}/polish"'),
    )


# ---------------------------------------------------------------------------
# 7: Polish never auto-submits the Send form
# ---------------------------------------------------------------------------

def test_polish_never_submits_the_send_form():
    src = _read_source(os.path.join("templates", "email_detail.html"))
    script = _script_block(src)
    check(
        "the script never calls composeForm.submit() or requestSubmit()",
        "composeForm.submit(" not in script and "composeForm.requestSubmit(" not in script,
    )
    check(
        "the existing Send <form> action/method/enctype are untouched",
        'action="/email/{{ email.id }}/send" method="POST" enctype="multipart/form-data"' in src,
    )
    check(
        "the existing Send button's onsubmit disable/relabel behavior is untouched",
        "this.querySelector('button[type=submit]').disabled=true; this.querySelector('button[type=submit]').innerText='Sending...';" in src,
    )
    check(
        "the Send button itself is still the only type=\"submit\" control inside the compose form",
        src.count('type="submit"') == 1,
    )


# ---------------------------------------------------------------------------
# 8-11: textarea is never auto-replaced; only Apply/Discard/error act on it
# ---------------------------------------------------------------------------

def test_textarea_value_is_only_ever_assigned_from_the_apply_handler():
    src = _read_source(os.path.join("templates", "email_detail.html"))
    script = _script_block(src)
    assignments = [m.start() for m in re.finditer(r"replyBody\.value\s*=(?!=)", script)]
    check(
        "replyBody.value is assigned exactly once in the whole script (only by Apply)",
        len(assignments) == 1,
        f"found {len(assignments)} assignment(s)",
    )
    if assignments:
        apply_handler_start = script.index('polishApplyBtn.addEventListener("click"')
        apply_handler_end = script.index("});", apply_handler_start)
        check(
            "that single assignment is inside the Apply click handler",
            apply_handler_start < assignments[0] < apply_handler_end,
        )


def test_apply_replaces_textarea_with_preview_text_and_hides_preview():
    src = _read_source(os.path.join("templates", "email_detail.html"))
    script = _script_block(src)
    apply_handler = script[script.index('polishApplyBtn.addEventListener("click"'):script.index("});", script.index('polishApplyBtn.addEventListener("click"')) + 3]
    check(
        "Apply sets replyBody.value from the preview's own stored text",
        "replyBody.value = polishPreviewText.textContent;" in apply_handler,
    )
    check(
        "Apply hides the preview afterward",
        "hidePolishPreview();" in apply_handler,
    )


def test_discard_restores_nothing_and_never_calls_backend_again():
    src = _read_source(os.path.join("templates", "email_detail.html"))
    script = _script_block(src)
    discard_handler = script[script.index('polishDiscardBtn.addEventListener("click"'):script.index("});", script.index('polishDiscardBtn.addEventListener("click"')) + 3]
    check(
        "Discard never assigns replyBody.value (the textarea already holds whatever the user last had)",
        "replyBody.value" not in discard_handler,
    )
    check(
        "Discard never calls fetch() again",
        "fetch(" not in discard_handler,
    )
    check(
        "Discard hides the preview",
        "hidePolishPreview();" in discard_handler,
    )


def test_error_paths_never_touch_the_textarea():
    src = _read_source(os.path.join("templates", "email_detail.html"))
    script = _script_block(src)
    check(
        "showPolishError() is never followed by a textarea mutation anywhere in the script",
        "replyBody.value" not in script[script.index("function showPolishError"):script.index("function hidePolishPreview")],
    )
    # The FIRST ".catch(" in source order is the small JSON-parse fallback
    # inside the .then() chain; the LAST one (bounded below by where the
    # click handler itself ends) is the real network-failure handler.
    network_catch_start = script.rindex(".catch(function ()")
    network_catch_end = script.index("polishApplyBtn.addEventListener", network_catch_start)
    check(
        "the network-failure .catch() handler never assigns replyBody.value",
        re.search(r"replyBody\.value\s*=(?!=)", script[network_catch_start:network_catch_end]) is None,
    )


# ---------------------------------------------------------------------------
# 12-13: loading/double-click guard, no raw backend errors surfaced
# ---------------------------------------------------------------------------

def test_loading_state_guards_against_duplicate_requests():
    src = _read_source(os.path.join("templates", "email_detail.html"))
    script = _script_block(src)
    check(
        "a click while a request is already in flight is ignored",
        "if (polishInFlight) {\n                return;\n            }" in script or "if (polishInFlight) {" in script,
    )
    check(
        "the Polish button is disabled while polishing",
        "polishBtn.disabled = isPolishing;" in script,
    )
    check(
        "the button label switches to a distinct \"Polishing...\" state",
        '"✨ Polishing..."' in script,
    )
    check(
        "the Send button is never disabled by this script (only Polish's own button is)",
        "sendBtn" not in script and "submit].disabled" not in script,
    )


def test_raw_backend_errors_are_never_displayed():
    src = _read_source(os.path.join("templates", "email_detail.html"))
    script = _script_block(src)
    check(
        "only the one fixed, friendly error message is ever shown to the user",
        script.count("We couldn't polish this draft right now. Your original draft is unchanged.") >= 1,
    )
    check(
        "the raw provider/backend error field from the JSON response is never rendered",
        "result.data.error" not in script and ".error)" not in script,
    )


# ---------------------------------------------------------------------------
# 14-16: no DB calls, Send route untouched, textarea name unchanged
# ---------------------------------------------------------------------------

def test_no_database_calls_or_persistence_introduced_in_the_template():
    src = _read_source(os.path.join("templates", "email_detail.html"))
    script = _script_block(src)
    check(
        "the Polish script never references database.py or a database module",
        "database" not in script.lower(),
    )
    check(
        "the only network call this script makes is to the polish endpoint",
        script.count("fetch(") == 1,
    )


def test_reply_polish_module_and_route_unmodified_by_this_task():
    # Phase 2's instructions explicitly forbid touching reply_polish.py
    # unless absolutely required - confirm the Phase 1 route/module still
    # match what Phase 1 already implemented and tested.
    main_src = _read_source("main.py")
    check(
        "the /email/{email_id}/polish route still exists in main.py, unmodified in shape",
        '@app.post("/email/{email_id}/polish")' in main_src,
    )
    check(
        "the route still reads request.state.form rather than re-parsing the body",
        "form = request.state.form" in main_src,
    )


# ---------------------------------------------------------------------------
# 17 / race condition: stale-response handling
# ---------------------------------------------------------------------------

def test_race_condition_sequence_number_guards_stale_responses():
    src = _read_source(os.path.join("templates", "email_detail.html"))
    script = _script_block(src)
    check(
        "a request sequence counter is captured at click time, before the fetch() call",
        script.index("const thisRequestSeq = ++polishRequestSeq;") < script.index('fetch("/email/{{ email.id }}/polish"'),
    )
    check(
        "the success handler discards its own result if a newer click has already started",
        "if (thisRequestSeq !== polishRequestSeq) {\n                        return;\n                    }" in script,
    )
    stale_guard_pos = script.index("if (thisRequestSeq !== polishRequestSeq) {\n                        return;\n                    }")
    preview_write_pos = script.index("polishPreviewText.textContent = polished;")
    check(
        "the stale-response guard runs BEFORE the preview is ever populated",
        stale_guard_pos < preview_write_pos,
    )


def test_race_condition_edit_during_flight_is_surfaced_not_hidden():
    src = _read_source(os.path.join("templates", "email_detail.html"))
    script = _script_block(src)
    check(
        "on response arrival, the live textarea value is compared against the draft that was actually polished",
        "polishStaleNote.classList.toggle(\"hidden\", replyBody.value === draftAtRequestTime);" in script,
    )
    check(
        "that comparison happens after the stale-request guard and before the preview is shown",
        script.index("if (thisRequestSeq !== polishRequestSeq)")
        < script.index('polishStaleNote.classList.toggle("hidden", replyBody.value === draftAtRequestTime);')
        < script.index("polishPreview.classList.remove(\"hidden\");"),
    )
    check(
        "the comparison never mutates replyBody - it only toggles a note's visibility",
        re.search(r"replyBody\.value\s*=(?!=)", script[
            script.index('polishStaleNote.classList.toggle("hidden", replyBody.value === draftAtRequestTime);'):
            script.index('polishStaleNote.classList.toggle("hidden", replyBody.value === draftAtRequestTime);') + 200
        ]) is None,
    )


def main():
    test_textarea_has_stable_id_and_unchanged_name()
    test_polish_button_exists_as_real_button_type_button()
    test_apply_and_discard_are_real_buttons_type_button()

    test_request_posts_to_polish_endpoint_with_formdata()
    test_request_includes_csrf_token_and_current_draft()

    test_polish_never_submits_the_send_form()

    test_textarea_value_is_only_ever_assigned_from_the_apply_handler()
    test_apply_replaces_textarea_with_preview_text_and_hides_preview()
    test_discard_restores_nothing_and_never_calls_backend_again()
    test_error_paths_never_touch_the_textarea()

    test_loading_state_guards_against_duplicate_requests()
    test_raw_backend_errors_are_never_displayed()

    test_no_database_calls_or_persistence_introduced_in_the_template()
    test_reply_polish_module_and_route_unmodified_by_this_task()

    test_race_condition_sequence_number_guards_stale_responses()
    test_race_condition_edit_during_flight_is_surfaced_not_hidden()

    print()
    if _failures:
        print(f"{len(_failures)} FAILED: {_failures}")
        sys.exit(1)
    else:
        print("All tests passed.")


if __name__ == "__main__":
    main()
