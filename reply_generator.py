#reply_generator.py
import os
import re

from dotenv import load_dotenv
from openai import OpenAI

import time

from ai_logger import save_ai_log

# Catches teacher/staff-only content leaking into a parent-facing reply —
# the same red-flag phrases prompt_builder.py's KNOWLEDGE RETRIEVAL section
# already warns the model away from, kept here as a deterministic backstop.
# Confirmed this session that the prompt-only instruction does not reliably
# hold on its own (reproduced live: a "Class Cancellation & Rescheduling"
# article's internal procedure - "Email teachers@coralacademy.com with the
# reason for cancellation... Our coordination team will identify a suitable
# rescheduled time" - leaked near-verbatim into a parent's reschedule reply
# despite that exact phrase being named as a red flag in the prompt).
_TEACHER_FACING_LEAK_PATTERNS = re.compile(
    r"teachers@coralacademy\.com|as an instructor|your credibility|coordination team|post an announcement|platform team will assist",
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
):
    """
    Generates an AI draft reply using:
    - Current email
    - Conversation history
    - Coral Academy Knowledge Base
    - Historical emails (style only)
    """

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

        print("\n" + "=" * 80)
        print("FINAL PROMPT SENT TO GPT")
        print("=" * 80)

        print("\nCURRENT SUBJECT:")
        print(subject)

        print("\nCURRENT BODY:")
        print(body)

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

        print("\nHISTORICAL EMAILS RETRIEVED:")
        for e in (historical_emails or []):
            if isinstance(e, dict):
                print("-", e.get("subject"))
            else:
                print("-", e[2])

        print("\nFULL PROMPT:\n")
        print(user_prompt)

        print("=" * 80)

        start_time = time.time()


        #with open("last_prompt.txt", "w", encoding="utf-8") as f:
         #   f.write(user_prompt)
        
        response = client.chat.completions.create(
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

        print("=" * 80)
        print("GPT GENERATED REPLY")
        print(reply)
        print("=" * 80)

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

        leaked_teacher_content = bool(reply) and bool(_TEACHER_FACING_LEAK_PATTERNS.search(reply))

        if leaked_teacher_content:
            print(f"Draft blocked - contained teacher/staff-only wording not meant for a parent reply ({gmail_message_id}): {reply!r}")

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

        if reply == "NO_REPLY" or leaked_teacher_content:
            return ""

        return reply

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
        return ""