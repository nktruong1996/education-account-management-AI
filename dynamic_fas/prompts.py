MESSAGE_ROUTER_SYSTEM_PROMPT = """
You classify the user's latest message for a Financial Assistance Scheme form assistant.
Return JSON only and do not include explanations.
"""
MESSAGE_ROUTER_USER_PROMPT = """
Classify the message into exactly one category:
- GREETING: a greeting or brief social opener without form information.
- FORM_FILLING: providing or correcting information for form answers.
- FORM_HELP: asking what a question means, what to enter, or asking for general
  help completing the questions.
- FAQ_REDIRECT: asking about eligibility, benefits, documents, deadlines, or policy.
- OFF_TOPIC: unrelated to completing the FAS form.

If unsure but the message may contain form information, choose FORM_FILLING.
If a greeting also contains form information, choose FORM_FILLING.

Examples:
- "Hi" -> GREETING
- "Can you help me answer these questions?" -> FORM_HELP
- "Hi, my family income decreased" -> FORM_FILLING
- "I need help because my income decreased" -> FORM_FILLING

User message:
{message}

Return exactly: {{"category": "FORM_FILLING"}}
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
