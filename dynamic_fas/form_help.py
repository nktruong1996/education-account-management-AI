import json
import re

from config import CHAT_MODEL, client
from dynamic_fas.extraction import build_question_context
from dynamic_fas.message_router import is_general_help_message
from dynamic_fas.models import DynamicAssistantState, DynamicQuestion


SYSTEM_PROMPT = """
You help users understand how to complete a Financial Assistance Scheme form.
Keep answers short, practical, and focused on the supplied question metadata.
Do not answer eligibility, benefit, document, deadline, or policy questions.
"""


def normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def find_referenced_question(
    questions: list[DynamicQuestion],
    message: str,
) -> DynamicQuestion | None:
    normalized_message = f" {normalize_text(message)} "
    candidates: list[tuple[int, DynamicQuestion, str]] = []

    for question in questions:
        question_candidates = {
            normalize_text(str(question.question_id)),
            normalize_text(f"question {question.question_id}"),
            normalize_text(question.question_text),
        }
        for candidate in question_candidates:
            if candidate:
                candidates.append((len(candidate), question, candidate))

    for _, question, candidate in sorted(
        candidates,
        key=lambda item: item[0],
        reverse=True,
    ):
        if f" {candidate} " in normalized_message:
            return question
    return None


def build_metadata_help_reply(question: DynamicQuestion) -> str:
    description = question.description or (
        "Provide a clear answer based on the applicant's actual circumstances."
    )
    required_text = (
        "This question is required."
        if question.is_required
        else "This question is optional."
    )

    if question.type == "select":
        return (
            f"For “{question.question_text}”, choose the option that best matches "
            f"the applicant's situation. {description} {required_text} "
            f"Available options are: {', '.join(question.options)}."
        )

    return (
        f"For “{question.question_text}”, enter a clear, brief answer. "
        f"{description} {required_text}"
    )


def build_general_help_reply(state: DynamicAssistantState) -> str:
    if state.pending_question_id is not None:
        question = state.questions[str(state.pending_question_id)]
        return (
            "Yes. We can go through the questions one at a time. "
            f"Let's start with: {question.question_text}"
        )

    return (
        "Yes. I have enough information for the required questions. "
        "You can review the suggestions, apply the accurate ones, and edit them "
        "before submitting the form."
    )


def generate_form_help_reply(
    state: DynamicAssistantState,
    questions: list[DynamicQuestion],
    message: str,
) -> str:
    referenced_question = find_referenced_question(questions, message)
    if referenced_question is not None:
        return build_metadata_help_reply(referenced_question)

    if is_general_help_message(message):
        return build_general_help_reply(state)

    prompt = f"""
The user is asking for help with a dynamic FAS form.

Configured questions:
{build_question_context(questions)}

Current assistant state:
{json.dumps(state.model_dump(), indent=2)}

User question:
{message}

Rules:
- Explain only how to fill the configured questions.
- Use descriptions and select options when relevant.
- If asked what is still needed, mention missing required questions.
- Policy questions should be handled by the FAQ assistant.
- Do not mention APIs, JSON, backend, or internal state.
"""

    try:
        response = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_completion_tokens=400,
        )
        content = response.choices[0].message.content
        if content and content.strip():
            return content.strip()
    except Exception as exc:
        print(f"Dynamic form help error: {exc!r}")

    return (
        "I can explain what to enter for any question in this form. "
        "Which question would you like help with?"
    )
