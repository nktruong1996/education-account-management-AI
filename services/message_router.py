import json
from typing import Literal
from pydantic import BaseModel
from llm import client, DEPLOYMENT_NAME
from services.prompts import MESSAGE_ROUTER_SYSTEM_PROMPT, MESSAGE_ROUTER_USER_PROMPT

RouteCategory = Literal["FORM_FILLING", "FORM_HELP", "FAQ_REDIRECT", "OFF_TOPIC"]

class MessageRoute(BaseModel):
    category: RouteCategory
    reply: str | None = None

def route_message(message: str) -> MessageRoute:
    try:
        response = client.chat.completions.create(
            model=DEPLOYMENT_NAME,
            messages=[
                {"role": "system", "content": MESSAGE_ROUTER_SYSTEM_PROMPT},
                {"role": "user", "content": MESSAGE_ROUTER_USER_PROMPT.format(message=message)},
            ],
            max_completion_tokens=200,
        )
        data = json.loads(response.choices[0].message.content or "")
        category = data.get("category", "FORM_FILLING")
        reply = data.get("reply", None)
        if category in {"FORM_FILLING", "FORM_HELP", "FAQ_REDIRECT", "OFF_TOPIC"}:
            return MessageRoute(category=category, reply=reply)
    except Exception:
        pass
    return MessageRoute(category="FORM_FILLING")
