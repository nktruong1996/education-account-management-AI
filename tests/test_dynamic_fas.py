import unittest
from unittest.mock import Mock, patch

from dynamic_fas.change_detector import detect_changes
from dynamic_fas.conversation import handle_chat
from dynamic_fas.conversation_llm import get_fallback_reply
from dynamic_fas.extraction import extract_answers
from dynamic_fas.form_help import generate_form_help_reply
from dynamic_fas.message_router import MessageRoute, route_by_rules, route_message
from dynamic_fas.models import (
    DynamicAssistantState,
    DynamicChatRequest,
    DynamicQuestion,
    DynamicQuestionState,
)
from dynamic_fas.session_store import get_or_create_state, sessions


def question(
    question_id: int = 101,
    *,
    question_type: str = "textarea",
    options: list[str] | None = None,
) -> DynamicQuestion:
    return DynamicQuestion(
        question_id=question_id,
        question_text="What is your current financial situation?",
        is_required=True,
        description="Describe the household's current circumstances.",
        type=question_type,
        options=options or [],
    )


class DynamicFasTests(unittest.TestCase):
    def setUp(self) -> None:
        sessions.clear()

    def test_legacy_question_payload_remains_valid(self) -> None:
        legacy = DynamicQuestion(
            question_id=101,
            question_text="Describe your financial situation",
            is_required=True,
        )

        self.assertEqual(legacy.type, "textarea")
        self.assertIsNone(legacy.description)
        self.assertEqual(legacy.options, [])

    @patch("dynamic_fas.message_router.client.chat.completions.create")
    def test_short_greeting_uses_deterministic_route(self, create: Mock) -> None:
        route = route_message("Hi!")

        self.assertEqual(route.category, "GREETING")
        self.assertIn("Hello!", route.reply or "")
        create.assert_not_called()

    @patch("dynamic_fas.message_router.client.chat.completions.create")
    def test_general_help_uses_deterministic_route(self, create: Mock) -> None:
        route = route_message("Can you help me answer these questions?")

        self.assertEqual(route.category, "FORM_HELP")
        create.assert_not_called()

    def test_greeting_with_form_information_is_not_swallowed(self) -> None:
        route = route_by_rules("Hi, my family income decreased")

        self.assertIsNotNone(route)
        self.assertEqual(route.category, "FORM_FILLING")

    @patch("dynamic_fas.conversation.generate_assistant_reply", return_value="Next")
    @patch("dynamic_fas.conversation.extract_answers", return_value={})
    def test_leading_greeting_is_removed_before_extraction(
        self,
        extract_answers_mock: Mock,
        generate_reply: Mock,
    ) -> None:
        handle_chat(
            DynamicChatRequest(
                session_id="session-mixed-greeting",
                fas_scheme_id=10,
                message="Hi, my family income decreased",
                questions=[question()],
                current_answers={"101": ""},
            )
        )

        self.assertEqual(
            extract_answers_mock.call_args.kwargs["message"],
            "my family income decreased",
        )
        generate_reply.assert_called_once()

    @patch("dynamic_fas.message_router.client.chat.completions.create")
    def test_mixed_help_and_form_information_prefers_form_filling(
        self,
        create: Mock,
    ) -> None:
        response = Mock()
        response.choices = [
            Mock(message=Mock(content='{"category":"FORM_FILLING"}'))
        ]
        create.return_value = response

        route = route_message("I need help because my income decreased")

        self.assertEqual(route.category, "FORM_FILLING")

    @patch("dynamic_fas.conversation.extract_answers")
    @patch("dynamic_fas.message_router.client.chat.completions.create")
    def test_greeting_does_not_run_extraction_or_change_progress(
        self,
        router_llm: Mock,
        extract_answers_mock: Mock,
    ) -> None:
        response = handle_chat(
            DynamicChatRequest(
                session_id="session-greeting",
                fas_scheme_id=10,
                message="Hi",
                questions=[question()],
                current_answers={"101": ""},
            )
        )

        self.assertIn("Hello!", response.reply)
        self.assertEqual(response.suggested_fields, {})
        self.assertEqual(response.progress.completed, 0)
        extract_answers_mock.assert_not_called()
        router_llm.assert_not_called()

    @patch("dynamic_fas.conversation.extract_answers")
    @patch("dynamic_fas.form_help.client.chat.completions.create")
    def test_general_help_starts_with_pending_question_without_extraction(
        self,
        help_llm: Mock,
        extract_answers_mock: Mock,
    ) -> None:
        response = handle_chat(
            DynamicChatRequest(
                session_id="session-general-help",
                fas_scheme_id=10,
                message="Can you help me answer these questions?",
                questions=[question()],
                current_answers={"101": ""},
            )
        )

        self.assertIn("go through the questions one at a time", response.reply)
        self.assertIn("What is your current financial situation?", response.reply)
        self.assertEqual(response.suggested_fields, {})
        self.assertEqual(response.progress.completed, 0)
        extract_answers_mock.assert_not_called()
        help_llm.assert_not_called()

    @patch("dynamic_fas.conversation.route_message")
    def test_pending_confirmation_remains_higher_priority_than_greeting(
        self,
        route_message_mock: Mock,
    ) -> None:
        pending_question = question()
        sessions["session-pending-greeting"] = DynamicAssistantState(
            fas_scheme_id=10,
            questions={
                "101": DynamicQuestionState(
                    **pending_question.model_dump(),
                    value="Existing value",
                    pending_value="New value",
                    status="pending_update",
                    source="current_form",
                )
            },
            question_order=["101"],
            pending_update_question_id=101,
        )

        response = handle_chat(
            DynamicChatRequest(
                session_id="session-pending-greeting",
                fas_scheme_id=10,
                message="Hi",
                questions=[pending_question],
                current_answers={"101": "Existing value"},
            )
        )

        self.assertIn("Reply “Yes”", response.reply)
        route_message_mock.assert_not_called()

    def test_select_question_requires_options(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one option"):
            question(question_type="select")

    def test_reconcile_adopts_current_form_answer(self) -> None:
        request = DynamicChatRequest(
            session_id="session-current-answer",
            fas_scheme_id=10,
            message="Hello",
            questions=[question()],
            current_answers={"101": "Existing form value"},
        )

        state = get_or_create_state(request)

        self.assertEqual(state.questions["101"].value, "Existing form value")
        self.assertEqual(state.questions["101"].status, "existing")
        self.assertEqual(state.questions["101"].source, "current_form")

    def test_change_detector_ignores_case_and_whitespace(self) -> None:
        state = DynamicAssistantState(
            fas_scheme_id=10,
            questions={
                "101": DynamicQuestionState(
                    question_id=101,
                    question_text="Question",
                    is_required=True,
                    value="Income decreased",
                    status="existing",
                )
            },
            question_order=["101"],
        )

        changes = detect_changes(state, {"101": "  income   DECREASED "})

        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].change_type, "same")
        self.assertEqual(changes[0].new_value, "income DECREASED")

    @patch("dynamic_fas.conversation.generate_assistant_reply", return_value="Next")
    @patch("dynamic_fas.conversation.extract_answers")
    @patch("dynamic_fas.conversation.route_message")
    def test_existing_answer_requires_confirmation_before_update(
        self,
        route_message: Mock,
        extract_answers_mock: Mock,
        generate_reply: Mock,
    ) -> None:
        route_message.return_value = MessageRoute(category="FORM_FILLING")
        extract_answers_mock.return_value = {"101": "New form value"}
        initial_request = DynamicChatRequest(
            session_id="session-update",
            fas_scheme_id=10,
            message="Actually it changed",
            questions=[question()],
            current_answers={"101": "Existing form value"},
        )

        pending_response = handle_chat(initial_request)

        pending = pending_response.assistant_state.questions["101"]
        self.assertEqual(pending.value, "Existing form value")
        self.assertEqual(pending.pending_value, "New form value")
        self.assertEqual(pending.status, "pending_update")
        self.assertEqual(pending_response.suggested_fields, {})

        confirmed_response = handle_chat(
            initial_request.model_copy(update={"message": "yes"})
        )

        confirmed = confirmed_response.assistant_state.questions["101"]
        self.assertEqual(confirmed.value, "New form value")
        self.assertIsNone(confirmed.pending_value)
        self.assertEqual(confirmed.status, "suggested")
        self.assertEqual(confirmed.source, "confirmed_update")
        self.assertEqual(
            confirmed_response.suggested_fields,
            {"101": "New form value"},
        )
        generate_reply.assert_called_once()

    @patch("dynamic_fas.extraction.client.chat.completions.create")
    def test_select_extraction_returns_canonical_option(self, create: Mock) -> None:
        response = Mock()
        response.choices = [Mock(message=Mock(content='{"answers":{"101":"part-time"}}'))]
        create.return_value = response
        select_question = question(
            question_type="select",
            options=["Full-time", "Part-time"],
        )

        extracted = extract_answers(
            "I work part-time",
            [select_question],
            pending_question_id=101,
        )

        self.assertEqual(extracted, {"101": "Part-time"})

    @patch("dynamic_fas.extraction.client.chat.completions.create")
    def test_select_extraction_rejects_unknown_option(self, create: Mock) -> None:
        response = Mock()
        response.choices = [Mock(message=Mock(content='{"answers":{"101":"Contract"}}'))]
        create.return_value = response

        extracted = extract_answers(
            "I am a contractor",
            [
                question(
                    question_type="select",
                    options=["Full-time", "Part-time"],
                )
            ],
            pending_question_id=101,
        )

        self.assertEqual(extracted, {})

    def test_form_help_uses_select_metadata_without_llm(self) -> None:
        select_question = question(
            question_type="select",
            options=["Full-time", "Part-time"],
        )
        state = DynamicAssistantState(
            fas_scheme_id=10,
            questions={"101": DynamicQuestionState(**select_question.model_dump())},
            question_order=["101"],
            pending_question_id=101,
        )

        with patch("dynamic_fas.form_help.client.chat.completions.create") as create:
            reply = generate_form_help_reply(
                state,
                [select_question],
                "What should I put for question 101?",
            )

        self.assertIn("Full-time, Part-time", reply)
        self.assertIn("required", reply)
        create.assert_not_called()

    def test_conversation_fallback_asks_next_required_question(self) -> None:
        state = DynamicAssistantState(
            fas_scheme_id=10,
            questions={
                "101": DynamicQuestionState(
                    question_id=101,
                    question_text="Describe your current situation",
                    is_required=True,
                )
            },
            question_order=["101"],
            pending_question_id=101,
        )

        reply = get_fallback_reply(state, extracted_any=False)

        self.assertEqual(
            reply,
            "I could not identify a clear answer. Describe your current situation",
        )


if __name__ == "__main__":
    unittest.main()
