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

    history = history or ""

    print("Classifier subject:", subject)
    print("Classifier body:", repr(body))

    prompt = f"""
You are Coral Academy's Email Classification Assistant.

Your task is to analyze an incoming email and determine how Coral Academy should handle it.

Return ONLY valid JSON.

Do not include markdown.

Do not include explanations.

--------------------------------------------------
AVAILABLE INFORMATION
--------------------------------------------------

Current Email

Subject:
{subject}

Body:
{body}

Conversation History:

{history}

--------------------------------------------------
WORKFLOW
--------------------------------------------------

Before producing the JSON, internally complete these steps.

Step 1

Determine the sender's primary intent.

Possible intents include:

• asking a question
• requesting information
• requesting an action
• admissions enquiry
• class enquiry
• enrollment enquiry
• billing enquiry
• reporting absence
• reporting an issue
• complaint
• feedback
• cancellation
• refund request
• general conversation

--------------------------------------------------

Step 2

Determine whether Coral Academy should reply.

Reply required:

• questions
• requests
• admissions
• enrollment
• billing
• technical support
• complaints
• feedback

Reply usually NOT required:

• newsletters
• automated notifications
• receipts
• deployment alerts
• monitoring emails
• spam
• marketing

--------------------------------------------------

Step 3

Determine whether AI can safely draft a reply.

Always require human review when the email:

• requests refunds
• requests policy exceptions
• contains complaints
• concerns legal matters
• concerns child safety
• concerns staff behaviour
• contains harassment or bullying
• lacks sufficient information
• contains conflicting information
• confidence is below 80%

--------------------------------------------------

Step 4

Determine priority.

Urgent

High

Medium

Low

Priority should reflect business impact, not emotional wording.

--------------------------------------------------

Step 5

Choose the most appropriate category.

Allowed Categories

Admissions
Teacher
Billing
Urgent
General

--------------------------------------------------
OUTPUT RULES
--------------------------------------------------

requires_review

TRUE when:

• confidence < 80
• complaint
• refund
• legal
• child safety
• staff conduct
• policy exception
• insufficient information

needs_reply

TRUE if Coral Academy should respond.

FALSE otherwise.

reply_type

If requires_review = true

reply_type = "human"

If requires_review = false AND needs_reply = true

reply_type = "automatic"

If needs_reply = false

reply_type = "none"

--------------------------------------------------
SUMMARY
--------------------------------------------------

The summary should:

• be one sentence
• describe the customer's request
• avoid unnecessary details
• not exceed 30 words

--------------------------------------------------
Return ONLY this JSON

{{
  "category": "...",
  "priority": "...",
  "summary": "...",
  "requires_review": true,
  "confidence": 93,
  "needs_reply": true,
  "reply_type": "human"
}}
"""

    try:

        response = client.chat.completions.create(
            model="gpt-5-nano",
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": """
You classify emails for Coral Academy.

Follow the workflow exactly.

Return only valid JSON.
"""
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        result = json.loads(response.choices[0].message.content)

        # Validate AI output
        required_keys = {
            "category",
            "priority",
            "summary",
            "requires_review",
            "confidence",
            "needs_reply",
            "reply_type",
        }

        if not required_keys.issubset(result):
            raise ValueError("Incomplete AI response.")

        # Business Rule Overrides
        text_content = (subject + " " + body).lower()

        human_keywords = [
            "complaint",
            "refund",
            "legal",
            "lawyer",
            "sue",
            "waiver",
            "scholarship",
            "bullying",
            "harassment",
            "teacher behaviour",
            "teacher behavior",
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
            "reply_type": "human",
        }