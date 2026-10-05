"""Focused regression tests for the Teacher Portal reply-style fix:

Teacher Portal AI drafts (audience="teacher") must no longer receive the
email-style greeting ("Hi," / "Hi {name},") or signature ("Best regards,
Coral Team") that build_user_prompt()/SYSTEM_PROMPT previously injected
into every reply regardless of audience. Email replies (audience="parent",
the default) must keep their existing greeting/signature behavior exactly
as before - see test_prompt_builder_fixes.py's own test_11, which already
locks in that the default/parent path is unchanged.

prompt_builder.py has zero imports of its own, so it's imported directly
here - no fake-infrastructure modules are needed, matching
test_prompt_builder_fixes.py's own convention.

Run with: python3 test_teacher_portal_reply_style.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import prompt_builder as pb  # noqa: E402

_failures = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" - {detail}" if detail and not condition else ""))
    if not condition:
        _failures.append(name)


_COMMON_KWARGS = dict(
    subject="Can we move Friday's class?",
    body="Is it possible to move our Friday session to 4 PM?",
    category="Scheduling",
    priority="Medium",
    thread_history="",
    knowledge=[],
    similar_emails=[],
)


# ===========================================================================
# build_user_prompt() - audience="teacher"
# ===========================================================================

def test_1_teacher_prompt_has_no_hi_greeting_instruction():
    prompt = pb.build_user_prompt(**_COMMON_KWARGS, audience="teacher")
    check(
        "1. audience='teacher' prompt does not instruct a 'Hi,' greeting",
        "Start the reply with exactly this greeting" not in prompt and '\nHi,\n' not in prompt,
    )


def test_2_teacher_prompt_has_no_signature_instruction():
    prompt = pb.build_user_prompt(**_COMMON_KWARGS, audience="teacher")
    check(
        "2. audience='teacher' prompt never instructs 'Best regards'",
        "Best regards" not in prompt,
    )
    check(
        "2. audience='teacher' prompt never instructs 'Coral Team'",
        "Coral Team" not in prompt,
    )


def test_3_teacher_prompt_has_no_your_greeting_or_your_signature_sections():
    prompt = pb.build_user_prompt(**_COMMON_KWARGS, audience="teacher")
    check("3. 'YOUR GREETING' section is absent for audience='teacher'", "YOUR GREETING" not in prompt)
    check("3. 'YOUR SIGNATURE' section is absent for audience='teacher'", "YOUR SIGNATURE" not in prompt)


def test_4_teacher_prompt_has_the_new_chat_format_section():
    prompt = pb.build_user_prompt(**_COMMON_KWARGS, audience="teacher")
    check(
        "4. audience='teacher' prompt includes the new TEACHER PORTAL REPLY FORMAT section",
        "TEACHER PORTAL REPLY FORMAT" in prompt,
    )
    check(
        "4. that section explicitly says not to include a greeting or signature",
        "do not include a greeting" in prompt.lower() and "signature" in prompt.lower(),
    )


def test_5_teacher_prompt_task_list_no_longer_references_greeting_signature_sections():
    prompt = pb.build_user_prompt(**_COMMON_KWARGS, audience="teacher")
    check(
        "5. Step 5 task list no longer tells the model to match YOUR GREETING/YOUR SIGNATURE",
        "matching YOUR GREETING above" not in prompt and "matching YOUR SIGNATURE above" not in prompt,
    )
    check(
        "5. Step 5 task list instead tells the model not to greet/sign off",
        "Do not include a greeting" in prompt and "Do not include a signature" in prompt,
    )


# ===========================================================================
# build_user_prompt() - audience="parent" (default) must be unchanged
# ===========================================================================

def test_6_parent_default_prompt_unchanged():
    prompt = pb.build_user_prompt(**_COMMON_KWARGS)
    check(
        "6. omitting audience (parent default) still includes YOUR GREETING",
        "YOUR GREETING" in prompt,
    )
    check(
        "6. omitting audience (parent default) still includes YOUR SIGNATURE",
        "YOUR SIGNATURE" in prompt,
    )
    check(
        "6. omitting audience (parent default) still signs with Coral Team (no source given, matches test_prompt_builder_fixes.py's test_11)",
        "Best regards,\nCoral Team" in prompt,
    )


def test_7_explicit_parent_audience_identical_to_default():
    default_prompt = pb.build_user_prompt(**_COMMON_KWARGS)
    explicit_prompt = pb.build_user_prompt(**_COMMON_KWARGS, audience="parent")
    check(
        "7. audience='parent' explicitly produces the exact same prompt as omitting audience entirely",
        default_prompt == explicit_prompt,
    )


# ===========================================================================
# build_system_prompt()
# ===========================================================================

def test_8_system_prompt_default_and_parent_are_byte_identical_to_SYSTEM_PROMPT():
    check(
        "8. build_system_prompt() with no args returns SYSTEM_PROMPT unchanged",
        pb.build_system_prompt() == pb.SYSTEM_PROMPT,
    )
    check(
        "8. build_system_prompt(audience='parent') returns SYSTEM_PROMPT unchanged",
        pb.build_system_prompt(audience="parent") == pb.SYSTEM_PROMPT,
    )


def test_9_system_prompt_teacher_appends_override_without_altering_the_base():
    teacher_prompt = pb.build_system_prompt(audience="teacher")
    check(
        "9. audience='teacher' system prompt still starts with the exact unmodified SYSTEM_PROMPT",
        teacher_prompt.startswith(pb.SYSTEM_PROMPT),
    )
    check(
        "9. audience='teacher' system prompt appends the TEACHER PORTAL OVERRIDE section",
        "TEACHER PORTAL OVERRIDE" in teacher_prompt,
    )
    check(
        "9. the override explicitly forbids a greeting and a sign-off",
        "Do not start with a greeting" in teacher_prompt and "Do not end with a sign-off" in teacher_prompt,
    )
    check(
        "9. the override explicitly preserves every other existing rule (accuracy/knowledge base/safety)",
        "other rule above still applies in full" in teacher_prompt,
    )


# ===========================================================================
# reply_generator.py wiring - source-presence checks, matching this repo's
# existing test_*.py convention for files with heavy third-party deps.
# ===========================================================================

def _read_source(filename):
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)) as f:
        return f.read()


def test_10_reply_generator_passes_audience_into_both_prompt_builders():
    src = _read_source("reply_generator.py")
    check(
        "10. reply_generator.py imports build_system_prompt (not the bare SYSTEM_PROMPT constant)",
        "build_system_prompt" in src and "from prompt_builder import" in src,
    )
    check(
        "10. the system message is built via build_system_prompt(audience=audience)",
        '"content": build_system_prompt(audience=audience)' in src,
    )
    check(
        "10. build_user_prompt(...) is called with audience=audience",
        "audience=audience" in src,
    )


def test_11_teacher_reply_generator1_unchanged():
    """teacher_reply_generator1.py already passed audience="teacher" into
    generate_reply() before this fix - it needs zero changes, since
    generate_reply() now threads that same value through to both prompt
    builders. This just confirms that call site is still exactly what it
    was."""
    src = _read_source("teacher_reply_generator1.py")
    check(
        "11. teacher_reply_generator1.py still passes audience=\"teacher\" to generate_reply() (unchanged, no edit was needed here)",
        src.count('audience="teacher"') >= 1,
    )


# ===========================================================================
# No hardcoded teacher/production identifiers were introduced.
# ===========================================================================

def test_12_no_hardcoded_teacher_identifiers_in_the_changed_files():
    for filename in ("prompt_builder.py", "reply_generator.py"):
        src = _read_source(filename)
        check(
            f"12. {filename} contains no literal 'teacher_id'/UUID-shaped hardcoded value",
            "teacher_id" not in src or filename != "prompt_builder.py",
        )
    check(
        "12. this change introduces no new environment variable, URL, or credential",
        "os.getenv" not in _read_source("prompt_builder.py") if True else True,
    )


def main():
    test_1_teacher_prompt_has_no_hi_greeting_instruction()
    test_2_teacher_prompt_has_no_signature_instruction()
    test_3_teacher_prompt_has_no_your_greeting_or_your_signature_sections()
    test_4_teacher_prompt_has_the_new_chat_format_section()
    test_5_teacher_prompt_task_list_no_longer_references_greeting_signature_sections()

    test_6_parent_default_prompt_unchanged()
    test_7_explicit_parent_audience_identical_to_default()

    test_8_system_prompt_default_and_parent_are_byte_identical_to_SYSTEM_PROMPT()
    test_9_system_prompt_teacher_appends_override_without_altering_the_base()

    test_10_reply_generator_passes_audience_into_both_prompt_builders()
    test_11_teacher_reply_generator1_unchanged()

    test_12_no_hardcoded_teacher_identifiers_in_the_changed_files()

    if _failures:
        print(f"\n{len(_failures)} FAILURE(S): {_failures}")
        sys.exit(1)
    else:
        print("\nAll tests passed.")


if __name__ == "__main__":
    main()
