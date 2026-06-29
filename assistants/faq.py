from config import client, CHAT_MODEL, SUPPORT_CONTACT
from models import FAQRequest, FAQResponse
from retrieval_sql import retrieve
from prompts import INTENT_PROMPT, FAQ_SYSTEM_PROMPT, FAQ_NO_CONTEXT_NOTE, FAQ_TIER1_RESPONSE, FAQ_TIER2_RESPONSE

# --- Intent detection ---
def detect_intent(message: str, history: list = []) -> str:
    """Returns 'PORTAL', 'OFF_TOPIC', or 'GREETING'. Defaults to OFF_TOPIC if unexpected output."""
    context = ""
    if history:
        last_turns = history[-4:]
        context = "Recent conversation:\n" + "\n".join(f"{t.role}: {t.content}" for t in last_turns)
    prompt = INTENT_PROMPT.format(message=message, context=context)

    response = client.chat.completions.create(
        model = CHAT_MODEL,
        messages = [{"role": "user", "content": prompt}],
        max_completion_tokens=200,
    )
    if hasattr(response,"usage") and response.usage:
        print(
            f"[intent tokens] "
            f"prompt={response.usage.prompt_tokens} "
            f"completion={response.usage.completion_tokens}"
            f"total={response.usage.total_tokens} "
        )
    
    raw = response.choices[0].message.content.strip().upper()
    print(f"[intent raw] {repr(raw)}")

    if raw in ("PORTAL", "OFF_TOPIC", "GREETING"):
        return raw
    
    print(f"[intent] Unexpected output '{raw}', defaulting to OFF_TOPIC")
    return "OFF_TOPIC"

# --- Get last message from assistant
def get_last_assistant_message(history:list) -> str | None:
    for turn in reversed(history):
        if turn.role == "assistant":
            return turn.content
    return None

# --- Build context query ---
def build_contextual_query(message:str, history: list) -> str:
    last_assistant = get_last_assistant_message(history)

    if not last_assistant:
        return message
    
    return f"""
    Previous assistant answer:
    {last_assistant}

    Current user question:
    {message}
    """.strip()

# --- Confidence check ---
UNCERTAINTY_PHRASES = (
    "i don't know",
    "i'm not sure",
    "i cannot find",
    "i do not have",
    "no information",
    "unable to answer",
    "cannot answer",
    "not in my knowledge",
)

def seems_uncertain(answer: str) -> bool:
    lower = answer.lower()
    return any(phrase in lower for phrase in UNCERTAINTY_PHRASES)

# --- Main handler ---
def handle_faq(req: FAQRequest) -> FAQResponse:
    # 1. Intent detection
    intent = detect_intent(req.message, req.history)
    print(f"[debug] Intent detected: {intent}")

    if intent == "OFF_TOPIC":
        return FAQResponse(
            answer=FAQ_TIER1_RESPONSE,
            fallback=True,
            fallback_type="tier1",
            support_contact=None,
        )
    
    if intent == "GREETING":
        return FAQResponse(
            answer="Hello! How can I assist you with the SFS e-Service portal today?",
            fallback=False,
            fallback_type=None,
            support_contact=None,
        )
    
    # 2. Retrieve relevant chunks
    retrieval_query = build_contextual_query(req.message, req.history)

    print(f"[debug] Retrieval query: {retrieval_query}")

    chunks = retrieve(retrieval_query)

    print(f"[debug] Retrieved {len(chunks)} chunks for contextual query")
    for i,c in enumerate(chunks):
        print(f"[debug] Chunk {i}: {c[:100]}")
    context = "\n\n---\n\n".join(chunks) if chunks else FAQ_NO_CONTEXT_NOTE

    # 3. Build messages
    messages = [{"role": "system", "content": FAQ_SYSTEM_PROMPT.format(context=context)}]

    for turn in req.history[-4:]:
        messages.append({"role": turn.role, "content": turn.content})

    messages.append({"role": "user", "content": req.message})

    # 4. LLM call
    response = client.chat.completions.create(
        model = CHAT_MODEL,
        messages=messages,
        max_completion_tokens=1500,
    )
    if hasattr(response, "usage") and response.usage:
        print(
            f"[tokens] "
            f"prompt={response.usage.prompt_tokens} "
            f"completion={response.usage.completion_tokens} "
            f"total={response.usage.total_tokens}"
        )
    answer = response.choices[0].message.content.strip()
    print(f"[debug] Raw LLM answer: {answer}")
    print(f"[debug] seems_uncertain: {seems_uncertain(answer)}")
    print(f"[debug] chunks found: {bool(chunks)}")

    # 5. Tier 2 fallback
    if seems_uncertain(answer) or not chunks:
        return FAQResponse(
            answer=FAQ_TIER2_RESPONSE.format(support_contact=SUPPORT_CONTACT),
            fallback=True,
            fallback_type="tier2",
            support_contact=SUPPORT_CONTACT,
        )

    return FAQResponse(
        answer=answer,
        fallback=False,
        fallback_type=None,
        support_contact=None,
    )