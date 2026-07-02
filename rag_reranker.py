import json
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"), 
    base_url="https://openrouter.ai/api/v1"
)


def rerank_emails(subject, body, candidates):
    email_list = ""

    for email in candidates:
        email_list += f"""
ID: {email[0]}

Similarity Score: {email[7]:.2%}

Subject:
{email[2]}

Body:
{email[3][:1200]}

--------------------------------------------------
"""

    prompt = f"""
You are selecting historical email examples for an AI email assistant.

Your job is NOT to write a reply.

Your job is to choose the THREE historical emails that will help write the best reply.



Rules:

Rank the historical emails using these priorities:

1. Match the underlying reason.
   (illness, vacation, billing, admissions, homework, etc.)

2. Match the requested action.
   (absence, cancellation, reschedule, refund, question, etc.)

3. Match the communication intent.
   (informing, requesting, asking, apologizing, confirming.)

4. Match the tone and wording where possible.

5. Ignore emails that are only superficially similar.

6. A teacher being unavailable is NOT similar to a parent reporting a child's absence.

7. Similarity score is only a hint. Prioritize semantic meaning over similarity score.

8. Choose diverse examples. Avoid selecting duplicates.

9. It is acceptable to ignore higher similarity emails if lower similarity emails are a better semantic match.

10.Keep each reason brief and based only on the email's content.

11.Use simple english

Return ONLY valid JSON.

Example:
{{
    "selected":[
        {{
            "id":23,
            "reason":"Parent informing the school that a child is absent due to illness."
        }},
        {{
            "id":57,
            "reason":"Similar absence request with rescheduling."
        }},
        {{
            "id":104,
            "reason":"Similar tone and requested action."
        }}
    ]
}}

Incoming Email

Subject:
{subject}

Body:
{body}

Historical Emails

{email_list}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-5-nano",
            temperature=0,
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            response_format={"type": "json_object"}  # Added to guarantee valid JSON formatting
        )

        return json.loads(response.choices[0].message.content)

    except Exception as e:
        print("Reranker Error:", e)
        return {"selected": []}


# Example execution wrapper
# results = search_similar_emails(...)
# reranked = rerank_emails(subject, body, results)
# print(reranked)