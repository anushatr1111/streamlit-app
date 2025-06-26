# === streamlit_app.py ===

import streamlit as st
import requests
import json
from datetime import datetime
import uuid
from urllib.parse import urlparse, parse_qs

# === PAGE CONFIG ===
st.set_page_config(
    page_title="AI Appointment Booking Assistant",
    page_icon="📅",
    layout="wide"
)

# === API CONFIG ===
API_BASE_URL = "http://localhost:8000"

# === SESSION STATE INIT ===
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())

if "messages" not in st.session_state:
    st.session_state.messages = [{
        "role": "assistant",
        "content": "👋 Hello! I'm your AI appointment assistant. I can check availability, book meetings, and show your calendar. How can I help today?"
    }]

if "booking_confirmed" not in st.session_state:
    st.session_state.booking_confirmed = False

# Initialize user_id safely
if "user_id" not in st.session_state:
    st.session_state.user_id = None
    query_params = st.experimental_get_query_params()
    if "user_id" in query_params:
        st.session_state.user_id = query_params["user_id"][0]

# === FUNCTIONS ===
def send_message(message: str):
    try:
        response = requests.post(
            f"{API_BASE_URL}/chat",
            json={"message": message, "session_id": st.session_state.session_id},
            timeout=30
        )
        return response.json() if response.status_code == 200 else None
    except Exception as e:
        st.error(f"❌ Error: {str(e)}")
        return None

def fetch_events(user_id: str):
    try:
        res = requests.get(f"{API_BASE_URL}/calendar/events", params={"user_id": user_id})
        return res.json().get("events", []) if res.status_code == 200 else []
    except Exception as e:
        st.error(f"Failed to fetch events: {str(e)}")
        return []

# === UI SECTIONS ===

st.title("📅 AI Appointment Booking Assistant")

## --- 1. LOGIN AREA ---
with st.expander("🔐 Login with Google", expanded=(not bool(st.session_state.user_id))):
    if not st.session_state.user_id:
        st.markdown("Click below to connect your Google Calendar:")
        st.link_button("🔗 Connect Google Calendar", f"{API_BASE_URL}/auth")

## --- 2. UPCOMING EVENTS ---
if st.session_state.user_id:
    st.subheader("📆 Your Upcoming Events")
    events = fetch_events(st.session_state.user_id)

    if events:
        for event in events:
            start = event["start"].get("dateTime", event["start"].get("date"))
            end = event["end"].get("dateTime", event["end"].get("date"))
            st.markdown(f"""
                **🗓️ {event.get('summary', 'No Title')}**
                - ⏰ Start: `{start}`
                - 🛑 End: `{end}`
                - 📄 Description: {event.get('description', 'N/A')}
                ---
            """)
    else:
        st.info("No upcoming events found.")

## --- 3. CHAT SECTION ---
    st.divider()
    st.subheader("💬 Talk to the Assistant")

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    user_input = st.chat_input("Type your message here...")

    if user_input:
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        response_data = send_message(user_input)

        if response_data:
            assistant_msg = response_data.get("response", "I didn't understand that.")
            st.session_state.messages.append({"role": "assistant", "content": assistant_msg})
            with st.chat_message("assistant"):
                st.markdown(assistant_msg)

            if response_data.get("booking_confirmed"):
                st.success("✅ Appointment booked!")

## --- 4. RESET BUTTON ---
st.divider()
if st.button("🔁 Reset Session"):
    try:
        requests.delete(f"{API_BASE_URL}/session/{st.session_state.session_id}")
    except:
        pass
    st.session_state.clear()
    st.experimental_rerun()