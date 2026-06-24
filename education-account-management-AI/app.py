import streamlit as st
import requests
from config import INTERNAL_API_KEY
 
API_BASE = "http://localhost:8000"
HEADERS = {"X-API-Key": INTERNAL_API_KEY}
 
st.set_page_config(page_title="MOE e-Service FAQ Assistant", page_icon="🎓")
st.title("🎓 MOE e-Service FAQ Assistant")
 
# ---------------------------------------------------------------------------
# Sidebar — document upload
# ---------------------------------------------------------------------------
 
with st.sidebar:
    st.header("📄 Upload Documents")
    uploaded_file = st.file_uploader("Upload a PDF", type=["pdf"])
 
    if uploaded_file:
        if st.button("Ingest Document"):
            with st.spinner("Ingesting..."):
                response = requests.post(
                    f"{API_BASE}/ai/documents/upload",
                    files={"file": (uploaded_file.name, uploaded_file.getvalue(), "application/pdf")},
                    headers=HEADERS,
                )
 
                if response.status_code == 200:
                    data = response.json()
 
                    if data.get("skipped"):
                        st.warning(f"⚠️ {data.get('message', data.get('reason', 'Document was skipped.'))}")
                    else:
                        st.success(f"✅ {data.get('message', 'Document ingested successfully.')}")
                else:
                    st.error(f"❌ Upload failed: {response.text}")
 
    st.divider()
    st.subheader("Knowledge Base")
    try:
        stats = requests.get(f"{API_BASE}/ai/documents/stats", headers=HEADERS)
        if stats.status_code == 200:
            data = stats.json()
            st.metric("Total Documents", data["total_documents"])
            st.metric("Total Chunks", data["total_chunks"])
        else:
            st.caption("Could not fetch stats")
    except:
        st.caption("Could not connect to API")
 
    st.divider()
    if st.button("🗑️ Clear Chat"):
        st.session_state.messages = []
        st.rerun()
 
# ---------------------------------------------------------------------------
# Chat history
# ---------------------------------------------------------------------------
 
if "messages" not in st.session_state:
    st.session_state.messages = []
 
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
 
# ---------------------------------------------------------------------------
# Chat input
# ---------------------------------------------------------------------------
 
if prompt := st.chat_input("Ask a question about the MOE e-Service portal..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
 
    # Build history for API (last 10 messages)
    history = st.session_state.messages[-10:]
    history_payload = [
        {"role": m["role"], "content": m["content"]}
        for m in history[:-1]  # exclude current message
    ]

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            response = requests.post(
                f"{API_BASE}/ai/faq/chat",
                json={
                    "message": prompt,
                    "history": history_payload,
                    "user_id": "streamlit-user",
                },
                headers=HEADERS,
            )
 
        if response.status_code == 200:
            data = response.json()
            answer = data["answer"]
 
            st.markdown(answer)
 
            # Show fallback badge if applicable
            if data["fallback"]:
                fallback_type = data["fallback_type"]
                if fallback_type == "tier1":
                    st.caption("🚫 Off-topic question detected")
                elif fallback_type == "tier2":
                    st.caption("⚠️ Answered with low confidence")
        else:
            answer = "Sorry, something went wrong. Please try again."
            st.error(answer)
 
    st.session_state.messages.append({"role": "assistant", "content": answer})