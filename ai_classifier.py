from openai import OpenAI
from dotenv import load_dotenv
import os
import json


load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1"
)

def ai_triage(subject, body,history=None, images=None):

    text = f"""
Subject: {subject}

Thread History:
{history}

Message:
{body}
"""

    prompt = f"""
You are a school communication assistant.

Analyze the message and return ONLY valid JSON.

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
  "draft_reply": "...",
  "requires_review": true

}}

Message:
{text}
"""

    try:

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

    except Exception as e:

        print("AI Error:", e)

        return {
            "category": "General",
            "priority": "Low",
            "summary": f"AI Error: {str(e)}",
            "draft_reply": ""
        }