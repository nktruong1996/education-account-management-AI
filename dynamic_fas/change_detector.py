from typing import Dict, List, Literal, Optional

from pydantic import BaseModel

from dynamic_fas.models import DynamicAssistantState


ChangeType = Literal["new", "same", "update"]


class DynamicQuestionChange(BaseModel):
    question_id: str
    old_value: Optional[str] = None
    new_value: str
    change_type: ChangeType


def normalize_value(value: str) -> str:
    return " ".join(value.strip().split())


def detect_changes(
    state: DynamicAssistantState,
    extracted: Dict[str, str],
) -> List[DynamicQuestionChange]:
    changes: List[DynamicQuestionChange] = []

    for question_id, raw_value in extracted.items():
        if question_id not in state.questions or raw_value is None:
            continue

        new_value = normalize_value(str(raw_value))
        if not new_value:
            continue

        old_value = state.questions[question_id].value
        if not old_value:
            change_type: ChangeType = "new"
        elif normalize_value(old_value).casefold() == new_value.casefold():
            change_type = "same"
        else:
            change_type = "update"

        changes.append(
            DynamicQuestionChange(
                question_id=question_id,
                old_value=old_value,
                new_value=new_value,
                change_type=change_type,
            )
        )

    return changes
