from openai import OpenAI
from dotenv import load_dotenv
import os

load_dotenv()

_default_client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY")
)

EMBEDDING_MODEL = "text-embedding-3-small"


def new_embedding_client():
    """A fresh, isolated client for callers that run concurrently with
    other embedding calls — the shared _default_client above isn't safe to
    use from multiple threads at once (same class of issue already found
    and fixed for the Supabase client elsewhere in this app). Must be
    closed with close_embedding_client() after use."""

    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENROUTER_API_KEY")
    )


def close_embedding_client(client):

    try:
        client.close()
    except Exception:
        pass


def generate_embedding(text: str, client=None) -> list[float]:

    if not text.strip():
        raise ValueError("Empty text.")

    active_client = client or _default_client

    try:

        response = active_client.embeddings.create(
            model=EMBEDDING_MODEL,
            input = text[:8000]
        )

        return response.data[0].embedding

    except Exception as e:

        print(f"Embedding Error: {e}")
        raise