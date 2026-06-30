from dynamic_fas.extraction import (
    extract_answers,
    is_negative_confirmation,
    is_positive_confirmation,
)
from dynamic_fas.message_router import route_message
from dynamic_fas.models import (
    DynamicAssistantState,
    DynamicChatRequest,
    DynamicChatResponse,
    DynamicQuestionState,
)
from dynamic_fas.session_store import (
    get_or_create_state,
    get_progress,
    get_suggested_fields,
    sessions,
    update_navigation,
)

def _build_response(
    request: DynamicChatRequest,
    state: DynamicAssistantState,
    reply: str,
) -> DynamicChatResponse:
    sessions[request.session_id] = state
    return DynamicChatResponse(
        reply=reply,
        assistant_state=state,
        suggested_fields=get_suggested_fields(state),
        progress=get_progress(state),
    )

def _pending_update_field(state: DynamicAssistantState) -> DynamicQuestionState | None:
    if state.pending_update_question_id is None:
        return None
    return state.questions.get(str(state.pending_update_question_id))

def _confirmation_reply(field: DynamicQuestionState) -> str:
    return (
        f"Question: “{field.question_text}”\n\n"
        f"Current answer: “{field.value}”\n\n"
        f"New answer: “{field.pending_value}”\n\n"
        "Would you like to use the new answer? Reply “Yes” or “No”."
    )

def _next_question_reply(state: DynamicAssistantState, extracted_any: bool = True) -> str:
    if state.pending_question_id is not None:
        field = state.questions[str(state.pending_question_id)]
        prefix = "Thank you. " if extracted_any else "I could not identify a clear answer. "
        return f"{prefix}{field.question_text}"

    return (
        "I have enough information for the required questions. "
        "Review the suggestions and apply only the content that is accurate."
    )

def _form_help_reply(state: DynamicAssistantState) -> str:
    if state.pending_question_id is not None:
        field = state.questions[str(state.pending_question_id)]
        return (
            f"For “{field.question_text}”, briefly describe your actual circumstances. "
            "I will not guess any missing information."
        )
    return (
        "Describe your actual circumstances in your own words. "
        "I only suggest answers for you to review before applying them to the form."
    )

def _apply_pending_update(field: DynamicQuestionState) -> None:
    field.value = field.pending_value
    field.pending_value = None
    field.status = "suggested"
    field.source = "confirmed_update"

def _reject_pending_update(field: DynamicQuestionState) -> None:
    field.pending_value = None
    field.status = "existing" if field.source == "current_form" else "suggested"

def _apply_extracted_answers(
    state: DynamicAssistantState,
    answers: dict[str, str],
) -> bool:
    applied_any = False
    for key in state.question_order:
        new_value = answers.get(key)
        if not new_value:
            continue

        field = state.questions[key]
        applied_any = True

        if not field.value:
            field.value = new_value
            field.pending_value = None
            field.status = "suggested"
            field.source = "user_message"
        elif field.value == new_value:
            continue
        else:
            field.pending_value = new_value
            field.status = "pending_update"

    update_navigation(state)
    return applied_any

def handle_chat(request: DynamicChatRequest) -> DynamicChatResponse:
    state = get_or_create_state(request)

    if not request.questions:
        return _build_response(request, state, "This FAS does not currently have any additional questions.")

    pending_field = _pending_update_field(state)

    # 1. Ưu tiên xử lý confirmation trước
    if pending_field is not None:
        if is_positive_confirmation(request.message):
            _apply_pending_update(pending_field)
            update_navigation(state)
        elif is_negative_confirmation(request.message):
            _reject_pending_update(pending_field)
            update_navigation(state)
        else:
            return _build_response(
                request, state, "Reply “Yes” to update the answer or “No” to keep the current answer."
            )

        next_pending = _pending_update_field(state)
        if next_pending is not None:
            return _build_response(request, state, _confirmation_reply(next_pending))

        return _build_response(request, state, _next_question_reply(state))

    # 2. Định tuyến tin nhắn
    route = route_message(request.message)

    if route.category == "FORM_HELP":
        return _build_response(request, state, _form_help_reply(state))

    if route.category != "FORM_FILLING":
        return _build_response(
            request, state, route.reply or "I can only help complete the questions in the FAS application."
        )

    # 3. Trích xuất và lưu câu trả lời
    answers = extract_answers(
        message=request.message,
        questions=request.questions,
        pending_question_id=state.pending_question_id,
    )
    extracted_any = _apply_extracted_answers(state, answers)
    pending_field = _pending_update_field(state)

    # 4. Trả về hỏi confirm hoặc câu hỏi tiếp theo
    if pending_field is not None:
        return _build_response(request, state, _confirmation_reply(pending_field))

    return _build_response(request, state, _next_question_reply(state, extracted_any=extracted_any))
