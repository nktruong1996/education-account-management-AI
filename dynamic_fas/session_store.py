import time

from dynamic_fas.models import (
    DynamicAssistantState,
    DynamicChatRequest,
    DynamicProgress,
    DynamicQuestion,
    DynamicQuestionState,
)

DEFAULT_SESSION_TTL_SECONDS = 30 * 60

sessions: dict[str, DynamicAssistantState] = {}
optional_prompt_shown_sessions: set[str] = set()
session_last_accessed: dict[str, float] = {}

def cleanup_expired_sessions(
    *,
    now: float | None = None,
    ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS,
) -> None:
    if ttl_seconds <= 0:
        return

    current_time = time.monotonic() if now is None else now
    expired_session_ids = [
        session_id
        for session_id, last_accessed in session_last_accessed.items()
        if current_time - last_accessed > ttl_seconds
    ]

    for session_id in expired_session_ids:
        sessions.pop(session_id, None)
        optional_prompt_shown_sessions.discard(session_id)
        session_last_accessed.pop(session_id, None)

def reset_session(session_id: str) -> None:
    sessions.pop(session_id, None)
    optional_prompt_shown_sessions.discard(session_id)
    session_last_accessed.pop(session_id, None)

def mark_session_active(session_id: str) -> None:
    session_last_accessed[session_id] = time.monotonic()

def _state_from_request(request: DynamicChatRequest) -> DynamicAssistantState:
    state = DynamicAssistantState(fas_scheme_id=request.fas_scheme_id)
    return reconcile_state(state, request)

def get_or_create_state(request: DynamicChatRequest) -> DynamicAssistantState:
    cleanup_expired_sessions()
    state = sessions.get(request.session_id)
    if state is None or state.fas_scheme_id != request.fas_scheme_id:
        state = _state_from_request(request)
    else:
        state = reconcile_state(state, request)
    sessions[request.session_id] = state
    mark_session_active(request.session_id)
    return state

def _state_from_question(question: DynamicQuestion) -> DynamicQuestionState:
    return DynamicQuestionState(
        question_id=question.question_id,
        question_text=question.question_text,
        is_required=question.is_required,
        description=question.description,
        type=question.type,
        options=question.options,
    )

def _definition_changed(
    previous: DynamicQuestionState,
    question: DynamicQuestion,
) -> bool:
    return (
        previous.question_text != question.question_text
        or previous.type != question.type
        or previous.options != question.options
    )

def _normalize_current_answer(question: DynamicQuestion, value: str) -> str:
    normalized = value.strip()
    if not normalized or question.type != "select":
        return normalized
    return next(
        (
            option
            for option in question.options
            if option.casefold() == normalized.casefold()
        ),
        "",
    )

def reconcile_state(state: DynamicAssistantState, request: DynamicChatRequest) -> DynamicAssistantState:
    reconciled: dict[str, DynamicQuestionState] = {}
    question_order: list[str] = []

    for question in request.questions:
        key = str(question.question_id)
        question_order.append(key)
        current_answer = _normalize_current_answer(
            question,
            request.current_answers.get(key, ""),
        )
        previous = state.questions.get(key)

        if previous is None or _definition_changed(previous, question):
            field = _state_from_question(question)
        else:
            field = previous.model_copy(deep=True)
            field.is_required = question.is_required
            field.description = question.description
            field.type = question.type
            field.options = list(question.options)

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

def get_blank_optional_fields(state: DynamicAssistantState) -> list[DynamicQuestionState]:
    return [
        state.questions[key]
        for key in state.question_order
        if not state.questions[key].is_required and not state.questions[key].value
    ]

def should_show_optional_prompt(session_id: str, state: DynamicAssistantState) -> bool:
    if session_id in optional_prompt_shown_sessions:
        return False
    if state.pending_question_id is not None or state.pending_update_question_id is not None:
        return False
    return bool(get_blank_optional_fields(state))

def mark_optional_prompt_shown(session_id: str) -> None:
    optional_prompt_shown_sessions.add(session_id)

def get_progress(state: DynamicAssistantState) -> DynamicProgress:
    required_fields = [state.questions[key] for key in state.question_order if state.questions[key].is_required]
    completed = sum(1 for field in required_fields if field.value)
    return DynamicProgress(completed=completed, total=len(required_fields), required_question_ids=[f.question_id for f in required_fields])
