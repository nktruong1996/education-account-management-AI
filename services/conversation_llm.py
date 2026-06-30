import json
from models import AssistantState
from llm import client, DEPLOYMENT_NAME
from services.prompts import CONVERSATION_SYSTEM_PROMPT, CONVERSATION_USER_PROMPT

def generate_assistant_reply(state: AssistantState, user_message: str) -> str:
    prompt = CONVERSATION_USER_PROMPT.format(
        state_json=state.model_dump_json(),
        user_message=user_message
    )
    try:
        response = client.chat.completions.create(
            model=DEPLOYMENT_NAME,
            messages=[
                {"role": "system", "content": CONVERSATION_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_completion_tokens=500,
        )
        return response.choices[0].message.content or "I couldn't generate a response."
    except Exception:
        return "I am having trouble connecting to the AI service. Please try again."
