MESSAGE_ROUTER_SYSTEM_PROMPT = """
You classify the user's latest message for a Financial Assistance Scheme form assistant.
Return JSON only and do not include explanations.
"""
MESSAGE_ROUTER_USER_PROMPT = """
Classify the message into exactly one category:
- FORM_FILLING: providing or correcting information for form answers.
- FORM_HELP: asking what a question means, what to enter, or asking for general
  help completing the questions.
- EXAMPLE_REQUEST: asking for examples, sample wording, or asking the assistant
  to make up/write an answer for the user.
- SMALL_TALK: polite acknowledgements, casual remarks, emotional reactions, or
  short social messages that do not provide form-answer information.
- FAQ_REDIRECT: asking about eligibility, benefits, documents, deadlines, or policy.
- OFF_TOPIC: unrelated to completing the FAS form.
- UNCLEAR: ambiguous between asking for help and providing an answer.

If unsure but the message may contain form information, choose FORM_FILLING.
If the user asks what to put, what kind of information to include, or how to
answer a question, choose FORM_HELP.
If the user asks for sample wording or asks you to make up/write the answer,
choose EXAMPLE_REQUEST.

Examples:
- "Can you help me answer these questions?" -> FORM_HELP
- "What should I put here?" -> FORM_HELP
- "What kind of information should I put in this question?" -> FORM_HELP
- "This specific one, 'Briefly explain the primary reason...', what do I put?" -> FORM_HELP
- "Can you make up an answer for me?" -> EXAMPLE_REQUEST
- "Give me an example answer for this field" -> EXAMPLE_REQUEST
- "Write it for me" -> EXAMPLE_REQUEST
- "Thanks" -> SMALL_TALK
- "Okay" -> SMALL_TALK
- "My family is happy" -> SMALL_TALK
- "Haha nice" -> SMALL_TALK
- "Hi, my family income decreased" -> FORM_FILLING
- "I need help because my income decreased" -> FORM_FILLING
- "My family is poor and cannot cover tuition" -> FORM_FILLING
- "Actually, my reason is that my work hours were reduced" -> FORM_FILLING
- "Am I eligible for this scheme?" -> FAQ_REDIRECT
- "What documents do I need?" -> FAQ_REDIRECT
- "Tell me a joke" -> OFF_TOPIC
- "This one" -> UNCLEAR

User message:
{message}

Return JSON only, using one of the categories above and one confidence value.
Example output format:
{{"category": "FORM_HELP", "confidence": "high"}}
"""
EXTRACTION_SYSTEM_PROMPT = """
You are a strict JSON extraction engine for a Financial Assistance Scheme form.
Return JSON only. Do not include explanations.
"""
EXTRACTION_USER_PROMPT = """
Extract structured answers from the user's latest message.

Configured questions:
{questions_context}

Current pending question ID:
{pending_question_id}

Rules:
- Use exactly the configured question IDs as JSON keys.
- Extract only information explicitly provided by the user.
- Do not infer or invent missing values.
- A message may answer multiple questions or correct a previous answer.
- The pending question is context only; do not blindly assign the message to it.
- Ignore greetings or requests for help when the same message also provides clear
  form information; extract the explicit form information.
- For select questions, return exactly one configured option when clearly indicated.
- Use null for questions not clearly answered.

User message:
{message}

Return exactly this JSON shape:
{{"answers": {empty_shape}}}
"""

ANSWER_REVISION_SYSTEM_PROMPT = """
You revise one Financial Assistance Scheme form answer.
Return JSON only. Do not include explanations.
"""

ANSWER_REVISION_USER_PROMPT = """
Revise the answer for one form question.

Question:
{question_text}

Existing field answer:
{existing_answer}

Extracted answer from the latest user message:
{extracted_answer}

Latest user message:
{user_message}

Task:
- Return one concise answer suitable for the field.
- Preserve existing facts unless the latest user message corrects or removes them.
- Add only genuinely new facts from the latest user message or extracted answer.
- Do not repeat facts already covered.
- Do not invent names, dates, amounts, medical details, employment details, or hardship details.
- Preserve important numbers, dates, people, medical conditions, income, expenses, and uncertainty.
- Keep first-person wording if the user's answer is first person.
- If the latest user message asks to exaggerate or add unsupported details, keep the factual answer unchanged.
- If the latest user message is already covered by the existing answer, return the existing field answer exactly.
- Do not make cosmetic wording changes when no new factual detail is added.

Examples:
- Existing: "My father lost his job, so we cannot cover tuition."
  Extracted: "My father lost his job."
  Latest: "Also say my father lost his job."
  Answer: "My father lost his job, so we cannot cover tuition."
  Reason: "deduplicated"
- Existing: "My father lost his job, so we cannot cover tuition."
  Extracted: "We are behind on rent and utility bills."
  Latest: "Also add that we are behind on rent and utility bills."
  Answer: "My father lost his job, so we cannot cover tuition, and we are behind on rent and utility bills."
  Reason: "added_new_fact"

Return JSON only:
{{"answer": "...", "changed": true, "reason": "compressed_long_answer | added_new_fact | deduplicated | unchanged"}}
"""
