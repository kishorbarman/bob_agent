import os
import httpx
from datetime import datetime, timezone
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/sdm.service",
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


# --- Nest ---

NEST_PROJECT_ID = os.environ.get("NEST_PROJECT_ID", "")
SDM_BASE = "https://smartdevicemanagement.googleapis.com/v1"


def nest_get(path: str) -> dict:
    creds = get_credentials()
    response = httpx.get(
        f"{SDM_BASE}/enterprises/{NEST_PROJECT_ID}/{path}",
        headers={"Authorization": f"Bearer {creds.token}"},
        timeout=10
    )
    response.raise_for_status()
    return response.json()


def nest_post(path: str, body: dict) -> dict:
    creds = get_credentials()
    response = httpx.post(
        f"{SDM_BASE}/enterprises/{NEST_PROJECT_ID}/{path}",
        headers={"Authorization": f"Bearer {creds.token}"},
        json=body,
        timeout=10
    )
    response.raise_for_status()
    return response.json()


def get_nest_devices() -> str:
    data = nest_get("devices")
    devices = data.get("devices", [])
    if not devices:
        return "No Nest devices found."
    lines = []
    for d in devices:
        name = d.get("displayName") or d["name"].split("/")[-1]
        device_type = d.get("type", "").split(".")[-1].replace("_", " ").title()
        lines.append(f"• {name} ({device_type})")
    return "\n".join(lines)


def get_thermostat_status() -> str:
    data = nest_get("devices")
    devices = data.get("devices", [])
    thermostats = [d for d in devices if "THERMOSTAT" in d.get("type", "")]
    if not thermostats:
        return "No Nest thermostat found."

    lines = []
    for t in thermostats:
        traits = t.get("traits", {})
        name = t.get("displayName") or t["name"].split("/")[-1]

        temp = traits.get("sdm.devices.traits.Temperature", {})
        humidity = traits.get("sdm.devices.traits.Humidity", {})
        therm = traits.get("sdm.devices.traits.ThermostatMode", {})
        hvac = traits.get("sdm.devices.traits.ThermostatHvac", {})
        setpoint = traits.get("sdm.devices.traits.ThermostatTemperatureSetpoint", {})

        ambient = temp.get("ambientTemperatureCelsius", "N/A")
        hum = humidity.get("ambientHumidityPercent", "N/A")
        mode = therm.get("mode", "N/A")
        hvac_status = hvac.get("status", "N/A")
        heat_sp = setpoint.get("heatCelsius", "")
        cool_sp = setpoint.get("coolCelsius", "")

        line = (
            f"{name}\n"
            f"  Temperature: {ambient}°C | Humidity: {hum}%\n"
            f"  Mode: {mode} | HVAC: {hvac_status}"
        )
        if heat_sp:
            line += f"\n  Heat setpoint: {heat_sp}°C"
        if cool_sp:
            line += f"\n  Cool setpoint: {cool_sp}°C"
        lines.append(line)

    return "\n\n".join(lines)


def set_thermostat_temperature(temperature: float, unit: str = "celsius") -> str:
    data = nest_get("devices")
    devices = data.get("devices", [])
    thermostats = [d for d in devices if "THERMOSTAT" in d.get("type", "")]
    if not thermostats:
        return "No Nest thermostat found."

    thermostat = thermostats[0]
    device_id = thermostat["name"].split("/")[-1]

    if unit.lower() == "fahrenheit":
        temperature = (temperature - 32) * 5 / 9

    # Get current mode to determine which setpoint to use
    traits = thermostat.get("traits", {})
    mode = traits.get("sdm.devices.traits.ThermostatMode", {}).get("mode", "HEAT")

    if mode == "HEAT":
        body = {"command": "sdm.devices.commands.ThermostatTemperatureSetpoint.SetHeat",
                "params": {"heatCelsius": round(temperature, 1)}}
    elif mode == "COOL":
        body = {"command": "sdm.devices.commands.ThermostatTemperatureSetpoint.SetCool",
                "params": {"coolCelsius": round(temperature, 1)}}
    else:
        return f"Cannot set temperature while thermostat is in {mode} mode."

    nest_post(f"devices/{device_id}:executeCommand", body)
    return f"Thermostat set to {round(temperature, 1)}°C."


def get_camera_status() -> str:
    data = nest_get("devices")
    devices = data.get("devices", [])
    cameras = [d for d in devices if "CAMERA" in d.get("type", "") or "DOORBELL" in d.get("type", "")]
    if not cameras:
        return "No Nest cameras or doorbells found."

    lines = []
    for c in cameras:
        traits = c.get("traits", {})
        name = c.get("displayName") or c["name"].split("/")[-1]
        device_type = c.get("type", "").split(".")[-1].replace("_", " ").title()
        connectivity = traits.get("sdm.devices.traits.Connectivity", {}).get("status", "N/A")
        lines.append(f"• {name} ({device_type}) — {connectivity}")

    return "\n".join(lines)
