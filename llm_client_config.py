#llm_client_config.py
"""Single shared constant for every OpenAI/OpenAI-compatible (OpenRouter)
client construction in this codebase - ai_classifier.py, rag_reranker.py,
reply_generator.py, reply_polish.py, email_reader.py, embedding_service.py,
embed_knowledge_base.py, followup_ai.py, subscription_cancel.py. Added as
part of the final pre-freeze reliability audit's finding that none of the
9 construction sites set an explicit timeout, relying entirely on the
openai SDK's own much larger default - a hung or badly degraded request
could otherwise tie up a worker thread far longer than necessary.

120 seconds is deliberately well above the slowest real production
generation call this session's own read-only latency investigation
measured directly from this app's own ai_logs (~38 seconds) - a genuinely
slow but legitimate reply must never be cut off by this. It's still far
below the SDK's own default, so a hung/degraded request no longer blocks a
worker indefinitely.

Passed as the `timeout=` constructor argument the openai SDK already
supports (verified directly against the pinned openai==2.41.1 source) -
applies to every HTTP call made through that client. Does not add retries,
does not change any model/prompt/temperature, and does not change the
OpenRouter base URL or authentication - purely a per-request ceiling on
how long a single call is allowed to hang."""

LLM_REQUEST_TIMEOUT_SECONDS = 120
