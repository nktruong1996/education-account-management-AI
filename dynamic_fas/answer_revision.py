import json
import re
from typing import Literal

from config import CHAT_MODEL, client
from dynamic_fas.models import DynamicAssistantState, DynamicQuestion
from dynamic_fas.prompts import (
    ANSWER_REVISION_SYSTEM_PROMPT,
    ANSWER_REVISION_USER_PROMPT,
)


LONG_ANSWER_THRESHOLD = 600
EXPLICIT_REPLACEMENT_PATTERN = re.compile(
    r"\b(?:actually\s+)?(?:change|update|replace|set)\b.+\b(?:to|with|as)\b",
    re.IGNORECASE,
)
RevisionReason = Literal[
    "compressed_long_answer",
    "added_new_fact",
    "deduplicated",
    "unchanged",
]


def _parse_json(content: str) -> dict:
    normalized = content.strip()
    if normalized.startswith("```"):
        normalized = (
            normalized.removeprefix("```json")
            .removeprefix("```JSON")
            .removeprefix("```")
            .removesuffix("```")
            .strip()
        )
    return json.loads(normalized)


def should_revise_answer(
    *,
    question: DynamicQuestion,
    existing_answer: str | None,
    extracted_answer: str,
    user_message: str = "",
) -> bool:
    if question.type != "textarea":
        return False
    if existing_answer and EXPLICIT_REPLACEMENT_PATTERN.search(user_message):
        return False
    if existing_answer and existing_answer.strip():
        return True
    return len(extracted_answer.strip()) > LONG_ANSWER_THRESHOLD


def revise_answer(
    *,
    question: DynamicQuestion,
    existing_answer: str | None,
    extracted_answer: str,
    user_message: str,
) -> str:
    prompt = ANSWER_REVISION_USER_PROMPT.format(
        question_text=question.question_text,
        existing_answer=existing_answer or "(empty)",
        extracted_answer=extracted_answer,
        user_message=user_message,
    )

    try:
        response = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": ANSWER_REVISION_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_completion_tokens=800,
        )
        data = _parse_json(response.choices[0].message.content or "")
        answer = str(data.get("answer") or "").strip()
    except Exception as exc:
        print(f"Dynamic answer revision error: {exc!r}")
        return extracted_answer

    return answer[:4000] if answer else extracted_answer


def revise_extracted_answers(
    *,
    state: DynamicAssistantState,
    questions: list[DynamicQuestion],
    answers: dict[str, str],
    user_message: str,
) -> dict[str, str]:
    question_map = {str(question.question_id): question for question in questions}
    revised: dict[str, str] = {}

    for question_id, extracted_answer in answers.items():
        question = question_map.get(str(question_id))
        field = state.questions.get(str(question_id))
        if question is None or field is None:
            revised[question_id] = extracted_answer
            continue

        existing_answer = field.value
        if should_revise_answer(
            question=question,
            existing_answer=existing_answer,
            extracted_answer=extracted_answer,
            user_message=user_message,
        ):
            revised[question_id] = revise_answer(
                question=question,
                existing_answer=existing_answer,
                extracted_answer=extracted_answer,
                user_message=user_message,
            )
        else:
            revised[question_id] = extracted_answer

    return revised
