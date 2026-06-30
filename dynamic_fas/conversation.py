from dynamic_fas.answer_revision import revise_extracted_answers
from dynamic_fas.change_detector import detect_changes
from dynamic_fas.conversation_llm import generate_assistant_reply
from dynamic_fas.extraction import (
    extract_answers,
    is_negative_confirmation,
    is_positive_confirmation,
)
from dynamic_fas.form_help import generate_example_request_reply, generate_form_help_reply
from dynamic_fas.message_router import route_message, strip_leading_greeting
from dynamic_fas.models import (
    DynamicAssistantState,
    DynamicChatRequest,
    DynamicChatResponse,
    DynamicQuestionState,
)
from dynamic_fas.session_store import (
    get_or_create_state,
    get_blank_optional_fields,
    get_progress,
    get_suggested_fields,
    mark_optional_prompt_shown,
    sessions,
    should_show_optional_prompt,
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
    changes = detect_changes(state, answers)
    for change in changes:
        field = state.questions[change.question_id]
        if change.change_type == "new":
            field.value = change.new_value
            field.pending_value = None
            field.status = "suggested"
            field.source = "user_message"
        elif change.change_type == "same":
            continue
        elif change.change_type == "update":
            field.pending_value = change.new_value
            field.status = "pending_update"

    update_navigation(state)
    return bool(changes)

def _optional_completion_reply(
    request: DynamicChatRequest,
    state: DynamicAssistantState,
) -> str | None:
    if not should_show_optional_prompt(request.session_id, state):
        return None

    optional_fields = get_blank_optional_fields(state)
    mark_optional_prompt_shown(request.session_id)
    optional_list = "\n".join(
        f"- {field.question_text}" for field in optional_fields[:5]
    )
    more_text = (
        "\n- ..." if len(optional_fields) > 5 else ""
    )
    return (
        "Required questions are complete. Optional questions still blank:\n"
        f"{optional_list}{more_text}\n\n"
        "You can answer any of them, or review and apply the current suggestions."
    )

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

        reply = generate_assistant_reply(
            state=state,
            questions=request.questions,
            user_message=request.message,
            extracted_any=True,
        )
        return _build_response(request, state, reply)

    # 2. Định tuyến tin nhắn
    route = route_message(request.message)
    routed_message = strip_leading_greeting(request.message)

    if route.category == "FORM_HELP":
        reply = generate_form_help_reply(
            state=state,
            questions=request.questions,
            message=routed_message,
        )
        return _build_response(request, state, reply)

    if route.category == "EXAMPLE_REQUEST":
        reply = generate_example_request_reply(
            state=state,
            questions=request.questions,
            message=routed_message,
        )
        return _build_response(request, state, reply)

    if route.category != "FORM_FILLING":
        return _build_response(
            request, state, route.reply or "I can only help complete the questions in the FAS application."
        )

    # 3. Trích xuất và lưu câu trả lời
    answers = extract_answers(
        message=routed_message,
        questions=request.questions,
        pending_question_id=state.pending_question_id,
    )
    answers = revise_extracted_answers(
        state=state,
        questions=request.questions,
        answers=answers,
        user_message=routed_message,
    )
    extracted_any = _apply_extracted_answers(state, answers)
    pending_field = _pending_update_field(state)

    # 4. Trả về hỏi confirm hoặc câu hỏi tiếp theo
    if pending_field is not None:
        return _build_response(request, state, _confirmation_reply(pending_field))

    optional_reply = _optional_completion_reply(request, state)
    if optional_reply is not None:
        return _build_response(request, state, optional_reply)

    reply = generate_assistant_reply(
        state=state,
        questions=request.questions,
        user_message=request.message,
        extracted_any=extracted_any,
    )
    return _build_response(request, state, reply)
