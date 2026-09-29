"""Focused tests for the two generation-quality fixes to prompt_builder.py:

1. build_knowledge_section() used to append its "IMPORTANT - the CURRENT
   EMAIL is the only email you should answer" reminder once PER knowledge
   item (byte-for-byte duplicate text repeated N times for an N-item
   retrieval). It now appears exactly once for the whole section.

2. ACCOUNT_DISPLAY_NAMES used to resolve every known parent-facing
   mailbox's organization sign-off to "Coral Team". It now resolves to
   "Coral Academy" for every confirmed parent-facing source
   (support@/lucy@/engineering@coralacademy.com, and main.py's
   source="contact_form"), while DEFAULT_DISPLAY_NAME - the fallback
   Teacher Portal's generate_reply() call also resolves to, since it
   never passes a source at all - is deliberately left untouched.

prompt_builder.py has zero imports of its own, so it's imported directly
here - no fake-infrastructure modules are needed, unlike most of this
repo's other test_*.py files.

Matches this repo's existing test_*.py convention: a plain script using
only assert statements and the standard library.

Run with: python3 test_prompt_builder_fixes.py
"""

import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import prompt_builder as pb  # noqa: E402


_failures = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" - {detail}" if detail and not condition else ""))
    if not condition:
        _failures.append(name)


# ---------------------------------------------------------------------------
# The exact reminder text, verbatim, as it existed (inside the loop) before
# this fix - used below to prove the wording itself was not rewritten, only
# its position moved.
# ---------------------------------------------------------------------------

_EXPECTED_REMINDER = (
    "IMPORTANT\n\n"
    "The CURRENT EMAIL below is the only email you should answer.\n\n"
    "Conversation History is provided only for context.\n\n"
    "If the customer's latest email starts a new topic or asks a different question than earlier emails, answer ONLY the latest topic.\n\n"
    "Do not continue discussing previous issues unless the customer explicitly asks about them."
)


_THREE_ITEMS = [
    {
        "source": "class", "similarity": 0.731, "title": "Astronomy 101: Learn About Space",
        "section": "Pricing", "category": "science", "content": "$20.00 per session",
        "url": "https://www.coralacademy.com/class/spacerockssummercamp",
    },
    {
        "source": "class", "similarity": 0.62, "title": "Geology & Earth Science Explorers",
        "section": "Description", "category": "science", "content": "Rocks, fossils, volcanoes.",
        "url": "https://www.coralacademy.com/class/geologybyamalia",
    },
    {
        "source": "help_center", "similarity": 0.55, "title": "Refund Policy",
        "section": "Policies", "category": "billing", "content": "Refunds within 7 days.",
        "url": "https://www.coralacademy.com/help/refunds",
    },
]


# ===========================================================================
# PART 1 - knowledge-reminder deduplication.
# ===========================================================================

def test_1_reminder_appears_exactly_once_with_multiple_items():
    text = pb.build_knowledge_section(_THREE_ITEMS)
    check(
        "1. the reminder appears exactly once for a 3-item retrieval, not once per item",
        text.count("The CURRENT EMAIL below is the only email you should answer.") == 1,
        f"found {text.count('The CURRENT EMAIL below is the only email you should answer.')} occurrence(s)",
    )
    check(
        "1. the 'IMPORTANT' heading itself also appears exactly once",
        text.count("IMPORTANT") == 1,
    )


def test_2_reminder_wording_preserved_verbatim():
    text = pb.build_knowledge_section(_THREE_ITEMS)
    check(
        "2. the reminder's exact wording is unchanged - present verbatim in the output",
        _EXPECTED_REMINDER in text,
    )


def test_3_all_knowledge_items_still_present_and_unchanged():
    text = pb.build_knowledge_section(_THREE_ITEMS)
    for item in _THREE_ITEMS:
        check(f"3. title present: {item['title']!r}", item["title"] in text)
        check(f"3. content present: {item['content']!r}", item["content"] in text)
        check(f"3. url present: {item['url']!r}", item["url"] in text)
        check(f"3. section present: {item['section']!r}", f"Section:\n{item['section']}" in text)
        check(f"3. category present: {item['category']!r}", f"Category:\n{item['category']}" in text)
        check(f"3. similarity present: {item['similarity']!r}", f"Similarity:\n{item['similarity']}" in text)
        check(f"3. source present: {item['source']!r}", f"Source:\n{item['source']}" in text)


def test_4_item_order_preserved():
    text = pb.build_knowledge_section(_THREE_ITEMS)
    positions = [text.index(item["title"]) for item in _THREE_ITEMS]
    check(
        "4. items appear in the same order they were passed in",
        positions == sorted(positions),
    )
    check("4. item numbering ('Knowledge Item 1/2/3') is unchanged", all(f"Knowledge Item {i}" in text for i in (1, 2, 3)))


def test_5_zero_items_behavior_unchanged():
    check(
        "5. an empty knowledge list still returns the exact original short-circuit string",
        pb.build_knowledge_section([]) == "No relevant Coral Academy Knowledge was found.",
    )
    check(
        "5. the empty-list case never contains the reminder text at all (matches prior behavior)",
        "IMPORTANT" not in pb.build_knowledge_section([]),
    )
    check(
        "5. None is treated the same as an empty list",
        pb.build_knowledge_section(None) == "No relevant Coral Academy Knowledge was found.",
    )


def test_6_single_item_reminder_still_appears_once():
    text = pb.build_knowledge_section([_THREE_ITEMS[0]])
    check("6. a single-item retrieval still gets exactly one reminder", text.count("IMPORTANT") == 1)


# ===========================================================================
# PART 2 - parent-facing organization sign-off.
# ===========================================================================

_PARENT_SOURCES = [
    "support@coralacademy.com",
    "lucy@coralacademy.com",
    "engineering@coralacademy.com",
    "contact_form",
]


def test_7_all_known_parent_sources_resolve_to_coral_academy():
    for source in _PARENT_SOURCES:
        name = pb.ACCOUNT_DISPLAY_NAMES.get(source, pb.DEFAULT_DISPLAY_NAME)
        check(
            f"7. source={source!r} resolves to a display name containing 'Coral Academy'",
            "Coral Academy" in name,
            f"got {name!r}",
        )
        check(
            f"7. source={source!r} no longer resolves to 'Coral Team'",
            "Coral Team" not in name,
            f"got {name!r}",
        )


def test_8_lucys_personal_line_preserved():
    check(
        "8. lucy@coralacademy.com keeps her personal first line, with only the org name fixed",
        pb.ACCOUNT_DISPLAY_NAMES["lucy@coralacademy.com"] == "Lucy\nCoral Academy",
    )


def test_9_default_display_name_untouched_protects_teacher_portal():
    check(
        "9. DEFAULT_DISPLAY_NAME is still exactly 'Coral Team' - unchanged, since "
        "teacher_reply_generator1.py's generate_reply() call resolves to this same "
        "fallback (it never passes a source at all)",
        pb.DEFAULT_DISPLAY_NAME == "Coral Team",
    )
    check(
        "9. a source not present in ACCOUNT_DISPLAY_NAMES (simulating the Teacher "
        "Portal's implicit source=None) still resolves to 'Coral Team', proving this "
        "fix does not silently change Teacher Portal's signature",
        pb.ACCOUNT_DISPLAY_NAMES.get(None, pb.DEFAULT_DISPLAY_NAME) == "Coral Team",
    )


def test_10_end_to_end_prompt_uses_coral_academy_for_parent_sources():
    """Builds the real, full user prompt (as reply_generator.py would) for
    each confirmed parent-facing source and checks the actual YOUR
    SIGNATURE section the model is instructed to use."""
    for source in _PARENT_SOURCES:
        prompt = pb.build_user_prompt(
            subject="Test", body="Hello", category="General", priority="Medium",
            thread_history="", knowledge=[], similar_emails=[],
            source=source, customer_name="Test Parent",
            email_date=datetime(2026, 9, 29, tzinfo=timezone.utc),
        )
        check(
            f"10. end-to-end prompt for source={source!r} instructs the model to sign with 'Coral Academy'",
            "Best regards,\nCoral Academy" in prompt or "Best regards,\nLucy\nCoral Academy" in prompt,
        )
        check(
            f"10. end-to-end prompt for source={source!r} never instructs 'Coral Team'",
            "Coral Team" not in prompt,
        )


def test_11_end_to_end_prompt_unset_source_still_coral_team():
    """Mirrors exactly how teacher_reply_generator1.py calls build_user_prompt
    indirectly via generate_reply() - no source kwarg at all."""
    prompt = pb.build_user_prompt(
        subject="Test", body="Hello", category="General", priority="Medium",
        thread_history="", knowledge=[], similar_emails=[],
    )
    check(
        "11. omitting source entirely (Teacher Portal's actual call shape) still "
        "signs with 'Coral Team' - confirms Teacher Portal is unaffected",
        "Best regards,\nCoral Team" in prompt,
    )


def main():
    test_1_reminder_appears_exactly_once_with_multiple_items()
    test_2_reminder_wording_preserved_verbatim()
    test_3_all_knowledge_items_still_present_and_unchanged()
    test_4_item_order_preserved()
    test_5_zero_items_behavior_unchanged()
    test_6_single_item_reminder_still_appears_once()

    test_7_all_known_parent_sources_resolve_to_coral_academy()
    test_8_lucys_personal_line_preserved()
    test_9_default_display_name_untouched_protects_teacher_portal()
    test_10_end_to_end_prompt_uses_coral_academy_for_parent_sources()
    test_11_end_to_end_prompt_unset_source_still_coral_team()

    if _failures:
        print(f"\n{len(_failures)} FAILURE(S): {_failures}")
        sys.exit(1)
    else:
        print("\nAll tests passed.")


if __name__ == "__main__":
    main()
