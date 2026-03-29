import os
from datetime import datetime, timezone
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import base64
import email

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
]

CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.json"


def get_credentials() -> Credentials:
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return creds


# --- Calendar ---

def get_upcoming_events(max_results: int = 10) -> str:
    creds = get_credentials()
    service = build("calendar", "v3", credentials=creds)

    now = datetime.now(timezone.utc).isoformat()
    result = service.events().list(
        calendarId="primary",
        timeMin=now,
        maxResults=max_results,
        singleEvents=True,
        orderBy="startTime"
    ).execute()

    events = result.get("items", [])
    if not events:
        return "No upcoming events found."

    lines = []
    for event in events:
        start = event["start"].get("dateTime", event["start"].get("date", ""))
        # Format datetime nicely
        try:
            dt = datetime.fromisoformat(start)
            start = dt.strftime("%a %d %b %Y, %H:%M")
        except ValueError:
            pass
        title = event.get("summary", "(No title)")
        location = event.get("location", "")
        line = f"• {start} — {title}"
        if location:
            line += f" @ {location}"
        lines.append(line)

    return "\n".join(lines)


def search_calendar_events(query: str, max_results: int = 5) -> str:
    creds = get_credentials()
    service = build("calendar", "v3", credentials=creds)

    result = service.events().list(
        calendarId="primary",
        q=query,
        maxResults=max_results,
        singleEvents=True,
        orderBy="startTime"
    ).execute()

    events = result.get("items", [])
    if not events:
        return f"No calendar events found matching '{query}'."

    lines = []
    for event in events:
        start = event["start"].get("dateTime", event["start"].get("date", ""))
        try:
            dt = datetime.fromisoformat(start)
            start = dt.strftime("%a %d %b %Y, %H:%M")
        except ValueError:
            pass
        title = event.get("summary", "(No title)")
        lines.append(f"• {start} — {title}")

    return "\n".join(lines)


# --- Gmail ---

def get_recent_emails(max_results: int = 5, query: str = "") -> str:
    creds = get_credentials()
    service = build("gmail", "v1", credentials=creds)

    params = {"userId": "me", "maxResults": max_results, "labelIds": ["INBOX"]}
    if query:
        params["q"] = query

    result = service.users().messages().list(**params).execute()
    messages = result.get("messages", [])

    if not messages:
        return "No emails found."

    lines = []
    for msg in messages:
        msg_data = service.users().messages().get(
            userId="me", id=msg["id"], format="metadata",
            metadataHeaders=["From", "Subject", "Date"]
        ).execute()

        headers = {h["name"]: h["value"] for h in msg_data["payload"]["headers"]}
        subject = headers.get("Subject", "(No subject)")
        sender = headers.get("From", "Unknown")
        date = headers.get("Date", "")

        # Trim long sender strings
        if "<" in sender:
            name = sender.split("<")[0].strip().strip('"')
            sender = name if name else sender

        lines.append(f"• {date[:16]} | {sender[:30]} | {subject}")

    return "\n".join(lines)


def search_emails(query: str, max_results: int = 5) -> str:
    return get_recent_emails(max_results=max_results, query=query)
