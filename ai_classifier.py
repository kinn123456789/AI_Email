from openai import OpenAI
from dotenv import load_dotenv
import os
import json

load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1"
)

def ai_triage(subject, body, history=None, images=None):
    text = f"""
Subject: {subject}

Thread History:
{history}

Message:
{body}
"""

    prompt = f"""
You are a school communication assistant. Return ONLY valid JSON.
Do not include markdown, explanations, or any text before or after the JSON.

Categories: Admissions, Teacher, Billing, Urgent, General
Priorities: Low, Medium, High, Urgent

Set requires_review to true if:
- Confidence < 80
- The email is ambiguous
- Involves sensitive decisions, complaints, refunds, legal matters, or human judgment.

Always set requires_review = true for:
- Complaints, dissatisfaction, refund requests, policy exceptions, legal issues, 
  child safety concerns, staff conduct issues, or lack of information.

Workflow Rules:
If requires_review = true: needs_reply = true, reply_type = "human"
If requires_review = false AND needs_reply = true: reply_type = "automatic"
If requires_review = false AND needs_reply = false: reply_type = "none"

Return JSON object:
{{
  "category": "...",
  "priority": "...",
  "summary": "...",
  "requires_review": true,
  "confidence": 93,
  "needs_reply": false,
  "reply_type": "human"
}}

Message to triage:
{text}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-5-nano",
            messages=[{"role": "user", "content": prompt}]
        )

        result = json.loads(response.choices[0].message.content)

        # Keyword Override
        text_content = (subject + " " + body).lower()
        human_keywords = [
            "complaint", "refund", "legal", "lawyer", "sue", "waiver", 
            "scholarship", "bullying", "harassment", "teacher behaviour", 
            "teacher behavior"
        ]

        if any(word in text_content for word in human_keywords):
            result["requires_review"] = True
            result["needs_reply"] = True
            result["reply_type"] = "human"

            if result.get("priority") in ["Low", "Medium"]:
                result["priority"] = "High"
        print(json.dumps(result, indent=2))
        return result

    except Exception as e:
        print("AI Error:", e)
        return {
            "category": "General",
            "priority": "Low",
            "summary": f"AI Error: {str(e)}",
            "requires_review": True,
            "confidence": 0,
            "needs_reply": False,
            "reply_type": "human"
        }