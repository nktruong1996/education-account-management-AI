import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List

import streamlit as st

from dynamic_fas.ui_client import (
    DynamicFasApiError,
    chat_with_dynamic_fas,
    reset_dynamic_fas_session,
)


DEFAULT_QUESTIONS = [
    {
        "question_id": 101,
        "question_text": "Please describe your family's current financial situation.",
        "is_required": True,
        "description": "Summarise the household's present financial circumstances.",
        "type": "textarea",
        "options": "",
    },
    {
        "question_id": 102,
        "question_text": "How has your family's income changed over the past six months?",
        "is_required": True,
        "description": "Mention material increases, reductions, or loss of income.",
        "type": "textarea",
        "options": "",
    },
    {
        "question_id": 103,
        "question_text": "Is there any additional information you would like to provide?",
        "is_required": False,
        "description": "Include other relevant circumstances not covered above.",
        "type": "textarea",
        "options": "",
    },
]

GREETING = (
    "Hello! Describe your circumstances in your own words. "
    "I will suggest answers for you to review before applying them."
)


def _answer_key(question_id: str) -> str:
    return f"dfas_answer_{question_id}"


def _new_session_id(scheme_id: int) -> str:
    return f"fas-{scheme_id}-{uuid.uuid4()}"


def _initialize_state() -> None:
    defaults = {
        "dfas_api_base": os.getenv(
            "DYNAMIC_FAS_API_BASE",
            "http://127.0.0.1:8001",
        ),
        "dfas_scheme_id": 10,
        "dfas_session_id": _new_session_id(10),
        "dfas_question_rows": DEFAULT_QUESTIONS,
        "dfas_messages": [{"role": "assistant", "content": GREETING}],
        "dfas_suggestions": {},
        "dfas_assistant_state": None,
        "dfas_confirmation": None,
        "dfas_status": "",
        "dfas_error": "",
        "dfas_last_payload": None,
        "dfas_last_response": None,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def _change_scheme() -> None:
    scheme_id = int(st.session_state["dfas_scheme_id"])
    st.session_state["dfas_session_id"] = _new_session_id(scheme_id)
    st.session_state["dfas_messages"] = [
        {"role": "assistant", "content": GREETING}
    ]
    st.session_state["dfas_suggestions"] = {}
    st.session_state["dfas_assistant_state"] = None
    st.session_state["dfas_confirmation"] = None
    st.session_state["dfas_status"] = "Started a new session for the selected FAS."
    st.session_state["dfas_error"] = ""


def _rows_from_editor(value: Any) -> List[Dict[str, Any]]:
    if hasattr(value, "to_dict"):
        return value.to_dict("records")
    return list(value)


def _normalize_questions(value: Any) -> List[Dict[str, Any]]:
    questions: List[Dict[str, Any]] = []
    seen_ids = set()

    for row in _rows_from_editor(value):
        raw_id = row.get("question_id")
        text = str(row.get("question_text") or "").strip()
        if raw_id is None and not text:
            continue
        try:
            question_id = int(raw_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("Every question must have a numeric ID.") from exc
        if question_id <= 0:
            raise ValueError("Question IDs must be greater than zero.")
        if question_id in seen_ids:
            raise ValueError(f"Question ID {question_id} is duplicated.")
        if not text:
            raise ValueError(f"Question {question_id} must have text.")

        description = str(row.get("description") or "").strip() or None
        question_type = str(row.get("type") or "textarea").strip().lower()
        if question_type not in {"text", "textarea", "select"}:
            raise ValueError(f"Question {question_id} has an unsupported type.")

        raw_options = row.get("options") or []
        if isinstance(raw_options, str):
            option_values = raw_options.split(",")
        else:
            option_values = list(raw_options)
        options = []
        seen_options = set()
        for raw_option in option_values:
            option = str(raw_option).strip()
            option_key = option.casefold()
            if option and option_key not in seen_options:
                options.append(option)
                seen_options.add(option_key)
        if question_type == "select" and not options:
            raise ValueError(
                f"Select question {question_id} must define comma-separated options."
            )
        if question_type != "select":
            options = []

        seen_ids.add(question_id)
        questions.append(
            {
                "question_id": question_id,
                "question_text": text,
                "is_required": bool(row.get("is_required", False)),
                "description": description,
                "type": question_type,
                "options": options,
            }
        )

    if not questions:
        raise ValueError("Add at least one question before chatting with AI.")
    return questions


def _current_answers(questions: List[Dict[str, Any]]) -> Dict[str, str]:
    return {
        str(question["question_id"]): str(
            st.session_state.get(_answer_key(str(question["question_id"])), "")
        )
        for question in questions
    }


def _question_was_confirmed_by_chat(question_id: str) -> bool:
    state = st.session_state.get("dfas_assistant_state") or {}
    question_state = (state.get("questions") or {}).get(question_id) or {}
    return question_state.get("source") == "confirmed_update"


def _commit_suggestion(question_id: str, value: str) -> None:
    st.session_state[_answer_key(question_id)] = value
    suggestions = dict(st.session_state.get("dfas_suggestions") or {})
    suggestions.pop(question_id, None)
    st.session_state["dfas_suggestions"] = suggestions


def _apply_suggestion(question_id: str, value: str) -> None:
    current_value = str(st.session_state.get(_answer_key(question_id), "")).strip()
    if (
        current_value
        and current_value != value
        and not _question_was_confirmed_by_chat(question_id)
    ):
        st.session_state["dfas_confirmation"] = {
            "question_id": question_id,
            "current_value": current_value,
            "new_value": value,
        }
        return

    _commit_suggestion(question_id, value)
    st.session_state["dfas_status"] = (
        "Applied the suggestion to the form. The data has not been submitted."
    )


def _apply_all_suggestions() -> None:
    conflicts = []
    applied = 0
    suggestions = list((st.session_state.get("dfas_suggestions") or {}).items())

    for question_id, value in suggestions:
        current_value = str(
            st.session_state.get(_answer_key(question_id), "")
        ).strip()
        if (
            current_value
            and current_value != value
            and not _question_was_confirmed_by_chat(question_id)
        ):
            conflicts.append(
                {
                    "question_id": question_id,
                    "current_value": current_value,
                    "new_value": value,
                }
            )
            continue
        _commit_suggestion(question_id, value)
        applied += 1

    if conflicts:
        st.session_state["dfas_confirmation"] = conflicts[0]
        st.session_state["dfas_status"] = (
            f"Applied {applied} suggestions. {len(conflicts)} changes still require "
            "individual confirmation."
        )
    else:
        st.session_state["dfas_status"] = f"Applied {applied} suggestions."


def _dismiss_suggestion(question_id: str) -> None:
    suggestions = dict(st.session_state.get("dfas_suggestions") or {})
    suggestions.pop(question_id, None)
    st.session_state["dfas_suggestions"] = suggestions
    st.session_state["dfas_status"] = (
        "Dismissed the suggestion. The form answer was not changed."
    )


def _confirm_update() -> None:
    confirmation = st.session_state.get("dfas_confirmation")
    if not confirmation:
        return
    _commit_suggestion(
        confirmation["question_id"],
        confirmation["new_value"],
    )
    st.session_state["dfas_confirmation"] = None
    st.session_state["dfas_status"] = (
        "Applied the confirmed update. The data has not been submitted."
    )


def _cancel_update() -> None:
    st.session_state["dfas_confirmation"] = None
    st.session_state["dfas_status"] = "Kept the current form answer."


def _send_message(message: str, questions: List[Dict[str, Any]]) -> None:
    message = message.strip()
    if not message:
        return

    payload = {
        "session_id": st.session_state["dfas_session_id"].strip(),
        "fas_scheme_id": int(st.session_state["dfas_scheme_id"]),
        "message": message,
        "questions": questions,
        "current_answers": _current_answers(questions),
    }
    st.session_state["dfas_last_payload"] = payload
    st.session_state["dfas_messages"].append(
        {"role": "user", "content": message}
    )
    st.session_state["dfas_error"] = ""
    st.session_state["dfas_status"] = ""

    try:
        with st.spinner("AI is processing..."):
            data = chat_with_dynamic_fas(
                st.session_state["dfas_api_base"],
                payload,
            )
    except DynamicFasApiError as exc:
        st.session_state["dfas_error"] = str(exc)
        return

    st.session_state["dfas_last_response"] = data
    st.session_state["dfas_messages"].append(
        {"role": "assistant", "content": data.get("reply", "")}
    )
    st.session_state["dfas_suggestions"] = data.get("suggested_fields") or {}
    st.session_state["dfas_assistant_state"] = data.get("assistant_state")


def _reset_session() -> None:
    st.session_state["dfas_error"] = ""
    try:
        with st.spinner("Resetting assistant session..."):
            data = reset_dynamic_fas_session(
                st.session_state["dfas_api_base"],
                st.session_state["dfas_session_id"].strip(),
            )
    except DynamicFasApiError as exc:
        st.session_state["dfas_error"] = str(exc)
        return

    st.session_state["dfas_last_response"] = data
    st.session_state["dfas_suggestions"] = {}
    st.session_state["dfas_assistant_state"] = None
    st.session_state["dfas_confirmation"] = None
    st.session_state["dfas_messages"] = [
        {
            "role": "assistant",
            "content": (
                "The assistant session has been reset. "
                "Your existing form answers have been preserved."
            ),
        }
    ]
    st.session_state["dfas_status"] = (
        "Reset the conversation without changing the form data."
    )


def _load_styles() -> None:
    shared_css = Path(__file__).resolve().parents[1] / "style.css"
    if shared_css.exists():
        st.markdown(
            f"<style>{shared_css.read_text(encoding='utf-8')}</style>",
            unsafe_allow_html=True,
        )
    st.markdown(
        """
        <style>
        [data-testid="stAppViewContainer"], [data-testid="stHeader"] {
            background: #f8fafc !important;
        }
        .stApp, .stApp h1, .stApp h2, .stApp h3, .stApp h4,
        .stApp p, .stApp label, .stApp [data-testid="stMarkdownContainer"] {
            color: #111827 !important;
        }
        .stApp [data-testid="stCaptionContainer"] p {
            color: #6b7280 !important;
        }
        .stApp textarea, .stApp input {
            background: #ffffff !important;
            color: #111827 !important;
            -webkit-text-fill-color: #111827 !important;
        }
        .stApp textarea::placeholder, .stApp input::placeholder {
            color: #9ca3af !important;
            -webkit-text-fill-color: #9ca3af !important;
        }
        .stApp .stButton > button,
        .stApp .stFormSubmitButton > button {
            background: #ffffff !important;
            border-color: #d1d5db !important;
            color: #111827 !important;
        }
        .stApp [data-testid="stAlertContainer"] {
            color: #111827 !important;
        }
        .dfas-eyebrow { color: #2563eb; font-size: .78rem; font-weight: 700;
            letter-spacing: .08em; text-transform: uppercase; }
        .dfas-card { background: #fff; border: 1px solid #e5e7eb;
            border-radius: 16px; padding: 1rem 1.1rem; margin-bottom: .8rem; }
        .dfas-card h4 { margin: 0 0 .35rem; }
        .dfas-meta { color: #6b7280; font-size: .78rem; }
        .dfas-suggestion { border-left: 4px solid #2563eb; }
        </style>
        """,
        unsafe_allow_html=True,
    )


st.set_page_config(
    page_title="Dynamic FAS Test UI",
    page_icon="✨",
    layout="wide",
)
_initialize_state()
_load_styles()

st.markdown('<div class="dfas-eyebrow">Student application</div>', unsafe_allow_html=True)
st.title("AI Autofill for Additional Questions")
st.caption(
    "Test the Dynamic FAS chat and reset APIs. AI suggestions are never written "
    "to the form until you apply them."
)

with st.expander("Test configuration", expanded=False):
    config_left, config_right = st.columns(2)
    with config_left:
        st.text_input("API base URL", key="dfas_api_base")
        st.number_input(
            "FAS scheme ID",
            min_value=1,
            step=1,
            key="dfas_scheme_id",
            on_change=_change_scheme,
        )
    with config_right:
        st.text_input("Session ID", key="dfas_session_id")
        if st.button("Generate new session ID", use_container_width=True):
            st.session_state["dfas_session_id"] = _new_session_id(
                int(st.session_state["dfas_scheme_id"])
            )
            st.session_state["dfas_status"] = "Generated a new local session ID."
            st.rerun()

    edited_rows = st.data_editor(
        st.session_state["dfas_question_rows"],
        key="dfas_question_editor",
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "question_id": st.column_config.NumberColumn(
                "Question ID",
                min_value=1,
                step=1,
                required=True,
            ),
            "question_text": st.column_config.TextColumn(
                "Question text",
                required=True,
                width="large",
            ),
            "description": st.column_config.TextColumn(
                "Description",
                width="medium",
            ),
            "type": st.column_config.SelectboxColumn(
                "Type",
                options=["text", "textarea", "select"],
                required=True,
            ),
            "options": st.column_config.TextColumn(
                "Select options (comma-separated)",
                width="medium",
            ),
            "is_required": st.column_config.CheckboxColumn("Required"),
        },
    )

try:
    questions = _normalize_questions(edited_rows)
except ValueError as exc:
    questions = []
    st.error(str(exc))

valid_question_ids = {str(question["question_id"]) for question in questions}
suggestions = {
    str(question_id): str(value)
    for question_id, value in (st.session_state.get("dfas_suggestions") or {}).items()
    if str(question_id) in valid_question_ids
}
st.session_state["dfas_suggestions"] = suggestions

for question in questions:
    st.session_state.setdefault(_answer_key(str(question["question_id"])), "")

required_questions = [question for question in questions if question["is_required"]]
answers = _current_answers(questions)
completed = sum(
    1
    for question in required_questions
    if answers[str(question["question_id"])].strip()
    or suggestions.get(str(question["question_id"]), "").strip()
)
total = len(required_questions)
st.markdown(f"**Required question progress:** Completed {completed}/{total} questions")
st.progress(completed / total if total else 1.0)

application_column, assistant_column = st.columns([1.15, 0.85], gap="large")

with application_column:
    st.subheader("AdditionalQuestionAnswers")
    st.caption("Review and edit the answers before submitting the application.")
    for index, question in enumerate(questions, start=1):
        question_id = str(question["question_id"])
        required_mark = " *" if question["is_required"] else ""
        field_help = (
            f"{'Required' if question['is_required'] else 'Optional'} · "
            f"ID {question_id}"
        )
        if question.get("description"):
            field_help = f"{question['description']} · {field_help}"

        if question["type"] == "select":
            select_options = [""] + question["options"]
            answer_key = _answer_key(question_id)
            if st.session_state.get(answer_key, "") not in select_options:
                st.session_state[answer_key] = ""
            st.selectbox(
                f"{index}. {question['question_text']}{required_mark}",
                options=select_options,
                key=answer_key,
                format_func=lambda value: value or "Select an option...",
                help=field_help,
            )
        elif question["type"] == "text":
            st.text_input(
                f"{index}. {question['question_text']}{required_mark}",
                key=_answer_key(question_id),
                placeholder="Enter your answer...",
                help=field_help,
            )
        else:
            st.text_area(
                f"{index}. {question['question_text']}{required_mark}",
                key=_answer_key(question_id),
                placeholder="Enter your answer...",
                help=field_help,
            )
    st.caption("This test UI does not submit or persist application data.")

with assistant_column:
    assistant_header, reset_column = st.columns([3, 1])
    with assistant_header:
        st.subheader("FAS Assistant")
        st.caption("● Ready to help")
    with reset_column:
        reset_clicked = st.button(
            "Reset",
            key="dfas_reset",
            use_container_width=True,
        )

    for chat_message in st.session_state["dfas_messages"]:
        with st.chat_message(chat_message["role"]):
            st.markdown(chat_message["content"])

    quick_left, quick_right = st.columns(2)
    with quick_left:
        quick_income = st.button(
            "My family income has recently decreased",
            key="dfas_quick_income",
            use_container_width=True,
            disabled=not questions,
        )
    with quick_right:
        quick_job = st.button(
            "My father recently lost his job",
            key="dfas_quick_job",
            use_container_width=True,
            disabled=not questions,
        )

    with st.form("dfas_chat_form", clear_on_submit=True):
        draft = st.text_area(
            "Message",
            placeholder="Describe your circumstances...",
            label_visibility="collapsed",
        )
        send_clicked = st.form_submit_button(
            "Send message",
            use_container_width=True,
            disabled=not questions,
        )

if reset_clicked:
    _reset_session()
    st.rerun()
if quick_income:
    _send_message("My family income has recently decreased", questions)
    st.rerun()
if quick_job:
    _send_message("My father recently lost his job", questions)
    st.rerun()
if send_clicked and draft.strip():
    _send_message(draft, questions)
    st.rerun()

st.divider()
suggestion_header, apply_all_column = st.columns([4, 1])
with suggestion_header:
    st.subheader("Suggestions awaiting your review")
    st.caption("Nothing is automatically written to the form.")
with apply_all_column:
    if len(suggestions) > 1:
        st.button(
            "Apply all",
            key="dfas_apply_all",
            on_click=_apply_all_suggestions,
            use_container_width=True,
        )

if not suggestions:
    st.info("No suggestions yet. Chat with AI to receive suggestions.")
else:
    question_lookup = {
        str(question["question_id"]): question for question in questions
    }
    for question_id, value in suggestions.items():
        question = question_lookup[question_id]
        with st.container(border=True):
            st.caption(f"Question {question_id}")
            st.markdown(f"**{question['question_text']}**")
            st.write(value)
        apply_column, dismiss_column, spacer = st.columns([1, 1, 4])
        with apply_column:
            st.button(
                "Apply",
                key=f"dfas_apply_{question_id}",
                on_click=_apply_suggestion,
                args=(question_id, value),
                use_container_width=True,
            )
        with dismiss_column:
            st.button(
                "Dismiss",
                key=f"dfas_dismiss_{question_id}",
                on_click=_dismiss_suggestion,
                args=(question_id,),
                use_container_width=True,
            )

confirmation = st.session_state.get("dfas_confirmation")
if confirmation:
    question_lookup = {
        str(question["question_id"]): question for question in questions
    }
    question = question_lookup.get(confirmation["question_id"])
    st.warning(
        f"Confirm update for: {question['question_text'] if question else confirmation['question_id']}"
    )
    compare_left, compare_right = st.columns(2)
    compare_left.markdown(
        f"**Current answer**\n\n{confirmation['current_value']}"
    )
    compare_right.markdown(
        f"**New suggestion**\n\n{confirmation['new_value']}"
    )
    keep_column, confirm_column, spacer = st.columns([1, 1, 3])
    keep_column.button(
        "Keep current answer",
        key="dfas_keep_current",
        on_click=_cancel_update,
        use_container_width=True,
    )
    confirm_column.button(
        "Confirm update",
        key="dfas_confirm_update",
        on_click=_confirm_update,
        use_container_width=True,
    )

if st.session_state.get("dfas_status"):
    st.success(st.session_state["dfas_status"])
if st.session_state.get("dfas_error"):
    st.error(st.session_state["dfas_error"])

with st.expander("Last API exchange", expanded=False):
    if st.session_state.get("dfas_last_payload"):
        st.markdown("**POST /dynamic-fas/chat**")
        st.code(
            json.dumps(
                st.session_state["dfas_last_payload"],
                indent=2,
                ensure_ascii=False,
            ),
            language="json",
        )
    if st.session_state.get("dfas_last_response"):
        st.markdown("**Last response**")
        st.code(
            json.dumps(
                st.session_state["dfas_last_response"],
                indent=2,
                ensure_ascii=False,
            ),
            language="json",
        )
    if not st.session_state.get("dfas_last_payload") and not st.session_state.get(
        "dfas_last_response"
    ):
        st.caption("No API request has been made in this browser session.")
