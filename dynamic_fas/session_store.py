from dynamic_fas.models import DynamicAssistantState, DynamicChatRequest, DynamicProgress, DynamicQuestionState

sessions: dict[str, DynamicAssistantState] = {}

def reset_session(session_id: str) -> None:
    sessions.pop(session_id, None)

def _state_from_request(request: DynamicChatRequest) -> DynamicAssistantState:
    state = DynamicAssistantState(fas_scheme_id=request.fas_scheme_id)
    return reconcile_state(state, request)

def get_or_create_state(request: DynamicChatRequest) -> DynamicAssistantState:
    state = sessions.get(request.session_id)
    if state is None or state.fas_scheme_id != request.fas_scheme_id:
        state = _state_from_request(request)
    else:
        state = reconcile_state(state, request)
    sessions[request.session_id] = state
    return state

def reconcile_state(state: DynamicAssistantState, request: DynamicChatRequest) -> DynamicAssistantState:
    reconciled: dict[str, DynamicQuestionState] = {}
    question_order: list[str] = []

    for question in request.questions:
        key = str(question.question_id)
        question_order.append(key)
        current_answer = request.current_answers.get(key, "").strip()
        previous = state.questions.get(key)

        if previous is None or previous.question_text != question.question_text:
            field = DynamicQuestionState(question_id=question.question_id, question_text=question.question_text, is_required=question.is_required)
        else:
            field = previous.model_copy(deep=True)
            field.is_required = question.is_required

        if field.status == "pending_update":
            should_adopt_current_answer = (current_answer and current_answer == field.pending_value)
        else:
            should_adopt_current_answer = current_answer and (field.status in {"missing", "existing"} or current_answer == field.value)

        if should_adopt_current_answer:
            field.value = current_answer
            field.pending_value = None
            field.status = "existing"
            field.source = "current_form"
        reconciled[key] = field

    state.questions = reconciled
    state.question_order = question_order
    if str(state.pending_update_question_id) not in reconciled:
        state.pending_update_question_id = None
    update_navigation(state)
    return state

def update_navigation(state: DynamicAssistantState) -> None:
    pending_update = next((field.question_id for key in state.question_order if (field := state.questions[key]).status == "pending_update"), None)
    state.pending_update_question_id = pending_update
    if pending_update is not None:
        state.pending_question_id = None
        return

    state.pending_question_id = next((field.question_id for key in state.question_order if (field := state.questions[key]).is_required and not field.value), None)

def get_suggested_fields(state: DynamicAssistantState) -> dict[str, str]:
    return {key: field.value for key, field in state.questions.items() if field.status == "suggested" and field.value}

def get_progress(state: DynamicAssistantState) -> DynamicProgress:
    required_fields = [state.questions[key] for key in state.question_order if state.questions[key].is_required]
    completed = sum(1 for field in required_fields if field.value)
    return DynamicProgress(completed=completed, total=len(required_fields), required_question_ids=[f.question_id for f in required_fields])
