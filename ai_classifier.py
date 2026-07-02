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

Return ONLY valid JSON.
Do not include markdown, explanations, or any text before or after the JSON.

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

Confidence Guidelines:

95-100: Very certain. The category, priority, summary and reply requirement are clear.

80-94: Mostly certain with minor ambiguity.

60-79: Some uncertainty.

40-59: Multiple interpretations are possible.

0-39: Low confidence. Human review is recommended.

Return only an integer between 0 and 100.


Return a JSON object with the following fields.

Set requires_review to true if:
- The confidence is low.
- The email is ambiguous.
- The email involves sensitive decisions, complaints, refunds, legal matters, or anything requiring human judgment.
If you are unsure whether an email requires a reply, set:
- needs_reply = true
- requires_review = true

Otherwise set requires_review to false.

Always include every field in the JSON response.
Do not omit any fields.

{{
  
  "category": "...",
  "priority": "...",
  "summary": "...",
  "requires_review": true,
  "confidence":93,
  "needs_reply": false

}}

Set needs_reply to true ONLY if a human staff member at Coral Academy should send a reply.

Otherwise set needs_reply to false.

true
- Parent emails
- Student emails
- Admissions questions
- Billing questions
- Scheduling requests
- Homework questions
- Teacher communication
- Any email where a school staff member should respond

false
- Password reset emails
- Security codes
- Marketing emails
- Newsletters
- Receipts
- Payment confirmations
- Deployment alerts
- Server notifications
- Monitoring alerts
- Social media notifications
- Automated system messages


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
            "requires_review": True,
            "confidence": 0,
            "needs_reply": False
        }
    
