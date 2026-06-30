MESSAGE_ROUTER_SYSTEM_PROMPT = "You classify the latest message sent to an assistant. Return JSON only."
MESSAGE_ROUTER_USER_PROMPT = """
Classify the message into exactly one category: FORM_FILLING, FORM_HELP, FAQ_REDIRECT, OFF_TOPIC.
Message: {message}
Return exactly: {{"category": "FORM_FILLING"}}
"""
EXTRACTION_SYSTEM_PROMPT = "You are a strict information extraction engine. Return JSON only."
EXTRACTION_USER_PROMPT = """
Extract answers from the user's latest message for the configured questions.
Configured questions: {questions_json}
Current question being asked: {pending_question_id}
User message: {message}
Return exactly this JSON shape:
{{ "answers": {{ "101": "Clearly provided answer" }} }}
"""
