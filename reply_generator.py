#reply_generator.py
import os
import re

from dotenv import load_dotenv
from openai import OpenAI

import time

from ai_logger import save_ai_log

# Catches teacher/staff-only content leaking into a parent-facing reply —
# the same red-flag phrases prompt_builder.py's KNOWLEDGE RETRIEVAL section
# already warns the model away from, kept here as a deterministic backstop
# and defense-in-depth layer (the primary protection is the audience-based
# retrieval filter in knowledge_search.py, which stops Teaching-category
# content from reaching this function at all for a parent-facing email).
#
# Confirmed this session that the prompt-only instruction does not reliably
# hold on its own (reproduced live: a "Class Cancellation & Rescheduling"
# article's internal procedure - "Email teachers@coralacademy.com with the
# reason for cancellation... Our coordination team will identify a suitable
# rescheduled time" - leaked near-verbatim into a parent's reschedule
# reply despite that exact phrase being named as a red flag in the prompt).
#
# A 30-day production audit (this session) additionally confirmed the model
# doesn't only quote red-flag sentences verbatim - it can blend/paraphrase
# them into new wording the original 6 literal phrases didn't cover: a real
# parent-facing draft said "our platform team will identify a suitable
# Friday time and update the enrolled parents," which matched none of the
# patterns below at the time. `platform team will \w+` generalizes the old
# literal "platform team will assist" to any single-word verb (assist,
# identify, help, ...) instead of only that one exact phrase; the
# (update|notify|inform) ... enrolled (parents|families) pattern catches
# that same leak's other half. Both stay narrow and verb-anchored
# specifically so they don't fire on ordinary words like "teacher," "class,"
# "reschedule," "parent," "enrolled," or "schedule" on their own.
_TEACHER_FACING_LEAK_PATTERNS = re.compile(
    r"teachers@coralacademy\.com"
    r"|as an instructor"
    r"|your credibility"
    r"|coordination team"
    r"|post an announcement"
    r"|platform team will \w+"
    r"|(update|notify|inform) (the )?enrolled (parents|families)",
    re.IGNORECASE,
)

from prompt_builder import (
    SYSTEM_PROMPT,
    build_user_prompt,
)

load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1",
)


def generate_reply(
    gmail_message_id,
    subject,
    body,
    category,
    priority,
    thread_history,
    historical_emails,
    knowledge=None,
    source=None,
    customer_name=None,
    email_date=None,
    audience="parent",
    llm_client=None,
    live_class_context=None,
):
    """
    Generates an AI draft reply using:
    - Current email
    - Conversation history
    - Coral Academy Knowledge Base
    - Historical emails (style only)

    Returns (reply_text, status), where status is one of:
    - "ok": reply_text is a real generated draft
    - "no_reply": the model's own NO_REPLY sentinel — a considered "not
      enough information", not a fault. reply_text is "".
    - "blocked_safety_net": the _TEACHER_FACING_LEAK_PATTERNS regex fired
      on the model's output. reply_text is "".
    - "error": the OpenRouter call itself failed. reply_text is "".

    audience is an explicit "parent" or "teacher" signal from the caller -
    never inferred here from category/source/subject/knowledge. The
    _TEACHER_FACING_LEAK_PATTERNS safety net only ever applies when
    audience="parent": its entire purpose is keeping staff-only wording out
    of a parent-facing reply, so it has no reason to fire on
    audience="teacher" output, where that same wording is normal, correct
    content (e.g. explaining a cancellation/rescheduling process to the
    teacher who asked about it). For audience="teacher", the regex is
    simply never evaluated - generation proceeds exactly as it did before
    this safety net existed.

    llm_client is an optional injected OpenAI-family client (see
    ai_classifier.ai_triage()'s matching docstring for the full reasoning).
    Defaults to the shared module-level `client` when omitted - every
    caller today.

    live_class_context is an optional, pre-formatted text block (built by
    live_class_intent.py's build_prompt_block()) carrying CURRENT,
    authoritative live Coral class-catalog facts for this email - only
    ever supplied by the parent pipeline (process_email.py), and only
    when the email looked like it needed current price/schedule/teacher/
    enrollment data AND that data was safely resolved to exactly one live
    class. When supplied, it's prepended ahead of the existing prompt,
    clearly labeled as more current than the Knowledge Base below it.
    Every other caller (Teacher Portal, contact-form) omits this
    entirely, so the prompt is built exactly as before this parameter
    existed - it's additive only.
    """

    active_client = llm_client or client

    try:
        print("\nKNOWLEDGE OBJECT BEFORE PROMPT")
        print("LEN AFTER SEARCH:", len(knowledge or []))

        for i, k in enumerate(knowledge or [], 1):
            print(i, k["title"], "|", k["section"], "|", id(k))
        
        user_prompt = build_user_prompt(
            subject=subject,
            body=body,
            category=category,
            priority=priority,
            thread_history=thread_history,
            knowledge=knowledge or [],
            similar_emails=historical_emails or [],
            source=source,
            customer_name=customer_name,
            email_date=email_date,
        )

        # Prepended, not merged into prompt_builder.py's own prompt -
        # keeps all Coral-live-data-specific prompt text isolated here,
        # so the existing, extensively-tuned RAG prompt stays completely
        # untouched for every caller that doesn't pass this. See this
        # function's live_class_context docstring above.
        if live_class_context:
            user_prompt = (
                f"{live_class_context}\n\n"
                "==================================================\n\n"
                "GENERAL KNOWLEDGE AND EMAIL DETAILS BELOW (the Coral "
                "Academy Knowledge Base within this section may be less "
                "current than the LIVE CORAL CLASS DATA above for any "
                "price/schedule/teacher/enrollment fact):\n\n"
                f"{user_prompt}"
            )

        # Safe metadata only - never the customer's own subject/body or the
        # assembled prompt built from them, which used to be printed here
        # in full on every single generation call.
        print(f"\nBuilding reply prompt - gmail_message_id={gmail_message_id} category={category} priority={priority}")

        print("\nKNOWLEDGE RETRIEVED:")
        for i, k in enumerate(knowledge or [], 1):
            print(
                i,
                k.get("title"),
                "|",
                k.get("section"),
                "|",
                round(k.get("similarity", 0), 3),
            )

        # Count only - historical email subjects are redacted before
        # storage, but still customer-adjacent content that doesn't need
        # to be printed to list how many were used.
        print(f"\nHistorical examples retrieved: {len(historical_emails or [])}")

        start_time = time.time()


        #with open("last_prompt.txt", "w", encoding="utf-8") as f:
         #   f.write(user_prompt)
        
        response = active_client.chat.completions.create(
            model="gpt-5-nano",
            temperature=0.3,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
        )

        elapsed_ms = int((time.time() - start_time) * 1000)

        reply = response.choices[0].message.content.strip()

        # Length and timing only - never the generated draft itself, which
        # is customer-facing content built from the customer's own email.
        print(f"Reply generated - gmail_message_id={gmail_message_id} length={len(reply)} elapsed_ms={elapsed_ms}")

        usage = response.usage

        knowledge_log = []

        for item in knowledge or []:

            knowledge_log.append({
                "source": item.get("source"),
                "title": item.get("title"),
                "similarity": item.get("similarity"),
            })

        historical_log = []

        for email in historical_emails or []:

            if isinstance(email, dict):

                historical_log.append({
                    "id": email.get("id"),
                    "subject": email.get("subject"),
                })

            else:

                historical_log.append({
                    "id": email[0],
                    "subject": email[2],
                })

        # Captured once so the log line below can report exactly which
        # staff-only phrase triggered the block without printing the
        # surrounding draft text, which is built from the customer's own
        # email and must not be logged. Only evaluated for audience="parent"
        # - see the audience note in this function's docstring for why a
        # teacher-audience draft must never be blocked by this check.
        _leak_match = (
            _TEACHER_FACING_LEAK_PATTERNS.search(reply)
            if reply and audience == "parent"
            else None
        )
        leaked_teacher_content = bool(_leak_match)

        if leaked_teacher_content:
            print(f"Draft blocked - matched staff-only phrase {_leak_match.group()!r} (gmail_message_id={gmail_message_id})")

        save_ai_log(
            gmail_message_id=gmail_message_id,
            model="gpt-5-nano",
            category=category,
            priority=priority,
            reply_type="automatic",
            requires_review=leaked_teacher_content,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
            response_time_ms=elapsed_ms,
            knowledge_used=knowledge_log,
            historical_examples=historical_log,
            thread_history_length=len(thread_history or ""),
            ai_reply=reply,
            error="Draft blocked: contained teacher/staff-only wording not meant for a parent reply" if leaked_teacher_content else None,
        )

        # Explicit status alongside the reply text so a caller can tell WHY a
        # draft came back empty, instead of inferring it from "" alone — the
        # safety-net block, the model's own considered "not enough info"
        # sentinel, and a genuine API/parsing error are three different
        # situations that used to all collapse into the same empty string.
        if leaked_teacher_content:
            return "", "blocked_safety_net"

        if reply == "NO_REPLY":
            return "", "no_reply"

        return reply, "ok"

    except Exception as e:

        save_ai_log(
            gmail_message_id=gmail_message_id,
            model="gpt-5-nano",
            category=category,
            priority=priority,
            reply_type="automatic",
            requires_review=True,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            response_time_ms=0,
            knowledge_used=[],
            historical_examples=[],
            thread_history_length=0,
            ai_reply="",
            error=str(e),
        )

        print("Reply Generator Error:", e)
        return "", "error"