from openai import OpenAI
from dotenv import load_dotenv
import os

load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1"
)


_PARENT_PLACEHOLDER = "[PARENT_NAME]"
_LEARNER_PLACEHOLDER = "[STUDENT_NAME]"


def generate_followup_email(candidate, parent_name, email_number):

    learner_name = candidate.get("learner_name", "your child")
    class_title = candidate.get("class_title")
    # Real parent/learner names never leave the process — the AI only ever
    # sees the placeholder tokens below, and the real names are substituted
    # back in after the response comes back (see try/except below).
    redacted_class_line = f"{_LEARNER_PLACEHOLDER}'s classes: {class_title}" if class_title else ""

    if email_number == 1:

        subject = f"We hope {learner_name} enjoyed the free trial!"

        prompt = f"""
Write a warm, friendly follow-up email.

Parent name: {_PARENT_PLACEHOLDER}
learner name: {_LEARNER_PLACEHOLDER}
{redacted_class_line}

{_LEARNER_PLACEHOLDER} completed a free trial yesterday.

Thank the parent for trying Coral Academy.

Mention {_LEARNER_PLACEHOLDER} enjoyed interactive classes.

Invite them to continue learning.

Encourage the parent to reply to this email if they have questions about enrolling.

Keep the email around 120 words.


Return ONLY the email body.

{_PARENT_PLACEHOLDER} and {_LEARNER_PLACEHOLDER} are literal placeholder
tokens — reproduce them EXACTLY as written, including the square brackets,
everywhere a name would go. Do not translate, rename, or remove them.

Do not include:
- Subject
- Markdown
- Bullet points
- Explanations
"""

    elif email_number == 2:

        subject = f"Continue {learner_name}'s learning journey"

        prompt = f"""
Write a follow-up email.

Parent name: {_PARENT_PLACEHOLDER}
learner name: {_LEARNER_PLACEHOLDER}
{redacted_class_line}

{_LEARNER_PLACEHOLDER} completed a free trial three days ago.

Encourage enrollment.

Mention benefits like:
- confidence
- creativity
- communication
- expert teachers
- live interactive classes

Keep it warm and professional.

Return ONLY the email body.

Invite the parent to explore membership options.

Write naturally as if written by a real member of the Coral Academy team.

Do not sound like AI.

{_PARENT_PLACEHOLDER} and {_LEARNER_PLACEHOLDER} are literal placeholder
tokens — reproduce them EXACTLY as written, including the square brackets,
everywhere a name would go. Do not translate, rename, or remove them.

Do not include:
- Subject
- Markdown
- Bullet points
- Explanations
"""

    elif email_number == 3:
        subject = f"Last reminder about {learner_name}'s free trial"

        prompt = f"""
Write the final reminder email.

Parent name: {_PARENT_PLACEHOLDER}
learner name: {_LEARNER_PLACEHOLDER}
{redacted_class_line}

{_LEARNER_PLACEHOLDER} completed a free trial seven days ago.

Be warm.

Do not sound pushy.

Invite the parent to reply with questions.

Let the parent know they are welcome to contact Coral Academy anytime if they decide to continue in the future.

Return ONLY the email body.

Write naturally as if written by a real member of the Coral Academy team.

Do not sound like AI.

{_PARENT_PLACEHOLDER} and {_LEARNER_PLACEHOLDER} are literal placeholder
tokens — reproduce them EXACTLY as written, including the square brackets,
everywhere a name would go. Do not translate, rename, or remove them.

Do not include:
- Subject
- Markdown
- Bullet points
- Explanations
"""

    try:

        response = client.chat.completions.create(
            model="gpt-5-nano",
            messages=[
                {
                    
                        "role": "system",
                        "content": """
                    You are Coral Academy's parent communication assistant.

                    Write warm, professional and trustworthy emails to parents.

                    Never exaggerate.

                    Never make promises you cannot verify.

                    Always end the email with:

                    Warm regards,

                    Coral Academy
                    """
                    
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        body = response.choices[0].message.content.strip()
        body = body.replace(_PARENT_PLACEHOLDER, parent_name).replace(_LEARNER_PLACEHOLDER, learner_name)

        return subject, body

    except Exception as e:

        print("AI Error:", e)

        return subject, f"""
Hi {parent_name},

We hope {learner_name} enjoyed the free trial at Coral Academy.

We'd love to have {learner_name} continue learning with us.

Please reply to this email if you have any questions.

Write naturally as if written by a real member of the Coral Academy team.

Do not sound like AI.

Warm regards,

Coral Academy
"""