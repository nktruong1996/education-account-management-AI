import json
from dynamic_fas.models import DynamicQuestion
from dynamic_fas.prompts import EXTRACTION_SYSTEM_PROMPT, EXTRACTION_USER_PROMPT

def _parse_json(content: str) -> dict:
    normalized = content.strip()
    if normalized.startswith("```"):
        normalized = normalized.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(normalized)

def extract_answers(message: str, questions: list[DynamicQuestion], pending_question_id: int | None) -> dict[str, str]:
    question_payload = [{"question_id": q.question_id, "question_text": q.question_text, "is_required": q.is_required} for q in questions]
    prompt = EXTRACTION_USER_PROMPT.format(questions_json=json.dumps(question_payload, ensure_ascii=False), pending_question_id=pending_question_id, message=message)
    try:
        from llm import DEPLOYMENT_NAME, client
        response = client.chat.completions.create(
            model=DEPLOYMENT_NAME,
            messages=[{"role": "system", "content": EXTRACTION_SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
            max_completion_tokens=1200,
        )
        raw_answers = _parse_json(response.choices[0].message.content or "").get("answers", {})
    except Exception:
        return {}

    allowed_ids = {str(q.question_id) for q in questions}
    answers: dict[str, str] = {}
    if not isinstance(raw_answers, dict): return answers

    for question_id, value in raw_answers.items():
        key = str(question_id)
        if key in allowed_ids and isinstance(value, str) and value.strip():
            answers[key] = value.strip()[:4000]
    return answers

def is_positive_confirmation(message: str) -> bool:
    return message.lower().strip() in {"có", "đồng ý", "xác nhận", "yes", "y", "ok", "confirm"}

def is_negative_confirmation(message: str) -> bool:
    return message.lower().strip() in {"không", "từ chối", "no", "n", "cancel", "reject"}
