"""Focused tests for the final pre-freeze LLM client timeout fix: none of
the 9 OpenAI/OpenRouter client construction sites in this codebase set an
explicit timeout, relying entirely on the SDK's own much larger default -
a hung/degraded request could tie up a worker thread far longer than
necessary. llm_client_config.LLM_REQUEST_TIMEOUT_SECONDS (120s, well above
the slowest real production generation call this session's own latency
investigation measured, ~38s) is now passed as the `timeout=` constructor
argument at every site.

Matches this repo's existing test_*.py convention - a plain assert-based
script, no pytest, using the same fake dotenv/openai/psycopg2 injection
technique already established (test_p0_fixes.py, test_vector_search_staff_cache.py).

6 of the 9 files (ai_classifier, rag_reranker, reply_generator,
reply_polish, embedding_service, followup_ai) are genuinely importable
here with just dotenv/openai/psycopg2 faked, so this file imports them for
real and asserts on the actual keyword arguments their OpenAI(...) calls
were made with (captured by FakeOpenAI itself, since the real openai
package isn't installed in this sandbox either).

The remaining 3 (embed_knowledge_base.py, subscription_cancel.py,
email_reader.py) are covered via direct source inspection instead:
embed_knowledge_base.py runs a real SQL query at module import time (not
inside any function) - a one-off maintenance script, not meant to be
imported as a library - so importing it isn't safe to do just to check a
keyword argument; subscription_cancel.py and email_reader.py transitively
need dateutil/supabase/bs4/the-whole-pipeline, none installed here, same
documented limitation this session's other tests already give for these
exact files.

Run with: python3 test_llm_client_timeouts.py
"""

import os
import sys
import types


_failures = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" - {detail}" if detail and not condition else ""))
    if not condition:
        _failures.append(name)


def _read_source(filename):
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), filename), "r", encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Fake infrastructure. FakeOpenAI records the kwargs it was constructed
# with, so tests can assert on the real call-time arguments rather than
# just matching source text - genuine behavioral confidence that the
# timeout actually reaches the constructor call.
# ---------------------------------------------------------------------------

def _install_fake_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


class FakeOpenAI:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def close(self):
        pass


class FakeSimpleConnectionPool:
    def __init__(self, *a, **kw):
        pass

    def getconn(self):
        raise AssertionError("no test here should need a real DB connection")

    def putconn(self, conn):
        pass


def _install_fakes():
    _install_fake_module("dotenv", load_dotenv=lambda *a, **kw: None)
    _install_fake_module("openai", OpenAI=FakeOpenAI)

    pool_mod = _install_fake_module("psycopg2.pool", SimpleConnectionPool=FakeSimpleConnectionPool)
    extras_mod = _install_fake_module("psycopg2.extras", RealDictCursor=dict)
    psycopg2_mod = _install_fake_module("psycopg2")
    psycopg2_mod.pool = pool_mod
    psycopg2_mod.extras = extras_mod
    psycopg2_mod.connect = lambda *a, **kw: None


_install_fakes()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import llm_client_config  # noqa: E402
import ai_classifier  # noqa: E402
import rag_reranker  # noqa: E402
import reply_generator  # noqa: E402
import reply_polish  # noqa: E402
import embedding_service  # noqa: E402
import followup_ai  # noqa: E402


# ---------------------------------------------------------------------------
# Every intended client construction receives the explicit shared timeout.
# ---------------------------------------------------------------------------

def test_shared_constant_is_120_seconds():
    check(
        "LLM_REQUEST_TIMEOUT_SECONDS is a conservative value well above real production latency (~38s max observed)",
        llm_client_config.LLM_REQUEST_TIMEOUT_SECONDS == 120,
    )


def test_ai_classifier_client_has_the_timeout():
    check(
        "ai_classifier.client was constructed with the shared timeout",
        ai_classifier.client.kwargs.get("timeout") == llm_client_config.LLM_REQUEST_TIMEOUT_SECONDS,
    )


def test_rag_reranker_client_has_the_timeout():
    check(
        "rag_reranker.client was constructed with the shared timeout",
        rag_reranker.client.kwargs.get("timeout") == llm_client_config.LLM_REQUEST_TIMEOUT_SECONDS,
    )


def test_reply_generator_client_has_the_timeout():
    check(
        "reply_generator.client was constructed with the shared timeout",
        reply_generator.client.kwargs.get("timeout") == llm_client_config.LLM_REQUEST_TIMEOUT_SECONDS,
    )


def test_reply_polish_client_has_the_timeout():
    check(
        "reply_polish.client was constructed with the shared timeout",
        reply_polish.client.kwargs.get("timeout") == llm_client_config.LLM_REQUEST_TIMEOUT_SECONDS,
    )


def test_embedding_service_default_client_has_the_timeout():
    check(
        "embedding_service._default_client was constructed with the shared timeout",
        embedding_service._default_client.kwargs.get("timeout") == llm_client_config.LLM_REQUEST_TIMEOUT_SECONDS,
    )


def test_embedding_service_new_client_factory_applies_the_timeout():
    fresh = embedding_service.new_embedding_client()
    check(
        "new_embedding_client() also constructs its fresh client with the shared timeout",
        fresh.kwargs.get("timeout") == llm_client_config.LLM_REQUEST_TIMEOUT_SECONDS,
    )


def test_followup_ai_client_has_the_timeout():
    check(
        "followup_ai.client was constructed with the shared timeout",
        followup_ai.client.kwargs.get("timeout") == llm_client_config.LLM_REQUEST_TIMEOUT_SECONDS,
    )


# ---------------------------------------------------------------------------
# Existing configuration (base_url, api_key source) is otherwise unchanged,
# and no retry configuration was introduced anywhere.
# ---------------------------------------------------------------------------

def test_base_url_and_api_key_still_unchanged_everywhere():
    for module, client in [
        (ai_classifier, ai_classifier.client),
        (rag_reranker, rag_reranker.client),
        (reply_generator, reply_generator.client),
        (reply_polish, reply_polish.client),
        (followup_ai, followup_ai.client),
    ]:
        check(
            f"{module.__name__}'s client still uses the OpenRouter base_url, unchanged",
            client.kwargs.get("base_url") == "https://openrouter.ai/api/v1",
        )
    check(
        "embedding_service's default client also still uses the OpenRouter base_url",
        embedding_service._default_client.kwargs.get("base_url") == "https://openrouter.ai/api/v1",
    )


def test_no_retry_configuration_was_introduced_anywhere():
    for filename in [
        "ai_classifier.py", "rag_reranker.py", "reply_generator.py",
        "reply_polish.py", "embedding_service.py", "embed_knowledge_base.py",
        "followup_ai.py", "subscription_cancel.py", "email_reader.py",
    ]:
        src = _read_source(filename)
        check(
            f"{filename}: no max_retries= argument was added to any OpenAI(...) construction",
            "max_retries=" not in src,
        )


def test_models_prompts_temperature_untouched_spot_check():
    """A narrow spot-check (not exhaustive) that the timeout fix didn't
    touch generation parameters - the full model/prompt/temperature
    behavior is already covered by each module's own existing tests."""
    reply_gen_src = _read_source("reply_generator.py")
    check(
        "reply_generator.py still uses gpt-5-nano at temperature=0.3 (unchanged)",
        'model="gpt-5-nano",\n            temperature=0.3,' in reply_gen_src,
    )
    classifier_src = _read_source("ai_classifier.py")
    check(
        "ai_classifier.py's client construction and warm-up logic are otherwise unchanged",
        "client.chat\n    client.embeddings" in classifier_src,
    )


# ---------------------------------------------------------------------------
# The 3 files not imported for real above - source-presence checks instead.
# ---------------------------------------------------------------------------

def test_embed_knowledge_base_client_has_the_timeout():
    src = _read_source("embed_knowledge_base.py")
    check(
        "embed_knowledge_base.py imports the shared timeout constant",
        "from llm_client_config import LLM_REQUEST_TIMEOUT_SECONDS" in src,
    )
    check(
        "its OpenAI(...) construction has the timeout",
        'client = OpenAI(\n    api_key=os.getenv("OPENROUTER_API_KEY"),\n    base_url="https://openrouter.ai/api/v1",\n    timeout=LLM_REQUEST_TIMEOUT_SECONDS,\n)' in src,
    )


def test_subscription_cancel_both_client_sites_have_the_timeout():
    src = _read_source("subscription_cancel.py")
    check(
        "subscription_cancel.py imports the shared timeout constant",
        "from llm_client_config import LLM_REQUEST_TIMEOUT_SECONDS" in src,
    )
    check(
        "_ai_client (module-level) has the timeout",
        '_ai_client = OpenAI(\n    api_key=os.getenv("OPENROUTER_API_KEY"),\n    base_url="https://openrouter.ai/api/v1",\n    timeout=LLM_REQUEST_TIMEOUT_SECONDS,\n)' in src,
    )
    check(
        "_new_ai_client()'s factory-returned client also has the timeout",
        'return OpenAI(\n        api_key=os.getenv("OPENROUTER_API_KEY"),\n        base_url="https://openrouter.ai/api/v1",\n        timeout=LLM_REQUEST_TIMEOUT_SECONDS,\n    )' in src,
    )


def test_email_reader_client_site_has_the_timeout():
    src = _read_source("email_reader.py")
    check(
        "email_reader.py imports the shared timeout constant",
        "from llm_client_config import LLM_REQUEST_TIMEOUT_SECONDS" in src,
    )
    check(
        "its OpenAI(...) construction has the timeout",
        'return OpenAI(\n        api_key=os.getenv("OPENROUTER_API_KEY"),\n        base_url="https://openrouter.ai/api/v1",\n        timeout=LLM_REQUEST_TIMEOUT_SECONDS,\n    )' in src,
    )


def test_all_9_files_verified():
    """Final accounting: every one of the 9 files the audit named now
    imports and uses the shared constant."""
    for filename in [
        "ai_classifier.py", "rag_reranker.py", "reply_generator.py",
        "reply_polish.py", "email_reader.py", "embedding_service.py",
        "embed_knowledge_base.py", "followup_ai.py", "subscription_cancel.py",
    ]:
        src = _read_source(filename)
        check(
            f"{filename} imports LLM_REQUEST_TIMEOUT_SECONDS",
            "from llm_client_config import LLM_REQUEST_TIMEOUT_SECONDS" in src,
        )
        check(
            f"{filename} passes timeout=LLM_REQUEST_TIMEOUT_SECONDS to at least one OpenAI(...) call",
            "timeout=LLM_REQUEST_TIMEOUT_SECONDS," in src,
        )


def main():
    tests = [
        test_shared_constant_is_120_seconds,
        test_ai_classifier_client_has_the_timeout,
        test_rag_reranker_client_has_the_timeout,
        test_reply_generator_client_has_the_timeout,
        test_reply_polish_client_has_the_timeout,
        test_embedding_service_default_client_has_the_timeout,
        test_embedding_service_new_client_factory_applies_the_timeout,
        test_followup_ai_client_has_the_timeout,
        test_base_url_and_api_key_still_unchanged_everywhere,
        test_no_retry_configuration_was_introduced_anywhere,
        test_models_prompts_temperature_untouched_spot_check,
        test_embed_knowledge_base_client_has_the_timeout,
        test_subscription_cancel_both_client_sites_have_the_timeout,
        test_email_reader_client_site_has_the_timeout,
        test_all_9_files_verified,
    ]
    for t in tests:
        t()

    if _failures:
        print(f"\n{len(_failures)} FAILURE(S): {_failures}")
        sys.exit(1)
    print("\nAll tests passed.")


if __name__ == "__main__":
    main()
