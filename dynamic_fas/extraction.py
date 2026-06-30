import json
from typing import Dict, Optional

from config import CHAT_MODEL, client
from dynamic_fas.models import DynamicQuestion
from dynamic_fas.prompts import EXTRACTION_SYSTEM_PROMPT, EXTRACTION_USER_PROMPT


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


def build_question_context(questions: list[DynamicQuestion]) -> str:
    blocks = []
    for question in questions:
        lines = [
            f"- question_id: {question.question_id}",
            f"  question_text: {question.question_text}",
            f"  description: {question.description or ''}",
            f"  type: {question.type}",
            f"  required: {question.is_required}",
        ]
        if question.type == "select":
            lines.append(f"  options: {', '.join(question.options)}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def build_empty_shape(questions: list[DynamicQuestion]) -> Dict[str, Optional[str]]:
    return {str(question.question_id): None for question in questions}


def extract_answers(
    message: str,
    questions: list[DynamicQuestion],
    pending_question_id: int | None,
) -> dict[str, str]:
    prompt = EXTRACTION_USER_PROMPT.format(
        questions_context=build_question_context(questions),
        pending_question_id=pending_question_id,
        message=message,
        empty_shape=json.dumps(build_empty_shape(questions), indent=2),
    )

    try:
        response = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_completion_tokens=1500,
        )
        data = _parse_json(response.choices[0].message.content or "")
        raw_answers = data.get("answers", data)
    except Exception as exc:
        print(f"Dynamic extraction error: {exc!r}")
        return {}

    if not isinstance(raw_answers, dict):
        return {}

    question_map = {str(question.question_id): question for question in questions}
    answers: dict[str, str] = {}

    for raw_question_id, raw_value in raw_answers.items():
        question_id = str(raw_question_id)
        question = question_map.get(question_id)
        if question is None or raw_value is None:
            continue

        value = str(raw_value).strip()
        if not value:
            continue

        if question.type == "select":
            matched_option = next(
                (
                    option
                    for option in question.options
                    if option.casefold() == value.casefold()
                ),
                None,
            )
            if matched_option is None:
                continue
            value = matched_option

        answers[question_id] = value[:4000]

    return answers


def is_positive_confirmation(message: str) -> bool:
    return message.casefold().strip() in {
        "có",
        "đồng ý",
        "xác nhận",
        "yes",
        "y",
        "yeah",
        "yep",
        "sure",
        "correct",
        "ok",
        "okay",
        "confirm",
        "please do",
        "update it",
    }


def is_negative_confirmation(message: str) -> bool:
    return message.casefold().strip() in {
        "không",
        "từ chối",
        "no",
        "n",
        "nope",
        "incorrect",
        "cancel",
        "do not",
        "don't",
        "keep the old value",
        "reject",
    }
