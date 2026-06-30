import unittest
from unittest.mock import Mock, patch

from dynamic_fas.change_detector import detect_changes
from dynamic_fas.conversation import handle_chat
from dynamic_fas.conversation_llm import get_fallback_reply
from dynamic_fas.extraction import extract_answers
from dynamic_fas.answer_revision import revise_extracted_answers
from dynamic_fas.form_help import generate_form_help_reply
from dynamic_fas.message_router import MessageRoute, route_by_rules, route_message
from dynamic_fas.models import (
    DynamicAssistantState,
    DynamicChatRequest,
    DynamicQuestion,
    DynamicQuestionState,
)
from dynamic_fas.session_store import (
    get_or_create_state,
    optional_prompt_shown_sessions,
    sessions,
)


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


def financial_reason_question(question_id: int = 201) -> DynamicQuestion:
    return DynamicQuestion(
        question_id=question_id,
        question_text="Briefly explain the primary reason for your financial assistance application.",
        is_required=True,
        description="Explain the applicant's real financial circumstances.",
        type="textarea",
    )


def medical_condition_question(question_id: int = 202) -> DynamicQuestion:
    return DynamicQuestion(
        question_id=question_id,
        question_text="Are there any specific medical conditions in your household?",
        is_required=False,
        description="Mention any household medical condition relevant to the application.",
        type="textarea",
    )


def employment_status_question(question_id: int = 203) -> DynamicQuestion:
    return DynamicQuestion(
        question_id=question_id,
        question_text="What is your current employment status?",
        is_required=True,
        description="Choose the current employment status.",
        type="select",
        options=["Full-time", "Part-time", "Unemployed"],
    )


def multi_question_form() -> list[DynamicQuestion]:
    return [
        financial_reason_question(),
        medical_condition_question(),
        employment_status_question(),
    ]


class DynamicFasTests(unittest.TestCase):
    def setUp(self) -> None:
        sessions.clear()
        optional_prompt_shown_sessions.clear()

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

    @patch("dynamic_fas.message_router.client.chat.completions.create")
    def test_llm_router_supports_example_request(self, create: Mock) -> None:
        response = Mock()
        response.choices = [
            Mock(message=Mock(content='{"category":"EXAMPLE_REQUEST","confidence":"high"}'))
        ]
        create.return_value = response

        route = route_message("Can you make up an answer for me as an example?")

        self.assertEqual(route.category, "EXAMPLE_REQUEST")
        self.assertIn("can't make up", route.reply or "")

    @patch("dynamic_fas.message_router.client.chat.completions.create")
    def test_llm_router_supports_question_help_wording(self, create: Mock) -> None:
        response = Mock()
        response.choices = [
            Mock(message=Mock(content='{"category":"FORM_HELP","confidence":"high"}'))
        ]
        create.return_value = response

        route = route_message("What kind of information should I put in this question?")

        self.assertEqual(route.category, "FORM_HELP")

    @patch("dynamic_fas.message_router.client.chat.completions.create")
    def test_low_confidence_router_result_asks_clarification(self, create: Mock) -> None:
        response = Mock()
        response.choices = [
            Mock(message=Mock(content='{"category":"FORM_FILLING","confidence":"low"}'))
        ]
        create.return_value = response

        route = route_message("This one")

        self.assertEqual(route.category, "UNCLEAR")
        self.assertIn("Just to check", route.reply or "")

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
    @patch("dynamic_fas.conversation.route_message")
    def test_small_talk_does_not_run_extraction(
        self,
        route_message_mock: Mock,
        extract_answers_mock: Mock,
    ) -> None:
        route_message_mock.return_value = MessageRoute(
            category="SMALL_TALK",
            reply="Got it. For this form, I'll only use information that directly answers the FAS questions.",
        )

        response = handle_chat(
            DynamicChatRequest(
                session_id="session-small-talk",
                fas_scheme_id=10,
                message="My family is happy",
                questions=[question()],
                current_answers={"101": "Existing answer"},
            )
        )

        self.assertIn("directly answers the FAS questions", response.reply)
        self.assertEqual(response.suggested_fields, {})
        extract_answers_mock.assert_not_called()

    @patch("dynamic_fas.conversation.extract_answers")
    @patch("dynamic_fas.conversation.route_message")
    def test_example_request_refuses_to_fabricate_without_suggestion(
        self,
        route_message_mock: Mock,
        extract_answers_mock: Mock,
    ) -> None:
        route_message_mock.return_value = MessageRoute(
            category="EXAMPLE_REQUEST",
            reply="I can't make up an answer for you.",
        )

        response = handle_chat(
            DynamicChatRequest(
                session_id="session-example-request",
                fas_scheme_id=10,
                message="Can you make up an answer for me as an example?",
                questions=[question()],
                current_answers={"101": ""},
            )
        )

        self.assertIn("can't make up", response.reply)
        self.assertIn("Use only what is true", response.reply)
        self.assertEqual(response.suggested_fields, {})
        self.assertEqual(response.progress.completed, 0)
        extract_answers_mock.assert_not_called()

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
    @patch("dynamic_fas.conversation.revise_extracted_answers")
    @patch("dynamic_fas.conversation.extract_answers")
    @patch("dynamic_fas.conversation.route_message")
    def test_existing_answer_requires_confirmation_before_update(
        self,
        route_message: Mock,
        extract_answers_mock: Mock,
        revise_answers_mock: Mock,
        generate_reply: Mock,
    ) -> None:
        route_message.return_value = MessageRoute(category="FORM_FILLING")
        extract_answers_mock.return_value = {"101": "New form value"}
        revise_answers_mock.return_value = {"101": "New form value"}
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

    @patch("dynamic_fas.extraction.client.chat.completions.create")
    def test_extraction_accepts_multiple_answers_from_one_message(self, create: Mock) -> None:
        response = Mock()
        response.choices = [
            Mock(
                message=Mock(
                    content=(
                        '{"answers":{'
                        '"201":"My income dropped and I cannot cover tuition fees.",'
                        '"202":"My father has diabetes.",'
                        '"203":"part-time"'
                        "}}"
                    )
                )
            )
        ]
        create.return_value = response

        extracted = extract_answers(
            (
                "I work part-time. My father has diabetes, and my income dropped "
                "so I cannot cover tuition fees."
            ),
            multi_question_form(),
            pending_question_id=201,
        )

        self.assertEqual(
            extracted,
            {
                "201": "My income dropped and I cannot cover tuition fees.",
                "202": "My father has diabetes.",
                "203": "Part-time",
            },
        )

    @patch("dynamic_fas.extraction.client.chat.completions.create")
    def test_extraction_is_not_order_dependent(self, create: Mock) -> None:
        response = Mock()
        response.choices = [
            Mock(
                message=Mock(
                    content=(
                        '{"answers":{'
                        '"203":"unemployed",'
                        '"201":"I lost my job and need help paying school fees.",'
                        '"202":null'
                        "}}"
                    )
                )
            )
        ]
        create.return_value = response

        extracted = extract_answers(
            "I lost my job and need help paying school fees. I am unemployed.",
            multi_question_form(),
            pending_question_id=201,
        )

        self.assertEqual(
            extracted,
            {
                "201": "I lost my job and need help paying school fees.",
                "203": "Unemployed",
            },
        )

    @patch("dynamic_fas.extraction.client.chat.completions.create")
    def test_extraction_ignores_unknown_or_empty_answers(self, create: Mock) -> None:
        response = Mock()
        response.choices = [
            Mock(
                message=Mock(
                    content='{"answers":{"201":"Income reduced.","999":"Ignore me","202":""}}'
                )
            )
        ]
        create.return_value = response

        extracted = extract_answers(
            "Income reduced.",
            multi_question_form(),
            pending_question_id=201,
        )

        self.assertEqual(extracted, {"201": "Income reduced."})

    @patch("dynamic_fas.conversation.generate_assistant_reply", return_value="Review the suggestions.")
    @patch("dynamic_fas.conversation.extract_answers")
    @patch("dynamic_fas.conversation.route_message")
    def test_conversation_applies_all_extracted_answers_from_one_message(
        self,
        route_message_mock: Mock,
        extract_answers_mock: Mock,
        generate_reply: Mock,
    ) -> None:
        route_message_mock.return_value = MessageRoute(category="FORM_FILLING")
        extract_answers_mock.return_value = {
            "201": "My income dropped and I cannot cover tuition fees.",
            "202": "My father has diabetes.",
            "203": "Part-time",
        }

        response = handle_chat(
            DynamicChatRequest(
                session_id="session-multi-answer",
                fas_scheme_id=10,
                message=(
                    "I work part-time. My father has diabetes, and my income dropped "
                    "so I cannot cover tuition fees."
                ),
                questions=multi_question_form(),
                current_answers={"201": "", "202": "", "203": ""},
            )
        )

        self.assertEqual(
            response.suggested_fields,
            {
                "201": "My income dropped and I cannot cover tuition fees.",
                "202": "My father has diabetes.",
                "203": "Part-time",
            },
        )
        self.assertEqual(response.progress.completed, 2)
        self.assertEqual(response.progress.total, 2)
        self.assertIsNone(response.assistant_state.pending_question_id)
        generate_reply.assert_called_once()

    @patch("dynamic_fas.answer_revision.client.chat.completions.create")
    def test_short_new_answer_skips_revision(self, create: Mock) -> None:
        state = DynamicAssistantState(
            fas_scheme_id=10,
            questions={
                "201": DynamicQuestionState(
                    **financial_reason_question().model_dump()
                )
            },
            question_order=["201"],
        )

        revised = revise_extracted_answers(
            state=state,
            questions=[financial_reason_question()],
            answers={"201": "My income dropped and I cannot cover tuition."},
            user_message="My income dropped and I cannot cover tuition.",
        )

        self.assertEqual(
            revised,
            {"201": "My income dropped and I cannot cover tuition."},
        )
        create.assert_not_called()

    @patch("dynamic_fas.answer_revision.client.chat.completions.create")
    def test_text_field_update_skips_revision(self, create: Mock) -> None:
        employer_question = DynamicQuestion(
            question_id=202,
            question_text="Who is your current employer?",
            is_required=False,
            description="Name the company or business where you currently work, if applicable.",
            type="text",
        )
        state = DynamicAssistantState(
            fas_scheme_id=10,
            questions={
                "202": DynamicQuestionState(
                    **employer_question.model_dump(),
                    value="KFC",
                    status="suggested",
                )
            },
            question_order=["202"],
        )

        revised = revise_extracted_answers(
            state=state,
            questions=[employer_question],
            answers={"202": "Lotteria"},
            user_message="I work at Lotteria now.",
        )

        self.assertEqual(revised, {"202": "Lotteria"})
        create.assert_not_called()

    @patch("dynamic_fas.answer_revision.client.chat.completions.create")
    def test_long_new_answer_is_compressed(self, create: Mock) -> None:
        response = Mock()
        response.choices = [
            Mock(
                message=Mock(
                    content=(
                        '{"answer":"My father lost his job, our income dropped, '
                        'and we cannot cover tuition while also paying household '
                        'expenses.","changed":true,'
                        '"reason":"compressed_long_answer"}'
                    )
                )
            )
        ]
        create.return_value = response
        long_answer = (
            "My father lost his job last month and our income dropped. "
            "We cannot cover tuition and household expenses. "
            + "This sentence repeats background details. " * 30
        )
        state = DynamicAssistantState(
            fas_scheme_id=10,
            questions={
                "201": DynamicQuestionState(
                    **financial_reason_question().model_dump()
                )
            },
            question_order=["201"],
        )

        revised = revise_extracted_answers(
            state=state,
            questions=[financial_reason_question()],
            answers={"201": long_answer},
            user_message=long_answer,
        )

        self.assertEqual(
            revised["201"],
            (
                "My father lost his job, our income dropped, and we cannot cover "
                "tuition while also paying household expenses."
            ),
        )
        create.assert_called_once()

    @patch("dynamic_fas.answer_revision.client.chat.completions.create")
    def test_existing_answer_adds_new_fact_without_history(self, create: Mock) -> None:
        response = Mock()
        response.choices = [
            Mock(
                message=Mock(
                    content=(
                        '{"answer":"My father lost his job and my mother has '
                        'medical bills, so we cannot cover tuition.",'
                        '"changed":true,"reason":"added_new_fact"}'
                    )
                )
            )
        ]
        create.return_value = response
        state = DynamicAssistantState(
            fas_scheme_id=10,
            questions={
                "201": DynamicQuestionState(
                    **financial_reason_question().model_dump(),
                    value="My father lost his job, so we cannot cover tuition.",
                    status="suggested",
                )
            },
            question_order=["201"],
        )

        revised = revise_extracted_answers(
            state=state,
            questions=[financial_reason_question()],
            answers={"201": "My mother has medical bills."},
            user_message="Also add that my mother has medical bills.",
        )

        self.assertEqual(
            revised["201"],
            "My father lost his job and my mother has medical bills, so we cannot cover tuition.",
        )
        prompt = create.call_args.kwargs["messages"][1]["content"]
        self.assertIn("Existing field answer:", prompt)
        self.assertIn("Latest user message:", prompt)

    @patch("dynamic_fas.answer_revision.client.chat.completions.create")
    def test_explicit_replacement_skips_revision_so_confirmation_can_trigger(self, create: Mock) -> None:
        state = DynamicAssistantState(
            fas_scheme_id=10,
            questions={
                "201": DynamicQuestionState(
                    **financial_reason_question().model_dump(),
                    value="My father lost his job, so we cannot cover tuition.",
                    status="suggested",
                )
            },
            question_order=["201"],
        )

        revised = revise_extracted_answers(
            state=state,
            questions=[financial_reason_question()],
            answers={"201": "family income is not enough to cover tuition"},
            user_message=(
                "actually change my primary reason for financial assistance "
                "application to: family income is not enough to cover tuition"
            ),
        )

        self.assertEqual(
            revised,
            {"201": "family income is not enough to cover tuition"},
        )
        create.assert_not_called()

    @patch("dynamic_fas.answer_revision.client.chat.completions.create")
    def test_existing_answer_deduplicates_repeated_fact(self, create: Mock) -> None:
        response = Mock()
        response.choices = [
            Mock(
                message=Mock(
                    content=(
                        '{"answer":"My father lost his job, so we cannot cover '
                        'tuition.","changed":false,"reason":"deduplicated"}'
                    )
                )
            )
        ]
        create.return_value = response
        state = DynamicAssistantState(
            fas_scheme_id=10,
            questions={
                "201": DynamicQuestionState(
                    **financial_reason_question().model_dump(),
                    value="My father lost his job, so we cannot cover tuition.",
                    status="suggested",
                )
            },
            question_order=["201"],
        )

        revised = revise_extracted_answers(
            state=state,
            questions=[financial_reason_question()],
            answers={"201": "My father lost his job."},
            user_message="Also say my father lost his job.",
        )

        self.assertEqual(
            revised["201"],
            "My father lost his job, so we cannot cover tuition.",
        )

    @patch("dynamic_fas.answer_revision.client.chat.completions.create")
    def test_revision_error_keeps_extracted_answer(self, create: Mock) -> None:
        create.side_effect = RuntimeError("LLM unavailable")
        state = DynamicAssistantState(
            fas_scheme_id=10,
            questions={
                "201": DynamicQuestionState(
                    **financial_reason_question().model_dump(),
                    value="My father lost his job.",
                    status="suggested",
                )
            },
            question_order=["201"],
        )

        revised = revise_extracted_answers(
            state=state,
            questions=[financial_reason_question()],
            answers={"201": "My mother has medical bills."},
            user_message="Also add that my mother has medical bills.",
        )

        self.assertEqual(revised, {"201": "My mother has medical bills."})

    @patch("dynamic_fas.conversation.generate_assistant_reply", return_value="Next question.")
    @patch("dynamic_fas.conversation.extract_answers")
    @patch("dynamic_fas.conversation.route_message")
    def test_conversation_accumulates_partial_information_across_turns(
        self,
        route_message_mock: Mock,
        extract_answers_mock: Mock,
        generate_reply: Mock,
    ) -> None:
        route_message_mock.return_value = MessageRoute(category="FORM_FILLING")
        extract_answers_mock.side_effect = [
            {"201": "My income dropped and I cannot cover tuition fees."},
            {"203": "Unemployed"},
        ]
        questions = multi_question_form()

        first = handle_chat(
            DynamicChatRequest(
                session_id="session-partial-answers",
                fas_scheme_id=10,
                message="My income dropped and I cannot cover tuition fees.",
                questions=questions,
                current_answers={"201": "", "202": "", "203": ""},
            )
        )
        self.assertEqual(first.progress.completed, 1)
        self.assertEqual(first.assistant_state.pending_question_id, 203)

        second = handle_chat(
            DynamicChatRequest(
                session_id="session-partial-answers",
                fas_scheme_id=10,
                message="I am unemployed.",
                questions=questions,
                current_answers={"201": "", "202": "", "203": ""},
            )
        )

        self.assertEqual(
            second.suggested_fields,
            {
                "201": "My income dropped and I cannot cover tuition fees.",
                "203": "Unemployed",
            },
        )
        self.assertEqual(second.progress.completed, 2)
        self.assertIsNone(second.assistant_state.pending_question_id)

    @patch("dynamic_fas.conversation.generate_assistant_reply", return_value="Review the suggestions.")
    @patch("dynamic_fas.conversation.extract_answers")
    @patch("dynamic_fas.conversation.route_message")
    def test_required_complete_lists_blank_optional_fields_once(
        self,
        route_message_mock: Mock,
        extract_answers_mock: Mock,
        generate_reply: Mock,
    ) -> None:
        route_message_mock.return_value = MessageRoute(category="FORM_FILLING")
        extract_answers_mock.return_value = {
            "201": "My income dropped and I cannot cover tuition fees.",
            "203": "Unemployed",
        }

        response = handle_chat(
            DynamicChatRequest(
                session_id="session-optional-list",
                fas_scheme_id=10,
                message="My income dropped and I am unemployed.",
                questions=multi_question_form(),
                current_answers={"201": "", "202": "", "203": ""},
            )
        )

        self.assertIn("Required questions are complete", response.reply)
        self.assertIn("Optional questions still blank", response.reply)
        self.assertIn("Are there any specific medical conditions", response.reply)
        self.assertEqual(response.progress.completed, 2)
        self.assertFalse(hasattr(response.assistant_state, "optional_prompt_shown"))
        generate_reply.assert_not_called()

        extract_answers_mock.return_value = {}
        second = handle_chat(
            DynamicChatRequest(
                session_id="session-optional-list",
                fas_scheme_id=10,
                message="okay",
                questions=multi_question_form(),
                current_answers={"201": "", "202": "", "203": ""},
            )
        )

        self.assertNotIn("Optional questions still blank", second.reply)
        generate_reply.assert_called_once()

    @patch("dynamic_fas.conversation.generate_assistant_reply", return_value="Review the suggestions.")
    @patch("dynamic_fas.conversation.extract_answers")
    @patch("dynamic_fas.conversation.route_message")
    def test_no_optional_list_when_all_optional_fields_answered(
        self,
        route_message_mock: Mock,
        extract_answers_mock: Mock,
        generate_reply: Mock,
    ) -> None:
        route_message_mock.return_value = MessageRoute(category="FORM_FILLING")
        extract_answers_mock.return_value = {
            "201": "My income dropped and I cannot cover tuition fees.",
            "202": "My father has diabetes.",
            "203": "Unemployed",
        }

        response = handle_chat(
            DynamicChatRequest(
                session_id="session-no-optional-list",
                fas_scheme_id=10,
                message="My income dropped, my father has diabetes, and I am unemployed.",
                questions=multi_question_form(),
                current_answers={"201": "", "202": "", "203": ""},
            )
        )

        self.assertNotIn("Optional questions still blank", response.reply)
        self.assertEqual(response.reply, "Review the suggestions.")
        generate_reply.assert_called_once()

    @patch("dynamic_fas.conversation.generate_assistant_reply", return_value="Review the suggestions.")
    @patch("dynamic_fas.conversation.extract_answers")
    @patch("dynamic_fas.conversation.route_message")
    def test_optional_field_can_still_be_filled_after_optional_list(
        self,
        route_message_mock: Mock,
        extract_answers_mock: Mock,
        generate_reply: Mock,
    ) -> None:
        route_message_mock.return_value = MessageRoute(category="FORM_FILLING")
        extract_answers_mock.side_effect = [
            {
                "201": "My income dropped and I cannot cover tuition fees.",
                "203": "Unemployed",
            },
            {"202": "My father has diabetes."},
        ]

        first = handle_chat(
            DynamicChatRequest(
                session_id="session-fill-optional-later",
                fas_scheme_id=10,
                message="My income dropped and I am unemployed.",
                questions=multi_question_form(),
                current_answers={"201": "", "202": "", "203": ""},
            )
        )
        self.assertIn("Optional questions still blank", first.reply)

        second = handle_chat(
            DynamicChatRequest(
                session_id="session-fill-optional-later",
                fas_scheme_id=10,
                message="My father has diabetes.",
                questions=multi_question_form(),
                current_answers={"201": "", "202": "", "203": ""},
            )
        )

        self.assertEqual(
            second.suggested_fields,
            {
                "201": "My income dropped and I cannot cover tuition fees.",
                "202": "My father has diabetes.",
                "203": "Unemployed",
            },
        )
        self.assertNotIn("Optional questions still blank", second.reply)

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

    def test_form_help_uses_pending_question_for_this_question(self) -> None:
        pending_question = DynamicQuestion(
            question_id=101,
            question_text="Briefly explain the primary reason for your financial assistance application.",
            is_required=True,
            description=None,
            type="textarea",
        )
        state = DynamicAssistantState(
            fas_scheme_id=10,
            questions={"101": DynamicQuestionState(**pending_question.model_dump())},
            question_order=["101"],
            pending_question_id=101,
        )

        with patch("dynamic_fas.form_help.client.chat.completions.create") as create:
            reply = generate_form_help_reply(
                state,
                [pending_question],
                "What kind of information should I put in this question?",
            )

        self.assertIn("Briefly explain the primary reason", reply)
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
