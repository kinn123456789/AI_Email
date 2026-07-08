from openai import OpenAI
from dotenv import load_dotenv
import os

load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1"
)


def generate_followup_email(candidate, parent_name, email_number):

    learner_name = candidate.get("learner_name", "your child")

    if email_number == 1:

        subject = f"We hope {learner_name} enjoyed the free trial!"

        prompt = f"""
Write a warm, friendly follow-up email.

Parent name: {parent_name}
learner name: {learner_name}

{learner_name} completed a free trial yesterday.

Thank the parent for trying Coral Academy.

Mention {learner_name} enjoyed interactive classes.

Invite them to continue learning.

Encourage the parent to reply to this email if they have questions about enrolling.

Keep the email around 120 words.


Return ONLY the email body.

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

Parent name: {parent_name}
learner name: {learner_name}

{learner_name} completed a free trial three days ago.

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

Parent name: {parent_name}
learner name: {learner_name}

{learner_name} completed a free trial seven days ago.

Be warm.

Do not sound pushy.

Invite the parent to reply with questions.

Let the parent know they are welcome to contact Coral Academy anytime if they decide to continue in the future.

Return ONLY the email body.

Write naturally as if written by a real member of the Coral Academy team.

Do not sound like AI.

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