import streamlit as st
import requests
import json
import time
from config import INTERNAL_API_KEY
 
API_BASE = "http://127.0.0.1:8001"
HEADERS = {"X-API-Key": INTERNAL_API_KEY}
 
st.set_page_config(page_title="SFS e-Service FAQ Assistant", page_icon="🎓")

# Inject custom CSS for Claude-like UI
import os
css_path = os.path.join(os.path.dirname(__file__), "style.css")
try:
    with open(css_path) as f:
        st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)
except FileNotFoundError:
    pass

# Custom HTML for User Message Bubble
def render_user_message(text):
    html = f"""
    <div class="msg-animate" style="display: flex; justify-content: flex-end; margin: 1.5rem 0;">
        <div style="background-color: #f3f4f6; color: #111827; border-radius: 20px; border-bottom-right-radius: 4px; padding: 1rem 1.5rem; max-width: 80%; box-shadow: 0 1px 2px rgba(0,0,0,0.05); font-family: 'Inter', sans-serif;">
            {text}
        </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)

st.title("🎓 SFS e-Service FAQ Assistant")
 
# ---------------------------------------------------------------------------
# Sidebar — document upload
# ---------------------------------------------------------------------------
 
with st.sidebar:
    st.header("👤 Test Role")
    role = st.selectbox("Current role", ["user", "admin"])
    st.header("📄 Upload Documents")
    
    # Định nghĩa hàm lấy stats ở đây để có thể clear() cache ngay khi upload xong
    @st.cache_data(ttl=60, show_spinner=False)
    def fetch_stats():
        res = requests.get(f"{API_BASE}/ai/documents/stats", headers=HEADERS, timeout=5)
        res.raise_for_status()
        return res.json()
        
    uploaded_file = st.file_uploader("Upload a PDF", type=["pdf"])
    admin_only = st.checkbox("Admin-only document")
 
    if uploaded_file:
        if st.button("Ingest Document"):
            with st.spinner("Ingesting..."):
                response = requests.post(
                    f"{API_BASE}/ai/documents/upload",
                    files={"file": (uploaded_file.name, uploaded_file.getvalue(), "application/pdf")},
                    data={"admin_only": str(admin_only).lower()},
                    headers=HEADERS,
                )
 
                if response.status_code == 200:
                    data = response.json()
 
                    if data.get("skipped"):
                        st.warning(f"⚠️ {data.get('message', data.get('reason', 'Document was skipped.'))}")
                    else:
                        st.success(f"✅ {data.get('message', 'Document ingested successfully.')}")
                        fetch_stats.clear() # Xoá cache ngay lập tức để dòng bên dưới tải số liệu mới
                else:
                    st.error(f"❌ Upload failed: {response.text}")
 
    st.divider()
    st.subheader("Knowledge Base")

    try:
        data = fetch_stats()
        st.metric("Total Documents", data["total_documents"])
        st.metric("Total Chunks", data["total_chunks"])
    except:
        st.caption("Could not connect to API or fetch stats")
 
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
    if msg["role"] == "user":
        render_user_message(msg["content"])
    else:
        with st.chat_message("assistant"):
            st.markdown(msg["content"])
 
# ---------------------------------------------------------------------------
# Chat input
# ---------------------------------------------------------------------------
 
if prompt := st.chat_input("Ask a question about the SFS e-Service portal..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    render_user_message(prompt)
    
    # Build history for API (last 10 messages)
    history = st.session_state.messages[-10:]
    history_payload = [
        {"role": m["role"], "content": m["content"]}
        for m in history[:-1]
    ]

    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        # Hiện con trỏ nhấp nháy TRONG KHI CHỜ phản hồi từ Backend
        message_placeholder.markdown('<span class="blinking-cursor">|</span>', unsafe_allow_html=True)
        
        # Bắt buộc Streamlit cập nhật DOM (chứa tin nhắn user) ngay lập tức
        time.sleep(0.1)
        
        try:
            # Gọi API lấy toàn bộ response về trước (không dùng stream=True nữa)
            response = requests.post(
                f"{API_BASE}/ai/faq/chat",
                json={
                    "message": prompt,
                    "history": history_payload,
                    "user_id": "streamlit-user",
                    "role": role,
                },
                headers=HEADERS
            )
            
            if response.status_code == 200:
                data = response.json()
                answer = data.get("answer", "")
                fallback = data.get("fallback", False)
                fallback_type = data.get("fallback_type")
                
                # Hàm Animation gõ text từ từ (Giới hạn tối đa 3 giây)
                import math
                full_response = ""
                
                # Công thức: Tốc độ chuẩn 0.02s/lần cập nhật. Tối đa 150 bước (3 giây).
                MAX_STEPS = 150
                BASE_DELAY = 0.02
                
                L = len(answer)
                chunk_size = max(1, math.ceil(L / MAX_STEPS))
                delay = BASE_DELAY
                
                for i in range(0, L, chunk_size):
                    full_response += answer[i:i+chunk_size]
                    message_placeholder.markdown(full_response + '<span class="blinking-cursor">|</span>', unsafe_allow_html=True)
                    time.sleep(delay)
                
                # Kết thúc animation, bỏ con trỏ
                message_placeholder.markdown(full_response)
                
                # Xử lý hiển thị fallback
                if fallback:
                    if fallback_type == "tier1":
                        st.caption("🚫 Off-topic question detected")
                    elif fallback_type == "tier2":
                        st.caption("⚠️ Answered with low confidence")
                        # Nếu API có trả về tier2_message riêng biệt thì hiển thị, còn không thì answer đã chứa rồi
                        tier2_msg = data.get("tier2_message")
                        if tier2_msg:
                            st.info(tier2_msg)
                            full_response += "\n\n" + tier2_msg
                        
                st.session_state.messages.append({"role": "assistant", "content": full_response})
            else:
                st.error("Sorry, something went wrong. (Server Error)")
                st.session_state.messages.append({"role": "assistant", "content": "Error connecting to backend."})
                
        except Exception as e:
            st.error(f"Could not connect to API: {e}")
            st.session_state.messages.append({"role": "assistant", "content": "Error connecting to backend."})