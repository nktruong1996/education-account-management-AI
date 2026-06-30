from models import AssistantState
from llm import client, DEPLOYMENT_NAME
from services.prompts import FORM_HELP_SYSTEM_PROMPT, FORM_HELP_USER_PROMPT

def generate_form_help_reply(state: AssistantState, message: str) -> str:
    prompt = FORM_HELP_USER_PROMPT.format(
        state_json=state.model_dump_json(),
        message=message
    )
    try:
        response = client.chat.completions.create(
            model=DEPLOYMENT_NAME,
            messages=[
                {"role": "system", "content": FORM_HELP_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_completion_tokens=500,
        )
        return response.choices[0].message.content or "I couldn't generate a response."
    except Exception:
        return "I am having trouble connecting to the AI service. Please try again."
