from openai import OpenAI
from dotenv import load_dotenv
import os

load_dotenv()

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY")
)

EMBEDDING_MODEL = "text-embedding-3-small"


def generate_embedding(text: str) -> list[float]:

    if not text.strip():
        raise ValueError("Empty text.")

    try:

        response = client.embeddings.create(
            model=EMBEDDING_MODEL,
            input = text[:8000]
        )

        return response.data[0].embedding

    except Exception as e:

        print(f"Embedding Error: {e}")
        raise