import asyncio
import io
import logging
import os
import subprocess
import tempfile
import httpx
from datetime import datetime, timezone

_gs_logger = logging.getLogger(__name__)
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
        name = (
            d.get("traits", {}).get("sdm.devices.traits.Info", {}).get("customName")
            or d.get("displayName")
            or d["name"].split("/")[-1]
        )
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
        name = t.get("traits", {}).get("sdm.devices.traits.Info", {}).get("customName") or t.get("displayName") or "Thermostat"

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


def _fix_nest_sdp(sdp: str) -> str:
    """Fix non-standard ICE candidate lines in Nest's answer SDP.

    Nest omits the foundation and uses an empty field with a leading space:
      a=candidate: 1 udp priority addr port typ type
    RFC 5245 standard requires a non-empty foundation:
      a=candidate:0 1 udp priority addr port typ type
    aiortc's parser splits on whitespace after stripping 'candidate:', so
    with an empty foundation bits[0]='1' (component) and bits[1]='udp' (protocol),
    causing int(bits[1]) to raise ValueError.
    """
    fixed = []
    for line in sdp.splitlines():
        if line.startswith("a=candidate:"):
            after_colon = line[len("a=candidate:"):]
            # Empty foundation: leading space means no foundation token
            if after_colon.startswith(" "):
                line = "a=candidate:0" + after_colon
        fixed.append(line)
    return "\r\n".join(fixed)


async def _webrtc_capture_frame(device_id):
    """Establish a WebRTC connection to the Nest camera and return one JPEG frame."""
    from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer

    _gs_logger.info("WebRTC: starting for device %s", device_id)

    pc = RTCPeerConnection(configuration=RTCConfiguration(
        iceServers=[RTCIceServer(urls=["stun:stun.l.google.com:19302"])]
    ))

    loop = asyncio.get_running_loop()
    track_future = loop.create_future()
    media_session_id = ""

    @pc.on("track")
    def on_track(track):
        _gs_logger.info("WebRTC: received track kind=%s", track.kind)
        if track.kind == "video" and not track_future.done():
            track_future.set_result(track)

    try:
        # Nest requires audio, video, and application m-lines in that exact order
        pc.addTransceiver("audio", direction="recvonly")
        pc.addTransceiver("video", direction="recvonly")
        pc.createDataChannel("dataSendChannel")
        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)

        sdp = pc.localDescription.sdp
        _gs_logger.info("WebRTC: SDP offer snippet: %s", sdp[:300].replace("\r\n", " | "))
        _gs_logger.info("WebRTC: sending SDP offer to Nest API")

        try:
            stream_data = await loop.run_in_executor(
                None,
                lambda: nest_post(
                    f"devices/{device_id}:executeCommand",
                    {
                        "command": "sdm.devices.commands.CameraLiveStream.GenerateWebRtcStream",
                        "params": {"offerSdp": sdp},
                    },
                ),
            )
        except Exception as exc:
            response_body = getattr(getattr(exc, "response", None), "text", "")
            _gs_logger.error("WebRTC: Nest API call failed: %s | body: %s", exc, response_body)
            return None, f"Failed to start WebRTC stream: {exc}"

        answer_sdp = stream_data.get("results", {}).get("answerSdp", "")
        media_session_id = stream_data.get("results", {}).get("mediaSessionId", "")
        _gs_logger.info("WebRTC: got answer SDP (len=%d), mediaSessionId=%s", len(answer_sdp), media_session_id)

        if not answer_sdp:
            return None, "Camera did not return a WebRTC answer SDP."

        answer_sdp = _fix_nest_sdp(answer_sdp)
        _gs_logger.info("WebRTC: setting remote description")
        await pc.setRemoteDescription(RTCSessionDescription(sdp=answer_sdp, type="answer"))
        _gs_logger.info("WebRTC: remote description set, waiting for video track")

        video_track = await asyncio.wait_for(track_future, timeout=15)
        _gs_logger.info("WebRTC: video track received, capturing frames")

        frame = None
        for i in range(5):
            frame = await asyncio.wait_for(video_track.recv(), timeout=8)
            _gs_logger.info("WebRTC: received frame %d", i + 1)

        img = frame.to_image()
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        image_bytes = buf.getvalue()
        _gs_logger.info("WebRTC: captured JPEG, size=%d bytes", len(image_bytes))
        return image_bytes, None

    except asyncio.TimeoutError:
        error = "Timed out waiting for doorbell video feed. The camera may be initialising or offline."
        _gs_logger.warning("WebRTC: %s", error)
        return None, error
    except Exception as exc:
        _gs_logger.error("WebRTC: capture error: %s", exc, exc_info=True)
        return None, f"WebRTC capture error: {exc}"
    finally:
        if media_session_id:
            try:
                await loop.run_in_executor(
                    None,
                    lambda: nest_post(
                        f"devices/{device_id}:executeCommand",
                        {
                            "command": "sdm.devices.commands.CameraLiveStream.StopWebRtcStream",
                            "params": {"mediaSessionId": media_session_id},
                        },
                    ),
                )
            except Exception:
                pass
        await pc.close()


def get_doorbell_snapshot():
    """Capture a JPEG snapshot from the doorbell camera.

    Supports both RTSP (older cameras) and WebRTC (newer Nest Doorbells).
    Returns (bytes, None) on success or (None, error_message) on failure.
    """
    data = nest_get("devices")
    devices = data.get("devices", [])
    doorbell = next(
        (d for d in devices if "DOORBELL" in d.get("type", "") or "doorbell" in d.get("displayName", "").lower()),
        None,
    )
    if not doorbell:
        return None, "No Nest doorbell found."

    traits = doorbell.get("traits", {})
    live_stream_trait = traits.get("sdm.devices.traits.CameraLiveStream", {})
    if not live_stream_trait:
        return None, "Doorbell does not support live streaming via the Device Access API."

    supported_protocols = live_stream_trait.get("supportedProtocols", [])
    device_id = doorbell["name"].split("/")[-1]

    if "RTSP" in supported_protocols:
        return _snapshot_via_rtsp(device_id)

    if "WEB_RTC" in supported_protocols:
        # asyncio.run() is safe here because get_doorbell_snapshot is always
        # called from a worker thread (via asyncio.to_thread), never from
        # the main async event loop.
        try:
            return asyncio.run(_webrtc_capture_frame(device_id))
        except Exception as exc:
            _gs_logger.error("WebRTC: asyncio.run failed: %s", exc, exc_info=True)
            return None, f"WebRTC snapshot failed: {exc}"

    return None, f"Unsupported streaming protocols: {supported_protocols}"


def _normalize_camera_label(value: str) -> str:
    return " ".join((value or "").lower().strip().split())


def _camera_display_name(device: dict) -> str:
    traits = device.get("traits", {})
    return (
        traits.get("sdm.devices.traits.Info", {}).get("customName")
        or device.get("displayName")
        or device.get("name", "").split("/")[-1]
    )


def _find_camera_device(devices: list[dict], camera_name: str = ""):
    cameras = [d for d in devices if "CAMERA" in d.get("type", "") or "DOORBELL" in d.get("type", "")]
    if not cameras:
        return None, "No Nest cameras or doorbells found."

    query = _normalize_camera_label(camera_name)
    if not query:
        return cameras[0], None

    scored = []
    for cam in cameras:
        label = _normalize_camera_label(_camera_display_name(cam))
        if label == query:
            return cam, None
        if query in label or label in query:
            scored.append(cam)

    if scored:
        return scored[0], None

    available = ", ".join(_camera_display_name(c) for c in cameras)
    return None, f"Camera '{camera_name}' not found. Available cameras: {available}"


def get_camera_snapshot(camera_name: str = ""):
    """Capture a JPEG snapshot from a named Nest camera (or first available camera)."""
    data = nest_get("devices")
    devices = data.get("devices", [])
    camera, error = _find_camera_device(devices, camera_name)
    if error:
        return None, error

    traits = camera.get("traits", {})
    live_stream_trait = traits.get("sdm.devices.traits.CameraLiveStream", {})
    if not live_stream_trait:
        label = _camera_display_name(camera)
        return None, f"{label} does not support live streaming via the Device Access API."

    supported_protocols = live_stream_trait.get("supportedProtocols", [])
    device_id = camera["name"].split("/")[-1]
    camera_label = _camera_display_name(camera)

    if "RTSP" in supported_protocols:
        image_bytes, snapshot_error = _snapshot_via_rtsp(device_id)
        if snapshot_error:
            return None, snapshot_error
        return image_bytes, None

    if "WEB_RTC" in supported_protocols:
        try:
            return asyncio.run(_webrtc_capture_frame(device_id))
        except Exception as exc:
            _gs_logger.error("WebRTC: asyncio.run failed: %s", exc, exc_info=True)
            return None, f"WebRTC snapshot failed for {camera_label}: {exc}"

    return None, f"Unsupported streaming protocols for {camera_label}: {supported_protocols}"


def _snapshot_via_rtsp(device_id):
    """Grab a single JPEG frame from an RTSP stream using ffmpeg."""
    try:
        stream_data = nest_post(
            f"devices/{device_id}:executeCommand",
            {"command": "sdm.devices.commands.CameraLiveStream.GenerateRtspStream", "params": {}},
        )
    except Exception as exc:
        return None, f"Failed to start RTSP stream: {exc}"

    rtsp_url = stream_data.get("results", {}).get("streamUrls", {}).get("rtspUrl")
    stream_extension_token = stream_data.get("results", {}).get("streamExtensionToken", "")
    if not rtsp_url:
        return None, "RTSP stream started but no URL was returned."

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        tmp_path = f.name

    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-rtsp_transport", "tcp", "-i", rtsp_url,
             "-vframes", "1", "-q:v", "2", tmp_path],
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode(errors="ignore")[-300:]
            _gs_logger.error("ffmpeg error: %s", stderr)
            return None, f"Failed to capture RTSP frame: {stderr}"
        with open(tmp_path, "rb") as f:
            return f.read(), None
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        try:
            nest_post(
                f"devices/{device_id}:executeCommand",
                {"command": "sdm.devices.commands.CameraLiveStream.StopRtspStream",
                 "params": {"streamExtensionToken": stream_extension_token}},
            )
        except Exception:
            pass


def get_camera_status() -> str:
    data = nest_get("devices")
    devices = data.get("devices", [])
    cameras = [d for d in devices if "CAMERA" in d.get("type", "") or "DOORBELL" in d.get("type", "")]
    if not cameras:
        return "No Nest cameras or doorbells found."

    lines = []
    for c in cameras:
        traits = c.get("traits", {})
        name = (
            traits.get("sdm.devices.traits.Info", {}).get("customName")
            or c.get("displayName")
            or c["name"].split("/")[-1]
        )
        device_type = c.get("type", "").split(".")[-1].replace("_", " ").title()
        connectivity = traits.get("sdm.devices.traits.Connectivity", {}).get("status", "N/A")
        lines.append(f"• {name} ({device_type}) — {connectivity}")

    return "\n".join(lines)
