from models import AssistantState, FieldState

def create_initial_state() -> AssistantState:
    return AssistantState(
        fields={
            "employment_status": FieldState(),
            "employer_name": FieldState(),
            "application_reason": FieldState(),
        },
        notes=[],
        pending_question="employment_status",
    )

def get_suggested_fields(state: AssistantState) -> dict:
    return {
        key: field.value
        for key, field in state.fields.items()
        if field.status in ["suggested", "confirmed"] and field.value is not None
    }

def get_required_fields(state: AssistantState) -> list[str]:
    employment_status = state.fields["employment_status"].value

    if employment_status == "Unemployed":
        return [
            "employment_status",
            "application_reason",
        ]

    return [
        "employment_status",
        "employer_name",
        "application_reason",
    ]

def get_progress(state: AssistantState) -> dict:
    required_fields = get_required_fields(state)

    completed = sum(
        1
        for field_name in required_fields
        if state.fields[field_name].status in ["suggested", "confirmed"]
    )

    return {
        "completed": completed,
        "total": len(required_fields),
        "required_fields": required_fields,
    }
