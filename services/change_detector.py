from typing import List
from pydantic import BaseModel
from models import AssistantState
from services.extraction import ExtractedInfo

class FieldChange(BaseModel):
    field_name: str
    old_value: str | None = None
    new_value: str
    change_type: str  # "new", "same", "update"

def detect_changes(state: AssistantState, extracted: ExtractedInfo) -> List[FieldChange]:
    changes: List[FieldChange] = []
    extracted_dict = extracted.model_dump()

    for field_name, new_value in extracted_dict.items():
        if not new_value:
            continue
        current_field = state.fields[field_name]
        old_value = current_field.value

        if not old_value:
            changes.append(FieldChange(field_name=field_name, old_value=None, new_value=new_value, change_type="new"))
        elif old_value == new_value:
            changes.append(FieldChange(field_name=field_name, old_value=old_value, new_value=new_value, change_type="same"))
        else:
            changes.append(FieldChange(field_name=field_name, old_value=old_value, new_value=new_value, change_type="update"))
    return changes
