import json
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1"
)


def rerank_knowledge(subject, body, candidates):

    article_list = ""

    for i, article in enumerate(candidates):
        article_list += f"""
Index: {i}

Similarity Score: {article["similarity"]:.2%}

Title:
{article["title"]}{" — " + article["section"] if article["section"] else ""}

Content:
{article["content"][:1200]}

--------------------------------------------------
"""

    prompt = f"""
You are selecting Knowledge Base articles for Coral Academy's AI Email Assistant.

Your job is NOT to write a reply.

Your job is to choose the Knowledge Base chunks that actually answer the customer's question — not ones that are merely topically or semantically similar.

Unlike historical emails, these chunks are used as a FACTUAL source — an incorrect or irrelevant chunk here can cause the AI to state something wrong as if it were verified fact.

--------------------------------------------------
Candidate Knowledge Base Chunks
--------------------------------------------------

The following chunks were retrieved using semantic search.

They are only candidates.

Many are intentionally imperfect — vector similarity often returns chunks that are topically close but do not actually answer the question.

Similarity scores are provided only as guidance.

--------------------------------------------------
Selection Rules
--------------------------------------------------

1. Only choose a chunk if it actually contains the specific fact, policy, or process needed to answer the customer's question.

2. Do not choose a chunk just because it shares keywords or general topic with the question.

3. Do not choose a chunk written for teachers/instructors/internal staff when the customer is a parent — see the "written for staff, not parents" red flags (phrases like "as an instructor," "email teachers@coralacademy.com," "post an announcement to enrolled parents").

4. Prefer fewer, precisely relevant chunks over many loosely related ones.

5. If none of the candidates genuinely answer the question, return an empty selection — do not force a match.

6. Ignore duplicate or near-duplicate chunks; keep the clearer one.

7. Keep each reason under 15 words.

8. Use simple English.

--------------------------------------------------
Do NOT choose chunks that
--------------------------------------------------

• only match on keywords or general topic
• describe a process for staff/teachers rather than the customer
• contain outdated information contradicted by a more specific candidate
• require guessing or inference beyond what the chunk actually states

--------------------------------------------------
Incoming Email
--------------------------------------------------

Subject:
{subject}

Body:
{body}

--------------------------------------------------
Candidate Knowledge Base Chunks
--------------------------------------------------

{article_list}

--------------------------------------------------
Output
--------------------------------------------------

Return ONLY valid JSON.

Do not include markdown.

Do not include explanations.

Do not include additional text.

Confidence should be an integer between 0 and 100 indicating how directly the chunk answers the customer's question.

Example:

{{
    "selected": [
        {{
            "index": 2,
            "reason": "States the exact refund window policy asked about.",
            "confidence": 96
        }}
    ]
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
You are Coral Academy's Knowledge Base reranking assistant.

Return only valid JSON.
"""
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            response_format={"type": "json_object"}
        )

        result = json.loads(response.choices[0].message.content)

        if "selected" not in result:
            raise ValueError("Missing 'selected' field.")

        for item in result["selected"]:

            if "index" not in item:
                raise ValueError("Missing index.")

            if "reason" not in item:
                raise ValueError("Missing reason.")

            if "confidence" not in item:
                item["confidence"] = 100

        return result

    except Exception as e:

        print("Knowledge Reranker Error:", e)

        return {
            "selected": []
        }


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
You are selecting historical email examples for Coral Academy's AI Email Assistant.

Your job is NOT to write a reply.

Your job is to choose the historical emails that would be the MOST useful references for writing an accurate reply to the current email.

The historical emails are used ONLY to teach Coral Academy's writing style and response structure.

They are NOT factual references.

Do NOT choose emails because they contain similar names, dates, or facts.

Choose them because they demonstrate how Coral Academy would naturally respond to a similar customer situation.

--------------------------------------------------
Candidate Historical Emails
--------------------------------------------------

The following emails were retrieved using semantic search.

They are only candidates.

Many are intentionally imperfect.

Similarity scores are provided only as guidance.

Choose the emails that would produce the best reply, even if they have lower similarity scores.

--------------------------------------------------
Selection Rules
--------------------------------------------------

1. Match the customer's underlying intent.

Examples:

• asking a question
• reporting absence
• requesting cancellation
• requesting enrollment
• requesting information
• requesting refund
• making a complaint

2. Match the requested action.

Examples:

• explain
• approve
• inform
• confirm
• schedule
• cancel
• enroll

3. Match the actual situation.

Examples:

• sick child
• holiday
• missed lesson
• billing issue
• class enquiry
• technical problem

4. Prefer examples that would naturally help write today's reply.

5. Ignore emails that only share keywords.

6. Ignore duplicate examples.

7. Prefer examples that demonstrate Coral Academy's current writing style.

8. Never choose examples because of names, dates or specific facts.

9. Keep each reason under 15 words.

10. Use simple English.

11. If two examples are equally useful, prefer the shorter and clearer example.

12. If none of the candidate emails are genuinely useful, return fewer than three examples.

13. Do not select poor examples simply to reach three.

14. Do NOT choose all examples from the same conversation if other candidates provide broader guidance.

15. Prefer diversity when multiple examples are equally useful.

--------------------------------------------------
Do NOT choose examples that
--------------------------------------------------

• discuss a different customer problem
• only match on names or keywords
• require different business decisions
• contain outdated information

--------------------------------------------------
Incoming Email
--------------------------------------------------

Subject:
{subject}

Body:
{body}

--------------------------------------------------
Candidate Historical Emails
--------------------------------------------------

{email_list}

--------------------------------------------------
Output
--------------------------------------------------

Return ONLY valid JSON.

Do not include markdown.

Do not include explanations.

Do not include additional text.

Confidence should be an integer between 0 and 100 indicating how useful the historical email would be for writing the reply.

Example:

{{
    "selected": [
        {{
            "id": 23,
            "reason": "Similar child absence notification.",
            "confidence": 97
        }},
        {{
            "id": 57,
            "reason": "Similar enrollment enquiry.",
            "confidence": 91
        }}
    ]
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
You are Coral Academy's historical email reranking assistant.

Return only valid JSON.
"""
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            response_format={"type": "json_object"}
        )

        result = json.loads(response.choices[0].message.content)

        if "selected" not in result:
            raise ValueError("Missing 'selected' field.")

        for item in result["selected"]:

            if "id" not in item:
                raise ValueError("Missing id.")

            if "reason" not in item:
                raise ValueError("Missing reason.")

            if "confidence" not in item:
                item["confidence"] = 100

        return result

    except Exception as e:

        print("Reranker Error:", e)

        return {
            "selected": []
        }