import json
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
    
    if raw in ("PORTAL", "OFF_TOPIC", "GREETING", "ACCOUNT_INFO"):
        return raw
    
    print(f"[intent] Unexpected output '{raw}', defaulting to OFF_TOPIC")
    return "OFF_TOPIC"

# --- Build retrieval query from recent user messages only ---
def build_retrieval_query(message: str, history: list) -> str:
    recent_user_messages = [
        turn.content.strip()
        for turn in history[-4:]
        if turn.role == "user" and turn.content.strip()
    ]

    retrieval_parts = recent_user_messages + [message.strip()]
    return " ".join(retrieval_parts)

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
            answer="Hello! How can I assist you with the MOE e-Service portal today?",
            fallback=False,
            fallback_type=None,
            support_contact=None,
        )
    
    if intent == "ACCOUNT_INFO":
        return FAQResponse(
            answer=(
                "I can't access or disclose personal account information or sensitive personal data, "
                "whether about you or another person. If you're trying to view your own MOE e-Service "
                "records, please sign in to the MOE e-Service portal. For someone else's information, "
                "please contact the appropriate person or organisation directly."
            ),
            fallback=True,
            fallback_type="account_info",
            support_contact=None,
        )
    
    # 2. Retrieve relevant chunks
    retrieval_query = build_retrieval_query(req.message, req.history)

    print(f"[debug] User role: {req.role}")

    print(f"[debug] Retrieval query: {retrieval_query}")

    chunks = retrieve(retrieval_query, req.role)

    
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

# --- Stream handler ---
def stream_faq(req: FAQRequest):
    # Trả về ngay 1 chunk rỗng để mở stream lập tức, giúp Frontend không bị block và hiện tin nhắn user ngay
    yield json.dumps({"type": "chunk", "text": ""}) + "\n"

    # 1. Intent detection
    intent = detect_intent(req.message, req.history)
    print(f"[debug-stream] Intent detected: {intent}")

    if intent == "OFF_TOPIC":
        yield json.dumps({"type": "chunk", "text": FAQ_TIER1_RESPONSE}) + "\n"
        yield json.dumps({"type": "done", "fallback": True, "fallback_type": "tier1", "support_contact": None}) + "\n"
        return
    
    if intent == "GREETING":
        yield json.dumps({"type": "chunk", "text": "Hello! How can I assist you with the MOE e-Service portal today?"}) + "\n"
        yield json.dumps({"type": "done", "fallback": False, "fallback_type": None, "support_contact": None}) + "\n"
        return
    
    # 2. Retrieve relevant chunks
    retrieval_query = build_retrieval_query(req.message, req.history)
    chunks = retrieve(retrieval_query)
    context = "\n\n---\n\n".join(chunks) if chunks else FAQ_NO_CONTEXT_NOTE

    # 3. Build messages
    messages = [{"role": "system", "content": FAQ_SYSTEM_PROMPT.format(context=context)}]
    for turn in req.history[-4:]:
        messages.append({"role": turn.role, "content": turn.content})
    messages.append({"role": "user", "content": req.message})

    # 4. LLM call with streaming
    response_stream = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=messages,
        max_completion_tokens=1500,
        stream=True
    )

    full_answer = ""
    for chunk in response_stream:
        if chunk.choices and len(chunk.choices) > 0:
            delta = chunk.choices[0].delta.content
            if delta:
                full_answer += delta
                yield json.dumps({"type": "chunk", "text": delta}) + "\n"

    # 5. Tier 2 fallback post-check
    if seems_uncertain(full_answer) or not chunks:
        yield json.dumps({
            "type": "done",
            "fallback": True,
            "fallback_type": "tier2",
            "support_contact": SUPPORT_CONTACT,
            "tier2_message": FAQ_TIER2_RESPONSE.format(support_contact=SUPPORT_CONTACT)
        }) + "\n"
    else:
        yield json.dumps({"type": "done", "fallback": False, "fallback_type": None, "support_contact": None}) + "\n"