from openai import OpenAI
from dotenv import load_dotenv
import os
import json

load_dotenv()

api_key = os.getenv("OPENAI_API_KEY")

##print(api_key[:10])   # temporary test

client = OpenAI(
    api_key=api_key
)
def ai_triage(text):

    prompt = f"""
You are a school communication assistant.

Analyze the message and return ONLY JSON.

Categories:
Admissions
Teacher
Billing
Urgent
General

Priorities:
Low
Medium
High
Urgent

Return:

{{
  "category": "...",
  "priority": "...",
  "summary": "...",
  "draft_reply": "..."
}}

Message:
{text}
"""

    response = client.chat.completions.create(
        model="gpt-5-nano",
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

    return json.loads(
        response.choices[0].message.content
    )
