#reply_polish.py
"""Phase 1 of the future "AI Polish" feature (see the read-only
architecture investigation this follows): a small, isolated module that
takes the CURRENT HUMAN-EDITED draft and returns a grammar/clarity/tone-
polished version of that exact text - never a second reply-generation
pass, never RAG, never historical emails, never live-class data, never
the original customer email/thread. The draft is the sole and complete
input this module ever sees.

Deliberately separate from reply_generator.py, which this module does
NOT import, call, or share any state with - see main.py's
POST /email/{email_id}/polish for the endpoint that calls this, which
also never persists anything to the database (not messages.ai_draft_reply,
not messages.final_reply, no new row of any kind). The human-edited
draft remains the sole source of truth; nothing here overrides it on
its own - only a future, explicit human action (not built yet) would
ever apply a polished result, exactly like the existing Send flow is
the only thing that ever writes a reply to the database or sends real
email.
"""

import os
import time

from dotenv import load_dotenv
from openai import OpenAI

from ai_logger import save_ai_log

load_dotenv()

# Same construction every other LLM-calling module in this codebase
# already uses (ai_classifier.py, rag_reranker.py, reply_generator.py,
# email_reader.py's _new_llm_client()) - no shared client abstraction
# exists in this codebase yet, and this phase deliberately doesn't
# introduce one (see the read-only investigation this follows).
client = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1",
)


# Passed as its own system message, never concatenated with the draft -
# the draft is untrusted user-provided text, and string-joining it into
# this instruction could let it be misread as part of the instruction
# itself. See polish_draft() below: the system message and the user
# message (the draft, verbatim) are always two separate entries in the
# `messages` list sent to the API.
POLISH_SYSTEM_PROMPT = """
You are an email polishing assistant for Coral Academy.

Improve the provided draft's grammar, clarity, readability, and
professionalism using natural American-style customer-service English.

Preserve the meaning and all factual information exactly.

NEVER change, remove, invent, or reinterpret:

- prices
- currency
- dates
- times
- time zones
- names
- student/learner information
- class names
- teacher names
- policies
- commitments
- promises
- URLs
- email addresses
- phone numbers
- IDs
- manually added information

Do not add new facts.

Do not add new promises or commitments.

Do not invent explanations.

Do not answer the customer's question differently.

Do not introduce information that is not already present.

Do not use unnatural phrases such as:

- "do the needful"
- "revert back"
- "kindly do..."

Keep the same overall intent, meaning, and level of commitment.

Return ONLY the polished email text.

Do not add commentary.

Do not explain your changes.

Do not surround the answer with quotation marks.
"""


def polish_draft(draft, llm_client=None):
    """Sends exactly one request to OpenRouter/gpt-5-nano asking it to
    polish `draft` in place. Returns (polished_text, status), where
    status is one of:

    - "ok": polished_text is the model's real output.
    - "error": the provider call itself failed, or it returned empty/
      non-text output (treated as a failure, not a valid "nothing to
      polish" outcome - an empty result must never silently blank out a
      perfectly good human-edited draft). polished_text is "" for both.

    This mirrors reply_generator.generate_reply()'s own (reply, status)
    contract for the same class of failure, and never raises - every
    failure path is caught and converted into ("", "error") so a caller
    can rely on this function always returning normally.

    llm_client is an optional injected OpenAI-family client (same
    reasoning as every other LLM module in this codebase - see
    ai_classifier.ai_triage()'s docstring). Defaults to the shared
    module-level `client` when omitted.

    Logging: exactly one ai_logs row is written per call, via the
    existing save_ai_log() (category="Polish"), recording model/token
    counts/response_time_ms/error - the same metrics every other LLM
    call already logs. The draft and the polished text are deliberately
    NEVER passed to save_ai_log() (ai_reply="" always) - stricter than
    reply_generator.py's own convention (which does store the generated
    reply in ai_logs.ai_reply), because this feature's own security
    requirements explicitly forbid logging draft/polished content at
    all, not just omitting it from stdout prints."""

    active_client = llm_client or client

    start_time = time.time()

    try:
        response = active_client.chat.completions.create(
            model="gpt-5-nano",
            temperature=0.3,
            messages=[
                {
                    "role": "system",
                    "content": POLISH_SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": draft,
                },
            ],
        )

        elapsed_ms = int((time.time() - start_time) * 1000)
        polished = (response.choices[0].message.content or "").strip()
        usage = response.usage

        if not polished:
            save_ai_log(
                gmail_message_id=None,
                model="gpt-5-nano",
                category="Polish",
                priority=None,
                reply_type=None,
                requires_review=False,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                total_tokens=usage.total_tokens,
                response_time_ms=elapsed_ms,
                knowledge_used=[],
                historical_examples=[],
                thread_history_length=0,
                ai_reply="",
                error="Polish call returned empty output",
            )
            return "", "error"

        # Length and timing only - never the draft or the polished text
        # itself, both customer-facing content built from the human-
        # edited draft. Matches reply_generator.py's own established
        # print convention.
        print(f"Draft polished - length={len(polished)} elapsed_ms={elapsed_ms}")

        save_ai_log(
            gmail_message_id=None,
            model="gpt-5-nano",
            category="Polish",
            priority=None,
            reply_type=None,
            requires_review=False,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
            response_time_ms=elapsed_ms,
            knowledge_used=[],
            historical_examples=[],
            thread_history_length=0,
            ai_reply="",
            error=None,
        )

        return polished, "ok"

    except Exception as e:

        save_ai_log(
            gmail_message_id=None,
            model="gpt-5-nano",
            category="Polish",
            priority=None,
            reply_type=None,
            requires_review=False,
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

        print("Polish Error:", e)
        return "", "error"
