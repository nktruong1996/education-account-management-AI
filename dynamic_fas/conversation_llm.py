import json

from config import CHAT_MODEL, client
from dynamic_fas.extraction import build_question_context
from dynamic_fas.models import DynamicAssistantState, DynamicQuestion


SYSTEM_PROMPT = """
You are a helpful assistant for Financial Assistance Scheme form completion.
"""


def get_fallback_reply(
    state: DynamicAssistantState,
    extracted_any: bool,
) -> str:
    if state.pending_question_id is not None:
        question = state.questions[str(state.pending_question_id)]
        prefix = "Thank you. " if extracted_any else "I could not identify a clear answer. "
        return f"{prefix}{question.question_text}"

    return (
        "I have enough information for the required questions. "
        "Review the suggestions and apply only the content that is accurate."
    )


def generate_assistant_reply(
    state: DynamicAssistantState,
    questions: list[DynamicQuestion],
    user_message: str,
    extracted_any: bool,
) -> str:
    prompt = f"""
You are helping a parent or guardian complete dynamic additional questions for a
Financial Assistance Scheme application.

Configured questions:
{build_question_context(questions)}

Current assistant state:
{json.dumps(state.model_dump(), indent=2)}

Latest user message:
{user_message}

Information was extracted from the latest message: {extracted_any}

Rules:
- Be concise and polite.
- Ask only the next missing required question identified by pending_question_id.
- Do not invent form values.
- If the latest message was unclear, say so briefly before asking the next question.
- If all required questions are answered, ask the user to review and apply suggestions.
- Do not submit anything or imply that suggestions were applied automatically.
- Do not mention JSON, backend, APIs, or internal state.
"""

    try:
        response = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_completion_tokens=250,
        )
        content = response.choices[0].message.content
        if content and content.strip():
            return content.strip()
    except Exception as exc:
        print(f"Dynamic conversation reply error: {exc!r}")

    return get_fallback_reply(state, extracted_any)
