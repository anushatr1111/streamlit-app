# === main.py (FastAPI backend) ===

from fastapi import FastAPI, Request, Body, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from datetime import datetime, timedelta
from pydantic import BaseModel
import os
import json
import uuid
import dateparser
import re
from typing import Optional

from calendar_service import CalendarService

app = FastAPI(title="Google Calendar Booking API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SCOPES = ['https://www.googleapis.com/auth/calendar']
CLIENT_SECRET_FILE = 'credentials.json'
REDIRECT_URI = 'http://localhost:8000/oauth2callback'

user_tokens = {}
chat_sessions = {}

@app.get("/")
async def home():
    return {"message": "Welcome to the Google Calendar Booking API"}

@app.get("/auth")
async def authorize():
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRET_FILE,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    state = str(uuid.uuid4())
    auth_url, _ = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        state=state
    )
    return RedirectResponse(auth_url)

@app.get("/oauth2callback")
async def oauth2callback(request: Request):
    state = request.query_params.get("state")
    code = request.query_params.get("code")

    flow = Flow.from_client_secrets_file(
        CLIENT_SECRET_FILE,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    flow.fetch_token(code=code)

    creds = flow.credentials
    user_tokens[state] = creds.to_json()

    streamlit_url = f"http://localhost:8501/?user_id={state}"
    return RedirectResponse(streamlit_url)

@app.post("/link_session")
async def link_session(request: dict):
    """Link a chat session with an authenticated user"""
    session_id = request.get("session_id")
    user_id = request.get("user_id")
    
    if user_id in user_tokens:
        # Copy the user's credentials to the session_id
        user_tokens[session_id] = user_tokens[user_id]
        print(f"[DEBUG] Linked session {session_id} with user {user_id}")
        return {"success": True, "message": "Session linked successfully"}
    else:
        return {"success": False, "message": "User not authenticated"}

@app.get("/auth_status")
async def auth_status(session_id: str = None):
    """Check if a session is authenticated"""
    if session_id and session_id in user_tokens:
        return {"authenticated": True, "session_id": session_id}
    
    # Check if any user is authenticated
    if user_tokens:
        return {"authenticated": True, "available_users": list(user_tokens.keys())}
    
    return {"authenticated": False}
    if user_id not in user_tokens:
        return {"error": "User not authorized. Go to /auth to connect."}

    creds = Credentials.from_authorized_user_info(
        json.loads(user_tokens[user_id]), scopes=SCOPES)
    service = build('calendar', 'v3', credentials=creds)

    events_result = service.events().list(
        calendarId='primary',
        maxResults=5,
        singleEvents=True,
        orderBy='startTime'
    ).execute()

    events = events_result.get('items', [])
    return {"events": events}

class BookingRequest(BaseModel):
    user_id: str
    title: str
    date: str
    start_time: str
    duration_minutes: int = 60
    description: str = ""

@app.post("/calendar/book")
async def book_event(data: BookingRequest):
    if data.user_id not in user_tokens:
        return {"error": "User not authorized."}

    creds = Credentials.from_authorized_user_info(
        json.loads(user_tokens[data.user_id]), scopes=SCOPES)
    calendar_service = CalendarService(creds)

    result = await calendar_service.book_appointment(
        date=data.date,
        start_time=data.start_time,
        duration_minutes=data.duration_minutes,
        title=data.title,
        description=data.description
    )
    return result

def parse_datetime_from_message(message: str) -> Optional[datetime]:
    """Enhanced datetime parsing function with manual parsing as primary method"""
    try:
        print(f"[DEBUG] Original message: '{message}'")
        
        # First try: Simple dateparser with original message
        try:
            parsed_datetime = dateparser.parse(message, settings={'DATE_ORDER': 'MDY'})
            if parsed_datetime:
                print(f"[DEBUG] Dateparser success with original: {parsed_datetime}")
                return parsed_datetime
        except:
            pass
        
        # Second try: Manual parsing with regex patterns
        patterns = [
            # "next friday at 3 pm"
            r'next\s+(\w+day)\s+at\s+(\d{1,2})\s*(am|pm|AM|PM)',
            # "friday at 3 pm" 
            r'(\w+day)\s+at\s+(\d{1,2})\s*(am|pm|AM|PM)',
            # "next friday 3 pm"
            r'next\s+(\w+day)\s+(\d{1,2})\s*(am|pm|AM|PM)',
            # "friday 3 pm"
            r'(\w+day)\s+(\d{1,2})\s*(am|pm|AM|PM)',
            # "tomorrow at 3 pm"
            r'(tomorrow)\s+at\s+(\d{1,2})\s*(am|pm|AM|PM)',
            # "tomorrow 3 pm"
            r'(tomorrow)\s+(\d{1,2})\s*(am|pm|AM|PM)',
        ]
        
        for i, pattern in enumerate(patterns):
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                groups = match.groups()
                print(f"[DEBUG] Pattern {i+1} matched: {groups}")
                
                if len(groups) >= 3:
                    day_part = groups[0].lower()
                    hour = int(groups[1])
                    ampm = groups[2].upper()
                    
                    print(f"[DEBUG] Extracted - Day: {day_part}, Hour: {hour}, AM/PM: {ampm}")
                    
                    # Convert to 24-hour format
                    if ampm == 'PM' and hour != 12:
                        hour += 12
                    elif ampm == 'AM' and hour == 12:
                        hour = 0
                    
                    # Calculate the target date
                    now = datetime.now()
                    target_date = None
                    
                    if day_part == 'tomorrow':
                        target_date = now + timedelta(days=1)
                    else:
                        # Handle weekday names
                        weekdays = {
                            'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
                            'friday': 4, 'saturday': 5, 'sunday': 6
                        }
                        
                        if day_part in weekdays:
                            target_weekday = weekdays[day_part]
                            current_weekday = now.weekday()
                            
                            # Calculate days until target weekday
                            days_ahead = target_weekday - current_weekday
                            if days_ahead <= 0:  # Target day already happened this week
                                days_ahead += 7
                            
                            target_date = now + timedelta(days=days_ahead)
                    
                    if target_date:
                        # Combine date and time
                        result = target_date.replace(hour=hour, minute=0, second=0, microsecond=0)
                        print(f"[DEBUG] Manual parsing result: {result}")
                        return result
        
        # Third try: Clean message and use dateparser
        cleaned = re.sub(r'\b(book|schedule|meeting|appointment|call|session)\b', '', message, flags=re.IGNORECASE)
        cleaned = cleaned.strip()
        
        if cleaned != message:
            print(f"[DEBUG] Trying cleaned message: '{cleaned}'")
            try:
                parsed_datetime = dateparser.parse(cleaned, settings={'DATE_ORDER': 'MDY'})
                if parsed_datetime:
                    print(f"[DEBUG] Dateparser success with cleaned: {parsed_datetime}")
                    return parsed_datetime
            except:
                pass
        
        print("[DEBUG] All parsing attempts failed")
        return None
        
    except Exception as e:
        print(f"[DEBUG] Error in parse_datetime_from_message: {e}")
        import traceback
        traceback.print_exc()
        return None

class ChatMessage(BaseModel):
    message: str
    session_id: str

class ChatResponse(BaseModel):
    response: str
    session_id: str
    suggestions: list = []
    booking_confirmed: bool = False

@app.post("/chat", response_model=ChatResponse)
async def chat(chat_message: ChatMessage):
    try:
        session_id = chat_message.session_id
        message = chat_message.message.lower()

        print("[DEBUG] Received message:", message)

        if session_id not in chat_sessions:
            chat_sessions[session_id] = {
                "history": [],
                "booking_pending": None,
                "booking_confirmed": False
            }

        session = chat_sessions[session_id]
        print("[DEBUG] Current session:", session)

        if "book" in message or "schedule" in message:
            # Use the enhanced parsing function
            parsed_datetime = parse_datetime_from_message(message)
            print("[DEBUG] Parsed datetime:", parsed_datetime)

            if parsed_datetime:
                date_str = parsed_datetime.strftime("%Y-%m-%d")
                time_str = parsed_datetime.strftime("%H:%M")
                
                # Extract meeting title if possible
                title = "Meeting"
                if "meeting" in message:
                    title = "Meeting"
                elif "call" in message:
                    title = "Call"
                elif "appointment" in message:
                    title = "Appointment"
                
                session["booking_pending"] = {
                    "title": title,
                    "date": date_str,
                    "start_time": time_str,
                    "duration_minutes": 45,
                    "description": "Scheduled via AI assistant"
                }
                
                # Format the confirmation message nicely
                formatted_date = parsed_datetime.strftime("%A, %B %d, %Y")
                formatted_time = parsed_datetime.strftime("%I:%M %p")
                
                return ChatResponse(
                    response=f"📅 Should I confirm the {title.lower()} for {formatted_date} at {formatted_time}?",
                    session_id=session_id,
                    suggestions=["Yes, confirm it", "No, cancel", "Change time"],
                    booking_confirmed=False
                )
            else:
                return ChatResponse(
                    response="🕒 I couldn't understand the date/time. Try phrases like:\n• 'Book meeting next Friday at 3 PM'\n• 'Schedule call Tuesday at 11 AM'\n• 'Meeting tomorrow at 2 PM'",
                    session_id=session_id,
                    suggestions=["Next Monday 2 PM", "Tomorrow 10 AM", "Friday 3 PM"]
                )

        if (message in ["yes", "confirm", "yes, confirm it"] or "yes" in message) and session.get("booking_pending"):
            booking = session["booking_pending"]
            print("[DEBUG] Confirming booking:", booking)
            print(f"[DEBUG] Session ID: {session_id}")
            print(f"[DEBUG] Available user tokens: {list(user_tokens.keys())}")

            # Check if user is authenticated - try session_id first, then check all tokens
            user_creds = None
            user_key = None
            
            if session_id in user_tokens:
                user_creds = user_tokens[session_id]
                user_key = session_id
                print(f"[DEBUG] Found credentials for session_id: {session_id}")
            else:
                # If session_id doesn't match, try to find any valid user token
                # This handles the case where user authenticated but session_id changed
                if user_tokens:
                    user_key = list(user_tokens.keys())[-1]  # Use the most recent authentication
                    user_creds = user_tokens[user_key]
                    print(f"[DEBUG] Using most recent authentication: {user_key}")
                else:
                    print("[DEBUG] No user tokens available")

            if not user_creds:
                return ChatResponse(
                    response="❌ You need to authenticate first. Please go to /auth to connect your Google Calendar.",
                    session_id=session_id,
                    suggestions=["Go to /auth"]
                )

            try:
                creds = Credentials.from_authorized_user_info(json.loads(user_creds), scopes=SCOPES)
                calendar_service = CalendarService(creds)
                result = await calendar_service.book_appointment(**booking)

                # Clear the pending booking
                session["booking_pending"] = None
                session["booking_confirmed"] = True
                
                return ChatResponse(
                    response=f"✅ {booking['title']} confirmed for {booking['date']} at {booking['start_time']}!\n\n[View in Google Calendar]({result.get('calendar_link', '')})",
                    session_id=session_id,
                    booking_confirmed=True,
                    suggestions=["Book another meeting", "Show my calendar"]
                )
            except Exception as e:
                print(f"[DEBUG] Booking error: {e}")
                return ChatResponse(
                    response=f"❌ Sorry, there was an error booking your appointment: {str(e)}",
                    session_id=session_id,
                    suggestions=["Try again", "Check calendar"]
                )

        if message in ["no", "cancel", "no, cancel"] and session.get("booking_pending"):
            session["booking_pending"] = None
            return ChatResponse(
                response="❌ Booking cancelled. Let me know if you'd like to schedule something else!",
                session_id=session_id,
                suggestions=["Book a meeting", "Show my calendar"]
            )

        # Default response
        return ChatResponse(
            response="👋 I'm here to help you book appointments! Just tell me when you'd like to schedule something.\n\nExamples:\n• 'Book meeting next Friday at 3 PM'\n• 'Schedule call Tuesday at 11 AM'",
            session_id=session_id,
            suggestions=["Book a meeting", "Show my calendar", "Next Monday 2 PM"]
        )
        
    except Exception as e:
        print(f"[ERROR] Exception in chat endpoint: {e}")
        import traceback
        traceback.print_exc()
        return ChatResponse(
            response="❌ Sorry, something went wrong. Please try again.",
            session_id=chat_message.session_id,
            suggestions=["Try again"]
        )