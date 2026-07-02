import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1"
)


def generate_reply(
    subject,
    body,
    category,
    priority,
    thread_history,
    similar_emails,
    knowledge=None
):
    """
    Generates a professional, friendly response to an incoming email
    by referencing conversation history and past approved email styles.
    """
    examples = ""

    # Safely build historical examples, supporting both dictionary and list/tuple candidates
    for i, email in enumerate(similar_emails, 1):
        if isinstance(email, dict):
            email_subject = email.get("subject", "N/A")
            email_body = (email.get("body") or "")[:1000]
        elif isinstance(email, (list, tuple)) and len(email) >= 4:
            # Fallback if similar_emails is passed as raw DB rows (e.g., [id, role, subject, body, ...])
            email_subject = email[2]
            email_body = (email[3] or "")[:1000]
        else:
            continue

        examples += f"""
Example {i}

Subject:
{email_subject}

Body:
{email_body}

----------------------------------------
"""

    knowledge_text = ""
    if knowledge:
        for i, item in enumerate(knowledge, 1):
            knowledge_text += f"""
Knowledge {i}

Title:
{item['title']}

Content:
{item['content']}

URL:
{item['url']}

----------------------------------------
"""

    prompt = f"""
You are replying on behalf of Coral Academy.
Your goal is to draft replies for parents, students, teachers, and prospective families.
Only draft replies when a human staff member would normally reply.

Do not reply to automated notifications, receipts, newsletters, invoices, monitoring alerts, deployment alerts, or marketing emails.
Your reply should sound as if it was written by a school staff member.
Write a professional, friendly, and concise reply.
Follow the school's previous writing style shown in the historical examples.
Do not invent facts. If information is missing, politely ask for clarification.
Return only the email reply.
Do not include explanations, notes, markdown, or quotation marks.

Incoming Email

Category:
{category}

Priority:
{priority}

Subject:
{subject}

Body:
{body[:5000]}

Conversation History:
{thread_history}

Relevant Historical Email Examples:
{examples if examples else "No historical examples found."}

Relevant Help Center Information:
{knowledge_text if knowledge_text else "No relevant Help Center information found."}




Instructions:
1. Write a professional, friendly, and concise reply.
2. Use the conversation history and historical examples only as guidance.
3. Always answer the current incoming email directly.
4. Do not invent school policies, dates, prices, or promises.
5. If vital information is missing, politely ask for clarification.
6. If the email requires human approval or additional internal lookup, state that politely.
7. Use the historical emails only as style/tone guides—do not copy their wording verbatim.
8. Do not assume context or facts from historical examples apply to this new email.
9. If the current email's details conflict with a historical example, always trust the current email.
10. Do not mention or refer to the historical examples in your reply.
11. Return only the body of the email.
12. Do not include a subject line, markdown, explanations, notes, or quotation marks.

## Help Center Instructions:

If the Help Center contains information that answers the user's question:

- Base your reply directly on that information.
- Do not invent policies or procedures.
- Include only the single most relevant Help Center URL.
- If multiple Help Center articles are relevant, use the most relevant one only.

Never promise to perform an action on behalf of Coral Academy unless the Help Center explicitly states that staff perform that action.

Do not say things like:
- "I can pause it for you."
- "I have updated your account."
- "We have processed your refund."

Instead, explain the process described in the Help Center and direct the user to the appropriate steps.

If no Help Center information is relevant, ignore the Help Center information completely and answer using:
- the current incoming email,
- the conversation history, and
- the historical email examples (for writing style only).

If the Help Center fully answers the user's question, prefer the Help Center information over historical email examples.

Use historical email examples only to match Coral Academy's writing style and tone.

If you include a Help Center URL, end the email with exactly this format:

For more information:
<Help Center URL>

Do not include a Help Center URL unless you used Help Center information in your reply.

Do not invent menu names, navigation paths, button names, or website steps.
Only mention navigation or instructions that appear in the Help Center information provided.

Priority of information:

1. Current incoming email
2. Help Center information (facts and policies)
3. Conversation history
4. Historical email examples (style and tone only)

If these sources conflict, always follow the higher-priority source.
"""


    try:
        response = client.chat.completions.create(
            model="gpt-5-nano",
            temperature=0.3,
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )
        reply = response.choices[0].message.content.strip()
        if reply == "NO_REPLY":
            return ""

        return reply

    except Exception as e:
        print("Reply Generator Error:", e)
        return ""