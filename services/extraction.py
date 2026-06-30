import json
from typing import Optional
from pydantic import BaseModel
from llm import client, DEPLOYMENT_NAME
from services.prompts import EXTRACTION_SYSTEM_PROMPT, EXTRACTION_USER_PROMPT_2

class ExtractedInfo(BaseModel):
    employment_status: Optional[str] = None
    employer_name: Optional[str] = None
    application_reason: Optional[str] = None

def apply_deterministic_fallbacks(message: str, extracted: ExtractedInfo) -> ExtractedInfo:
    normalized = message.lower().strip()
    if "part-time" in normalized or "part time" in normalized:
        extracted.employment_status = "Part-time employed"
    elif "full-time" in normalized or "full time" in normalized:
        extracted.employment_status = "Full-time employed"
    elif "unemployed" in normalized or "lost my job" in normalized:
        extracted.employment_status = "Unemployed"
    elif "self-employed" in normalized or "self employed" in normalized:
        extracted.employment_status = "Self-employed"
    return extracted

def looks_like_correction(message: str) -> bool:
    normalized = message.lower().strip()
    correction_words = ["actually", "sorry", "i meant", "instead", "now", "correction"]
    employment_words = ["part-time", "full-time", "unemployed", "self-employed", "work", "job", "employed"]
    return any(w in normalized for w in correction_words) or any(w in normalized for w in employment_words)

def apply_pending_question_fallbacks(message: str, pending_question: Optional[str], extracted: ExtractedInfo) -> ExtractedInfo:
    if pending_question == "application_reason" and not extracted.application_reason and not extracted.employment_status and not looks_like_correction(message):
        extracted.application_reason = message.strip()
    if pending_question == "employer_name" and not extracted.employer_name and not extracted.employment_status and not looks_like_correction(message):
        extracted.employer_name = message.strip()
    return extracted

def extract_information(message: str, pending_question: Optional[str]) -> ExtractedInfo:
    prompt = EXTRACTION_USER_PROMPT_2.format(pending_question=pending_question, message=message)
    try:
        response = client.chat.completions.create(
            model=DEPLOYMENT_NAME,
            messages=[
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_completion_tokens=1000,
        )
        data = json.loads(response.choices[0].message.content)
        extracted = ExtractedInfo(**data)
    except Exception as e:
        extracted = ExtractedInfo()

    extracted = apply_deterministic_fallbacks(message, extracted)
    extracted = apply_pending_question_fallbacks(message, pending_question, extracted)
    return extracted

def is_positive_confirmation(message: str) -> bool:
    return message.lower().strip() in ["yes", "y", "yeah", "yep", "sure", "correct", "confirm", "ok", "okay"]

def is_negative_confirmation(message: str) -> bool:
    return message.lower().strip() in ["no", "n", "nope", "incorrect", "cancel", "do not", "don't"]
