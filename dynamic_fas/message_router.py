import json
import re
from typing import Literal

from pydantic import BaseModel

from config import CHAT_MODEL, client
from dynamic_fas.prompts import MESSAGE_ROUTER_SYSTEM_PROMPT, MESSAGE_ROUTER_USER_PROMPT


RouteCategory = Literal[
    "GREETING",
    "FORM_FILLING",
    "FORM_HELP",
    "FAQ_REDIRECT",
    "OFF_TOPIC",
]

GREETING_MESSAGES = {
    "hi",
    "hello",
    "hey",
    "good morning",
    "good afternoon",
    "good evening",
    "xin chào",
    "chào bạn",
}

GENERAL_HELP_MESSAGES = {
    "can you help me",
    "can you help me answer these questions",
    "can you help me complete this form",
    "help me answer these questions",
    "help me complete this form",
    "i need help",
    "please help me",
    "can you guide me through these questions",
    "how can you help me",
}


class MessageRoute(BaseModel):
    category: RouteCategory
    reply: str | None = None


def build_router_reply(category: RouteCategory) -> str:
    if category == "GREETING":
        return (
            "Hello! I can help you complete the additional FAS questions. "
            "You can describe your circumstances or ask what to enter."
        )
    if category == "FORM_HELP":
        return (
            "I can explain what to enter for the configured questions. "
            "You can review every suggestion before applying it."
        )
    if category == "FAQ_REDIRECT":
        return (
            "That question is better handled by the FAQ assistant. "
            "I can help collect information for this FAS form."
        )
    if category == "OFF_TOPIC":
        return (
            "I can only help with completing the FAS form. "
            "Please ask about the form or provide information for the application."
        )
    return ""


def normalize_rule_message(message: str) -> str:
    normalized = re.sub(r"[^\w\s']+", " ", message.casefold())
    return " ".join(normalized.split())


def is_general_help_message(message: str) -> bool:
    return normalize_rule_message(message) in GENERAL_HELP_MESSAGES


def strip_leading_greeting(message: str) -> str:
    greeting_pattern = "|".join(
        re.escape(greeting)
        for greeting in sorted(GREETING_MESSAGES, key=len, reverse=True)
    )
    match = re.match(
        rf"^\s*(?:{greeting_pattern})\b[\s,!.;:-]*(?P<remainder>.+)$",
        message,
        flags=re.IGNORECASE,
    )
    if match is None:
        return message.strip()
    return match.group("remainder").strip()


def route_by_rules(message: str) -> MessageRoute | None:
    normalized = normalize_rule_message(message)
    if normalized in GREETING_MESSAGES:
        return MessageRoute(
            category="GREETING",
            reply=build_router_reply("GREETING"),
        )

    if normalized in GENERAL_HELP_MESSAGES:
        return MessageRoute(
            category="FORM_HELP",
            reply=build_router_reply("FORM_HELP"),
        )

    message_without_greeting = strip_leading_greeting(message)
    if message_without_greeting != message.strip():
        if is_general_help_message(message_without_greeting):
            return MessageRoute(
                category="FORM_HELP",
                reply=build_router_reply("FORM_HELP"),
            )
        return MessageRoute(category="FORM_FILLING")

    form_help_patterns = {
        "what type of information",
        "what information",
        "what should i put",
        "what should i write",
        "what do i put",
        "how do i fill",
        "how should i fill",
        "what does",
        "why do you need",
        "can i edit",
        "how does this autofill work",
    }
    if any(pattern in normalized for pattern in form_help_patterns):
        return MessageRoute(
            category="FORM_HELP",
            reply=build_router_reply("FORM_HELP"),
        )
    return None


def route_message(message: str) -> MessageRoute:
    rule_route = route_by_rules(message)
    if rule_route is not None:
        return rule_route

    try:
        response = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": MESSAGE_ROUTER_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": MESSAGE_ROUTER_USER_PROMPT.format(message=message),
                },
            ],
            max_completion_tokens=300,
        )
        content = response.choices[0].message.content or ""
        if content.strip().startswith("```"):
            content = (
                content.strip()
                .removeprefix("```json")
                .removeprefix("```JSON")
                .removeprefix("```")
                .removesuffix("```")
                .strip()
            )
        data = json.loads(content)
        category = data.get("category", "FORM_FILLING")
        if category in {
            "GREETING",
            "FORM_FILLING",
            "FORM_HELP",
            "FAQ_REDIRECT",
            "OFF_TOPIC",
        }:
            return MessageRoute(
                category=category,
                reply=build_router_reply(category),
            )
    except Exception as exc:
        print(f"Dynamic message routing error: {exc!r}")

    return MessageRoute(category="FORM_FILLING")
