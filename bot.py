import asyncio
import logging
import math
import os
import random
import time
import re
import tempfile
from contextlib import asynccontextmanager, suppress
from functools import wraps
from pathlib import Path
from typing import Optional

import httpx
import wikipedia
from google import genai
from google.genai import types
from ddgs import DDGS
from pypdf import PdfReader
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from google_services import (
    get_camera_snapshot,
    get_camera_status,
    get_doorbell_snapshot,
    get_nest_devices,
    get_recent_emails,
    get_thermostat_status,
    get_upcoming_events,
    search_calendar_events,
    search_emails,
    set_thermostat_temperature,
    set_thermostat_mode,
)
from preferences import (
    get_user_preferences,
    set_language,
    set_selected_model,
    set_response_style,
    set_timezone,
)
from media_utils import detect_document_type
from storage import (
    clear_pending_transcription,
    get_latest_artifact,
    list_known_user_ids,
    get_pending_transcription,
    init_storage,
    is_duplicate_callback,
    save_artifact,
    save_pending_transcription,
)
from telegram_ui import (
    artifact_actions_keyboard,
    model_keyboard,
    parse_callback_data,
    prefs_keyboard,
    render_card,
    style_keyboard,
    tools_category_keyboard,
    tools_keyboard,
    voice_preview_keyboard,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

gemini_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
DEFAULT_MODEL = "models/gemini-3.1-flash-lite-preview"
MODEL_CHOICES = {
    "models/gemini-3.1-flash-lite-preview": "Gemini 3.1 Flash-Lite Preview",
    "models/gemini-3.1-pro-preview": "Gemini 3.1 Pro Preview",
}

# Per-user conversation history
conversations: dict[int, list[dict]] = {}

# Snapshot paths waiting to be sent; populated by the doorbell snapshot tool
_snapshot_queue: dict[int, str] = {}

SYSTEM_PROMPT = (
    "You are a helpful personal assistant called Bob. Be concise and direct. "
    "Use tools whenever they will give a better answer than your training data alone. "
    "If the user asks to see a camera view, call the camera snapshot tool instead of apologizing. "
    "If the user asks to turn the thermostat off or change HVAC mode, call thermostat mode tools."
)


async def _chat_action_pulse(bot, chat_id: int, action: str = ChatAction.TYPING):
    while True:
        try:
            await bot.send_chat_action(chat_id=chat_id, action=action)
        except Exception:
            logger.debug("Failed to send chat action", exc_info=True)
        await asyncio.sleep(4)


@asynccontextmanager
async def processing_indicator(
    bot,
    chat_id: int,
    action: str = ChatAction.TYPING,
    status_text: str = "Bob is working on it...",
):
    task = asyncio.create_task(_chat_action_pulse(bot, chat_id, action))
    status_holder = {"message": None}

    async def _send_delayed_status():
        await asyncio.sleep(1.0)
        try:
            status_holder["message"] = await bot.send_message(chat_id=chat_id, text=status_text)
        except Exception:
            logger.debug("Failed to send status message", exc_info=True)

    status_task = asyncio.create_task(_send_delayed_status()) if status_text else None
    try:
        yield
    finally:
        if status_task:
            status_task.cancel()
            with suppress(asyncio.CancelledError):
                await status_task
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        status_message = status_holder.get("message")
        if status_message:
            with suppress(Exception):
                await bot.delete_message(chat_id=chat_id, message_id=status_message.message_id)


def gemini_generate_with_retry(model: str, contents, config, retries: int = 3):
    base_delay = 1.0
    for attempt in range(1, retries + 1):
        try:
            return gemini_client.models.generate_content(
                model=model, contents=contents, config=config
            )
        except Exception as exc:
            if attempt == retries:
                raise
            delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0, 0.4)
            logger.warning(
                "Gemini error (attempt %s/%s): %s. Retrying in %.2fs",
                attempt,
                retries,
                exc,
                delay,
            )
            time.sleep(delay)

TOOLS = [
    {
        "name": "get_current_time",
        "description": "Get the current date and time, optionally in a specific timezone.",
        "input_schema": {
            "type": "object",
            "properties": {
                "timezone": {
                    "type": "string",
                    "description": "IANA timezone name, e.g. 'Europe/London', 'America/New_York'.",
                }
            },
            "required": [],
        },
    },
    {
        "name": "get_weather",
        "description": "Get current weather and forecast for a city.",
        "input_schema": {
            "type": "object",
            "properties": {"city": {"type": "string", "description": "City name"}},
            "required": ["city"],
        },
    },
    {
        "name": "web_search",
        "description": "Search the web for current information on any topic.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "max_results": {
                    "type": "integer",
                    "description": "Number of results (default 5)",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_news",
        "description": "Get latest news articles on a topic.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "News topic"},
                "max_results": {
                    "type": "integer",
                    "description": "Number of articles (default 5)",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "wikipedia_search",
        "description": "Search Wikipedia for a summary of a topic.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Wikipedia topic"}},
            "required": ["query"],
        },
    },
    {
        "name": "calculate",
        "description": "Evaluate a mathematical expression.",
        "input_schema": {
            "type": "object",
            "properties": {"expression": {"type": "string", "description": "Math expression"}},
            "required": ["expression"],
        },
    },
    {
        "name": "get_country_info",
        "description": "Get information about a country.",
        "input_schema": {
            "type": "object",
            "properties": {"country": {"type": "string", "description": "Country name"}},
            "required": ["country"],
        },
    },
    {
        "name": "define_word",
        "description": "Get dictionary definitions for a word.",
        "input_schema": {
            "type": "object",
            "properties": {"word": {"type": "string", "description": "Word to define"}},
            "required": ["word"],
        },
    },
    {"name": "get_nest_devices", "description": "List Nest devices.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "get_thermostat_status", "description": "Get Nest thermostat status.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {
        "name": "set_thermostat_temperature",
        "description": "Set Nest thermostat temperature.",
        "input_schema": {
            "type": "object",
            "properties": {
                "temperature": {"type": "number", "description": "Target temperature"},
                "unit": {"type": "string", "description": "celsius or fahrenheit"},
            },
            "required": ["temperature"],
        },
    },
    {
        "name": "set_thermostat_mode",
        "description": "Set Nest thermostat mode. Supports OFF, HEAT, COOL, HEATCOOL.",
        "input_schema": {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "description": "Target thermostat mode (OFF, HEAT, COOL, HEATCOOL)"},
            },
            "required": ["mode"],
        },
    },
    {"name": "get_camera_status", "description": "Get Nest camera status.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {
        "name": "get_camera_snapshot",
        "description": "Capture a live snapshot photo from a Nest camera. Use this when the user asks to see a specific camera view.",
        "input_schema": {
            "type": "object",
            "properties": {
                "camera_name": {
                    "type": "string",
                    "description": "Camera label, e.g. 'Front of Garage'. Optional: if omitted, use first camera.",
                }
            },
            "required": [],
        },
    },
    {"name": "get_doorbell_snapshot", "description": "Capture a live snapshot photo from the Nest doorbell camera.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {
        "name": "get_upcoming_events",
        "description": "Get upcoming Google Calendar events.",
        "input_schema": {"type": "object", "properties": {"max_results": {"type": "integer", "default": 10}}, "required": []},
    },
    {
        "name": "search_calendar_events",
        "description": "Search Google Calendar events.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}, "max_results": {"type": "integer", "default": 5}},
            "required": ["query"],
        },
    },
    {
        "name": "get_recent_emails",
        "description": "Get recent Gmail inbox messages.",
        "input_schema": {"type": "object", "properties": {"max_results": {"type": "integer", "default": 5}}, "required": []},
    },
    {
        "name": "search_emails",
        "description": "Search Gmail messages.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}, "max_results": {"type": "integer", "default": 5}},
            "required": ["query"],
        },
    },
]


def _schema_to_gemini(schema: dict) -> types.Schema:
    type_map = {
        "object": types.Type.OBJECT,
        "string": types.Type.STRING,
        "integer": types.Type.INTEGER,
        "number": types.Type.NUMBER,
        "boolean": types.Type.BOOLEAN,
        "array": types.Type.ARRAY,
    }
    t = type_map.get(schema.get("type", "string"), types.Type.STRING)
    kwargs: dict = {"type": t}
    if "description" in schema:
        kwargs["description"] = schema["description"]
    if "properties" in schema:
        kwargs["properties"] = {k: _schema_to_gemini(v) for k, v in schema["properties"].items()}
    if schema.get("required"):
        kwargs["required"] = schema["required"]
    return types.Schema(**kwargs)


def _build_gemini_tools(tools: list) -> list:
    declarations = [
        types.FunctionDeclaration(
            name=tool["name"],
            description=tool.get("description", ""),
            parameters=_schema_to_gemini(tool["input_schema"]) if tool.get("input_schema", {}).get("properties") else None,
        )
        for tool in tools
    ]
    return [types.Tool(function_declarations=declarations)]


GEMINI_TOOLS = _build_gemini_tools(TOOLS)


def env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name, "true" if default else "false").strip().lower()
    return raw in {"1", "true", "yes", "y", "on"}


UX_PHASE2_ENABLED = env_flag("UX_PHASE2_ENABLED", True)
UX_PHASE3_ENABLED = env_flag("UX_PHASE3_ENABLED", True)
UX_PHASE4_ENABLED = env_flag("UX_PHASE4_ENABLED", True)
OFFLINE_BROADCAST_ENABLED = env_flag("OFFLINE_BROADCAST_ENABLED", True)
ONLINE_BROADCAST_ENABLED = env_flag("ONLINE_BROADCAST_ENABLED", True)


def handler_guard(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            return await func(update, context)
        except Exception as exc:
            logger.exception("Handler failed", extra={"handler": func.__name__})
            if is_offline_error(exc):
                message = (
                    "Bob is currently offline. Please try again in a minute."
                )
            else:
                message = "I hit an unexpected error. Please try again."
            if update.callback_query:
                await update.callback_query.answer("Something went wrong. Please try again.")
                await update.callback_query.message.reply_text(message)
            elif update.message:
                await update.message.reply_text(message)

    return wrapper


def _iter_exception_chain(exc: Exception):
    current = exc
    visited = set()
    while current and id(current) not in visited:
        visited.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def is_offline_error(exc: Exception) -> bool:
    offline_markers = (
        "overloaded",
        "service unavailable",
        "temporarily unavailable",
        "timed out",
        "timeout",
        "connection error",
        "connection reset",
        "network is unreachable",
        "503",
        "529",
    )
    offline_types = {
        "OverloadedError",
        "ServiceUnavailableError",
        "APIConnectionError",
        "ConnectError",
        "ReadTimeout",
        "WriteTimeout",
        "RemoteProtocolError",
        "NetworkError",
        "TimeoutException",
    }
    for item in _iter_exception_chain(exc):
        name = type(item).__name__
        text = str(item).lower()
        if name in offline_types:
            return True
        if any(marker in text for marker in offline_markers):
            return True
    return False


def extract_text_from_parts(parts) -> str:
    return "\n".join(p.text for p in parts if hasattr(p, "text") and p.text).strip()


def style_reply(text: str, style: str) -> str:
    if style == "short":
        lines = [line for line in text.splitlines() if line.strip()]
        return "\n".join(lines[:4])[:600]
    if style == "detailed" and len(text) < 120:
        return f"{text}\n\nNeed more detail? Ask for a deeper walkthrough."
    return text


def get_current_time(timezone: str = "") -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    try:
        tz = ZoneInfo(timezone) if timezone else None
        now = datetime.now(tz)
        tz_label = timezone if timezone else "local"
        return now.strftime(f"%A, %d %B %Y %H:%M:%S ({tz_label})")
    except Exception:
        return f"Unknown timezone '{timezone}'. Use IANA format like America/Los_Angeles."


def fetch_weather(city: str) -> str:
    geo = httpx.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": city, "count": 1},
        timeout=12,
    ).json()
    if not geo.get("results"):
        return f"Could not find location: {city}"

    result = geo["results"][0]
    weather = httpx.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": result["latitude"],
            "longitude": result["longitude"],
            "current": "temperature_2m,apparent_temperature,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min",
            "forecast_days": 3,
            "timezone": "auto",
        },
        timeout=12,
    ).json()

    current = weather["current"]
    daily = weather["daily"]
    lines = [
        f"City: {result['name']}",
        f"Now: {current['temperature_2m']}C (feels {current['apparent_temperature']}C)",
        f"Wind: {current['wind_speed_10m']} km/h",
        "3-day:",
    ]
    for i in range(3):
        lines.append(f"- {daily['time'][i]}: {daily['temperature_2m_min'][i]} to {daily['temperature_2m_max'][i]}C")
    return "\n".join(lines)


def search_web(query: str, max_results: int = 5) -> str:
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
    except Exception as exc:
        logger.warning("Web search provider error for query=%r: %s", query, exc)
        return "Web search is temporarily unavailable."
    if not results:
        return "No results found."
    return "\n\n".join(f"{r.get('title', '')}\n{r.get('body', '')}\n{r.get('href', '')}" for r in results)


def get_news(query: str, max_results: int = 5) -> str:
    try:
        with DDGS() as ddgs:
            results = list(ddgs.news(query, max_results=max_results))
    except Exception as exc:
        logger.warning("News search provider error for query=%r: %s", query, exc)
        return "News search is temporarily unavailable."
    if not results:
        return "No news found."
    return "\n\n".join(
        f"{r.get('title', '')} ({r.get('date', '')})\n{r.get('body', '')}\n{r.get('url', '')}" for r in results
    )


def wikipedia_search(query: str) -> str:
    try:
        summary = wikipedia.summary(query, sentences=5, auto_suggest=True)
        page = wikipedia.page(query, auto_suggest=True)
        return f"{summary}\n\nMore: {page.url}"
    except wikipedia.DisambiguationError as exc:
        return f"Ambiguous query. Did you mean: {', '.join(exc.options[:5])}?"
    except wikipedia.PageError:
        return f"No Wikipedia page found for '{query}'."


def calculate(expression: str) -> str:
    allowed = {
        "sqrt": math.sqrt,
        "sin": math.sin,
        "cos": math.cos,
        "tan": math.tan,
        "log": math.log,
        "log10": math.log10,
        "abs": abs,
        "round": round,
        "pi": math.pi,
        "e": math.e,
    }
    try:
        result = eval(expression, {"__builtins__": {}}, allowed)
        return str(result)
    except Exception as ex:
        return f"Error: {ex}"


def get_country_info(country: str) -> str:
    response = httpx.get(
        f"https://restcountries.com/v3.1/name/{country}", params={"fullText": "false"}, timeout=10
    )
    if response.status_code != 200:
        return f"Country not found: {country}"
    data = response.json()[0]
    languages = ", ".join(data.get("languages", {}).values())
    currencies = ", ".join(
        f"{val['name']} ({val.get('symbol', '')})" for val in data.get("currencies", {}).values()
    )
    return (
        f"{data['name']['common']} ({data['name']['official']})\n"
        f"Capital: {', '.join(data.get('capital', ['N/A']))}\n"
        f"Region: {data.get('region')} / {data.get('subregion')}\n"
        f"Population: {data.get('population', 0):,}\n"
        f"Languages: {languages}\n"
        f"Currency: {currencies}"
    )


def define_word(word: str) -> str:
    response = httpx.get(f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}", timeout=10)
    if response.status_code != 200:
        return f"No definition found for '{word}'."
    data = response.json()[0]
    phonetic = data.get("phonetic", "")
    lines = [f"{word} {phonetic}".strip()]
    for meaning in data.get("meanings", [])[:3]:
        lines.append(f"\n{meaning['partOfSpeech']}")
        for defn in meaning.get("definitions", [])[:2]:
            lines.append(f"- {defn['definition']}")
            if defn.get("example"):
                lines.append(f"  e.g. \"{defn['example']}\"")
    return "\n".join(lines)


def _capture_doorbell_snapshot(user_id: int) -> str:
    image_bytes, error = get_doorbell_snapshot()
    if error:
        return error
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        f.write(image_bytes)
        _snapshot_queue[user_id] = f.name
    return "Doorbell snapshot captured."


def _capture_camera_snapshot(user_id: int, camera_name: str = "") -> str:
    image_bytes, error = get_camera_snapshot(camera_name)
    if error:
        return error
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        f.write(image_bytes)
        _snapshot_queue[user_id] = f.name
    if camera_name:
        return f"Snapshot captured from {camera_name}."
    return "Camera snapshot captured."


def run_tool(name: str, tool_input: dict, user_id: int = 0) -> str:
    if name == "get_current_time":
        return get_current_time(tool_input.get("timezone", ""))
    if name == "get_weather":
        return fetch_weather(tool_input["city"])
    if name == "web_search":
        return search_web(tool_input["query"], tool_input.get("max_results", 5))
    if name == "get_news":
        return get_news(tool_input["query"], tool_input.get("max_results", 5))
    if name == "wikipedia_search":
        return wikipedia_search(tool_input["query"])
    if name == "calculate":
        return calculate(tool_input["expression"])
    if name == "get_country_info":
        return get_country_info(tool_input["country"])
    if name == "define_word":
        return define_word(tool_input["word"])
    if name == "get_nest_devices":
        return get_nest_devices()
    if name == "get_thermostat_status":
        return get_thermostat_status()
    if name == "set_thermostat_temperature":
        return set_thermostat_temperature(tool_input["temperature"], tool_input.get("unit", "celsius"))
    if name == "set_thermostat_mode":
        return set_thermostat_mode(tool_input["mode"])
    if name == "get_camera_status":
        return get_camera_status()
    if name == "get_camera_snapshot":
        return _capture_camera_snapshot(user_id, tool_input.get("camera_name", ""))
    if name == "get_doorbell_snapshot":
        return _capture_doorbell_snapshot(user_id)
    if name == "get_upcoming_events":
        return get_upcoming_events(tool_input.get("max_results", 10))
    if name == "search_calendar_events":
        return search_calendar_events(tool_input["query"], tool_input.get("max_results", 5))
    if name == "get_recent_emails":
        return get_recent_emails(tool_input.get("max_results", 5))
    if name == "search_emails":
        return search_emails(tool_input["query"], tool_input.get("max_results", 5))
    return "Unknown tool"


def generate_short_model_response(instruction: str, text: str, model: str = DEFAULT_MODEL) -> str:
    response = gemini_generate_with_retry(
        model=model,
        contents=[types.Content(role="user", parts=[types.Part(text=f"{instruction}\n\n{text}")])],
        config=types.GenerateContentConfig(
            system_instruction="You are Bob. Be concise and clear.",
            max_output_tokens=512,
        ),
    )
    return response.text or "I could not generate a response."


def generate_agent_response(user_id: int, user_text: str, force_web: bool = False) -> str:
    prefs = get_user_preferences(user_id)
    model = prefs.selected_model if prefs.selected_model in MODEL_CHOICES else DEFAULT_MODEL
    if user_id not in conversations:
        conversations[user_id] = []

    prompt = user_text
    if force_web:
        prompt = f"Use web search to answer this with current info: {user_text}"

    conversations[user_id].append(
        types.Content(role="user", parts=[types.Part(text=prompt)])
    )
    history = list(conversations[user_id][-20:])

    system_prompt = (
        f"{SYSTEM_PROMPT}\n"
        f"User preferences: language={prefs.language}, style={prefs.response_style}, timezone={prefs.timezone}."
    )
    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        tools=GEMINI_TOOLS,
        max_output_tokens=1024,
    )

    while True:
        response = gemini_generate_with_retry(model, history, config)
        candidate = response.candidates[0]

        function_call_parts = [p for p in candidate.content.parts if p.function_call]

        if not function_call_parts:
            reply = extract_text_from_parts(candidate.content.parts)
            conversations[user_id].append(candidate.content)
            snapshot_path = _snapshot_queue.pop(user_id, None)
            return style_reply(reply or "I could not generate a response.", prefs.response_style), snapshot_path

        history.append(candidate.content)
        function_response_parts = []
        for part in function_call_parts:
            fc = part.function_call
            try:
                result = run_tool(fc.name, dict(fc.args), user_id=user_id)
            except Exception as exc:
                logger.exception("Tool execution failed: %s", fc.name)
                result = f"Tool '{fc.name}' failed: {exc}"
            function_response_parts.append(
                types.Part(
                    function_response=types.FunctionResponse(
                        name=fc.name,
                        response={"result": result},
                    )
                )
            )
        history.append(types.Content(role="user", parts=function_response_parts))


def summarize_for_preview(text: str, max_len: int = 700) -> str:
    return text if len(text) <= max_len else text[:max_len] + "..."


def detect_thermostat_mode_request(text: str) -> Optional[str]:
    msg = (text or "").strip().lower()
    if not msg:
        return None

    thermostat_context = any(
        token in msg for token in ("thermostat", "hvac", "heater", "air conditioner", "ac mode")
    )
    if not thermostat_context:
        return None

    if any(phrase in msg for phrase in ("turn off", "set to off", "mode off", "switch off")):
        return "OFF"
    if "heatcool" in msg or "heat cool" in msg or "auto" in msg:
        return "HEATCOOL"
    if "cool" in msg or "ac" in msg:
        return "COOL"
    if "heat" in msg:
        return "HEAT"
    if re.search(r"\boff\b", msg):
        return "OFF"
    return None


def analyze_image(path: Path, model: str = DEFAULT_MODEL) -> str:
    mime_type = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    image_bytes = path.read_bytes()
    response = gemini_generate_with_retry(
        model=model,
        contents=[
            types.Content(role="user", parts=[
                types.Part(text="Extract visible text first, then summarize this image in concise bullets."),
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            ])
        ],
        config=types.GenerateContentConfig(max_output_tokens=700),
    )
    return response.text or "I could not analyze that image."


def summarize_document_text(text: str, model: str = DEFAULT_MODEL) -> str:
    chunk = text[:12000]
    return generate_short_model_response(
        "Summarize this document into key points and include action items if any are implied.",
        chunk,
        model=model,
    )


def extract_pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    pages = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return "\n".join(pages).strip()


async def send_reply_with_actions(update: Update, _user_prompt: str, reply_text: str):
    await update.message.reply_text(reply_text)


@handler_guard
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    chat_id = update.effective_chat.id

    pending_tool = context.user_data.get("awaiting_tool")
    if pending_tool:
        context.user_data.pop("awaiting_tool", None)
        pending_status_map = {
            "tool_weather": "Bob is checking the weather...",
            "tool_news": "Bob is gathering the latest news...",
            "tool_web_search": "Bob is searching the web...",
            "tool_wikipedia": "Bob is reading Wikipedia...",
            "tool_calculate": "Bob is calculating that...",
            "tool_country": "Bob is looking up country info...",
            "tool_define": "Bob is checking the dictionary...",
            "tool_calendar_search": "Bob is searching your calendar...",
            "tool_email_search": "Bob is searching your email...",
            "tool_camera_snapshot": "Bob is checking the camera feed...",
        }
        pending_status = pending_status_map.get(pending_tool, "Bob is working on it...")
        async with processing_indicator(context.bot, chat_id, status_text=pending_status):
            if pending_tool == "tool_weather":
                raw = await asyncio.to_thread(fetch_weather, text)
                out = render_card("weather", raw) if UX_PHASE2_ENABLED else raw
            elif pending_tool == "tool_news":
                raw = await asyncio.to_thread(get_news, text, 5)
                out = render_card("news", raw) if UX_PHASE2_ENABLED else raw
            elif pending_tool == "tool_web_search":
                out = await asyncio.to_thread(search_web, text, 5)
            elif pending_tool == "tool_wikipedia":
                out = await asyncio.to_thread(wikipedia_search, text)
            elif pending_tool == "tool_calculate":
                out = await asyncio.to_thread(calculate, text)
            elif pending_tool == "tool_country":
                out = await asyncio.to_thread(get_country_info, text)
            elif pending_tool == "tool_define":
                out = await asyncio.to_thread(define_word, text)
            elif pending_tool == "tool_calendar_search":
                raw = await asyncio.to_thread(search_calendar_events, text, 5)
                out = render_card("calendar", raw) if UX_PHASE2_ENABLED else raw
            elif pending_tool == "tool_email_search":
                raw = await asyncio.to_thread(search_emails, text, 5)
                out = render_card("email", raw) if UX_PHASE2_ENABLED else raw
            elif pending_tool == "tool_camera_snapshot":
                out = await asyncio.to_thread(run_tool, "get_camera_snapshot", {"camera_name": text}, user_id)
            else:
                out = "Unsupported tool input."
        snapshot_path = _snapshot_queue.pop(user_id, None)
        if snapshot_path:
            await update.message.reply_photo(photo=open(snapshot_path, "rb"), caption=out)
            os.unlink(snapshot_path)
        else:
            await send_reply_with_actions(update, text, out)
        return

    if context.user_data.get("awaiting_voice_edit"):
        context.user_data["awaiting_voice_edit"] = False
        save_pending_transcription(user_id, text)
        await update.message.reply_text(
            f"Transcribed as:\n\n{summarize_for_preview(text)}",
            reply_markup=voice_preview_keyboard(),
        )
        return

    if context.user_data.get("awaiting_artifact_question"):
        context.user_data["awaiting_artifact_question"] = False
        artifact = get_latest_artifact(user_id)
        if not artifact:
            await update.message.reply_text("No recent file context found.")
            return
        async with processing_indicator(context.bot, chat_id, status_text="Bob is reading your file..."):
            answer = await asyncio.to_thread(
                generate_short_model_response,
                f"Answer the user question using only this artifact context:\n\n{artifact['content_text']}",
                f"Question: {text}",
            )
        await send_reply_with_actions(update, text, answer)
        return

    thermostat_mode = detect_thermostat_mode_request(text)
    if thermostat_mode:
        async with processing_indicator(context.bot, chat_id, status_text="Bob is updating the thermostat..."):
            out = await asyncio.to_thread(run_tool, "set_thermostat_mode", {"mode": thermostat_mode}, user_id)
        await send_reply_with_actions(update, text, out)
        return

    async with processing_indicator(context.bot, chat_id, status_text="Bob is thinking..."):
        reply, snapshot_path = await asyncio.to_thread(generate_agent_response, user_id, text)

    if snapshot_path:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
        await update.message.reply_photo(photo=open(snapshot_path, "rb"), caption=reply)
        os.unlink(snapshot_path)
    else:
        await send_reply_with_actions(update, text, reply)


@handler_guard
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not UX_PHASE3_ENABLED:
        await update.message.reply_text("Voice input is currently disabled.")
        return

    voice = update.message.voice
    if voice.duration and voice.duration > 180:
        await update.message.reply_text("Voice note is too long. Please keep it under 3 minutes.")
        return
    if voice.file_size and voice.file_size > 5 * 1024 * 1024:
        await update.message.reply_text("Voice note is too large. Please keep it under 5MB.")
        return

    await update.message.reply_text(
        "Voice transcription is currently unavailable in this configuration. "
        "You can send text, images, or PDF files."
    )


@handler_guard
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not UX_PHASE4_ENABLED:
        await update.message.reply_text("Image analysis is currently disabled.")
        return

    photo = update.message.photo[-1]
    tg_file = await context.bot.get_file(photo.file_id)
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        temp_path = Path(tmp.name)

    try:
        await tg_file.download_to_drive(custom_path=str(temp_path))
        async with processing_indicator(context.bot, update.effective_chat.id, status_text="Bob is analyzing the image..."):
            user_model = get_user_preferences(update.effective_user.id).selected_model
            summary = await asyncio.to_thread(analyze_image, temp_path, user_model)
    finally:
        if temp_path.exists():
            temp_path.unlink()

    save_artifact(update.effective_user.id, "image", summary, file_id=photo.file_id, mime_type="image/jpeg")
    await update.message.reply_text(
        f"Image analysis:\n\n{summary}",
        reply_markup=artifact_actions_keyboard(),
    )


@handler_guard
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not UX_PHASE4_ENABLED:
        await update.message.reply_text("Document analysis is currently disabled.")
        return

    doc = update.message.document
    doc_type = detect_document_type(doc.mime_type or "", doc.file_name or "")
    if doc_type == "unsupported":
        await update.message.reply_text("Supported files: images, PDF, and text files.")
        return

    tg_file = await context.bot.get_file(doc.file_id)
    suffix = Path(doc.file_name or "upload.bin").suffix or ".bin"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        temp_path = Path(tmp.name)

    try:
        await tg_file.download_to_drive(custom_path=str(temp_path))

        async with processing_indicator(context.bot, update.effective_chat.id, status_text="Bob is reading the document..."):
            user_model = get_user_preferences(update.effective_user.id).selected_model
            if doc_type == "image":
                content = await asyncio.to_thread(analyze_image, temp_path, user_model)
                artifact_type = "image"
            elif doc_type == "pdf":
                extracted = await asyncio.to_thread(extract_pdf_text, temp_path)
                if not extracted.strip():
                    await update.message.reply_text("I could not extract text from that PDF.")
                    return
                content = await asyncio.to_thread(summarize_document_text, extracted, user_model)
                artifact_type = "document"
            else:
                extracted = await asyncio.to_thread(temp_path.read_text, errors="ignore")
                content = await asyncio.to_thread(summarize_document_text, extracted, user_model)
                artifact_type = "document"
    finally:
        if temp_path.exists():
            temp_path.unlink()

    save_artifact(
        update.effective_user.id,
        artifact_type,
        content,
        file_id=doc.file_id,
        file_name=doc.file_name or "",
        mime_type=doc.mime_type or "",
    )
    await update.message.reply_text(
        f"File analysis:\n\n{content}",
        reply_markup=artifact_actions_keyboard(),
    )


@handler_guard
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    payload = parse_callback_data(query.data or "")
    action = payload.get("action", "")
    user_id = query.from_user.id
    message_id = query.message.message_id if query.message else 0

    if message_id and is_duplicate_callback(user_id, message_id, action):
        await query.answer("Already processed.")
        return

    if action == "reset":
        conversations[user_id] = []
        await query.message.reply_text("Conversation reset.")
        return

    if action.startswith("pref_style_"):
        style = action.replace("pref_style_", "")
        set_response_style(user_id, style)
        await query.message.reply_text(
            f"Preference updated: response style = {style}",
            reply_markup=style_keyboard(style),
        )
        return

    if action.startswith("pref_lang_"):
        lang = action.replace("pref_lang_", "")
        set_language(user_id, lang)
        await query.message.reply_text(f"Preference updated: language = {lang}")
        return

    if action.startswith("pref_tz_"):
        tz_map = {"pt": "America/Los_Angeles", "et": "America/New_York", "utc": "UTC"}
        tz = tz_map.get(action.replace("pref_tz_", ""), "America/Los_Angeles")
        set_timezone(user_id, tz)
        await query.message.reply_text(f"Preference updated: timezone = {tz}")
        return

    if action == "model_flash_lite":
        set_selected_model(user_id, "models/gemini-3.1-flash-lite-preview")
        prefs = get_user_preferences(user_id)
        await query.message.reply_text(
            f"Model updated: {MODEL_CHOICES[prefs.selected_model]}",
            reply_markup=model_keyboard(prefs.selected_model),
        )
        return

    if action == "model_pro":
        set_selected_model(user_id, "models/gemini-3.1-pro-preview")
        prefs = get_user_preferences(user_id)
        await query.message.reply_text(
            f"Model updated: {MODEL_CHOICES[prefs.selected_model]}",
            reply_markup=model_keyboard(prefs.selected_model),
        )
        return

    if action == "tool_time":
        prefs = get_user_preferences(user_id)
        await query.message.reply_text(get_current_time(prefs.timezone))
        return
    if action == "tools_home":
        await query.message.reply_text("Choose a tool:", reply_markup=tools_keyboard())
        return
    if action == "tools_all":
        await query.message.reply_text(format_all_tools_text())
        return
    if action.startswith("toolcat_"):
        category = action.replace("toolcat_", "")
        title_map = {
            "research": "Research tools:",
            "comms": "Calendar and email tools:",
            "home": "Home tools:",
            "utilities": "Utility tools:",
            "media": "Media tools:",
        }
        await query.message.reply_text(
            title_map.get(category, "Tools:"),
            reply_markup=tools_category_keyboard(category),
        )
        return
    if action == "tool_weather":
        context.user_data["awaiting_tool"] = "tool_weather"
        await query.message.reply_text("Send a city name for weather.")
        return
    if action == "tool_news":
        context.user_data["awaiting_tool"] = "tool_news"
        await query.message.reply_text("Send a topic for news.")
        return
    if action == "tool_web_search":
        context.user_data["awaiting_tool"] = "tool_web_search"
        await query.message.reply_text("Send your web search query.")
        return
    if action == "tool_wikipedia":
        context.user_data["awaiting_tool"] = "tool_wikipedia"
        await query.message.reply_text("Send a topic for Wikipedia.")
        return
    if action == "tool_calculate":
        context.user_data["awaiting_tool"] = "tool_calculate"
        await query.message.reply_text("Send a math expression, e.g. `sqrt(144)` or `2**10`.")
        return
    if action == "tool_country":
        context.user_data["awaiting_tool"] = "tool_country"
        await query.message.reply_text("Send a country name.")
        return
    if action == "tool_define":
        context.user_data["awaiting_tool"] = "tool_define"
        await query.message.reply_text("Send a word to define.")
        return
    if action == "tool_calendar":
        async with processing_indicator(context.bot, query.message.chat_id, status_text="Bob is checking your calendar..."):
            text = await asyncio.to_thread(get_upcoming_events, 8)
        await query.message.reply_text(render_card("calendar", text) if UX_PHASE2_ENABLED else text)
        return
    if action == "tool_calendar_search":
        context.user_data["awaiting_tool"] = "tool_calendar_search"
        await query.message.reply_text("Send a calendar search term.")
        return
    if action == "tool_email":
        async with processing_indicator(context.bot, query.message.chat_id, status_text="Bob is checking your inbox..."):
            text = await asyncio.to_thread(get_recent_emails, 5)
        await query.message.reply_text(render_card("email", text) if UX_PHASE2_ENABLED else text)
        return
    if action == "tool_email_search":
        context.user_data["awaiting_tool"] = "tool_email_search"
        await query.message.reply_text("Send a Gmail search query (e.g. `from:alice invoice`).")
        return
    if action == "tool_nest_devices":
        async with processing_indicator(context.bot, query.message.chat_id, status_text="Bob is checking your Nest devices..."):
            text = await asyncio.to_thread(get_nest_devices)
        await query.message.reply_text(text)
        return
    if action == "tool_nest":
        async with processing_indicator(context.bot, query.message.chat_id, status_text="Bob is checking the thermostat..."):
            text = await asyncio.to_thread(get_thermostat_status)
        await query.message.reply_text(text)
        return
    if action == "tool_camera_status":
        async with processing_indicator(context.bot, query.message.chat_id, status_text="Bob is checking camera status..."):
            text = await asyncio.to_thread(get_camera_status)
        await query.message.reply_text(text)
        return
    if action == "tool_camera_snapshot":
        context.user_data["awaiting_tool"] = "tool_camera_snapshot"
        await query.message.reply_text("Send the camera name (e.g. `Front of Garage`).")
        return
    if action == "tool_doorbell_snapshot":
        async with processing_indicator(context.bot, query.message.chat_id, status_text="Bob is checking the doorbell camera..."):
            text = await asyncio.to_thread(run_tool, "get_doorbell_snapshot", {}, user_id)
        snapshot_path = _snapshot_queue.pop(user_id, None)
        if snapshot_path:
            await query.message.reply_photo(photo=open(snapshot_path, "rb"), caption=text)
            os.unlink(snapshot_path)
        else:
            await query.message.reply_text(text)
        return
    if action == "tool_media_help":
        await query.message.reply_text(
            "Send a photo, image file, PDF, or text file and I will analyze it. "
            "Then ask follow-up questions in chat for summaries, action items, or Q&A."
        )
        return

    if action in {"voice_use", "voice_edit", "voice_cancel"}:
        if action == "voice_cancel":
            clear_pending_transcription(user_id)
            await query.message.reply_text("Canceled voice input.")
            return
        if action == "voice_edit":
            context.user_data["awaiting_voice_edit"] = True
            await query.message.reply_text("Send the edited transcription text.")
            return
        text = get_pending_transcription(user_id)
        clear_pending_transcription(user_id)
        if not text:
            await query.message.reply_text("No pending transcription found.")
            return
        async with processing_indicator(context.bot, query.message.chat_id, status_text="Bob is thinking..."):
            reply, snapshot_path = await asyncio.to_thread(generate_agent_response, user_id, text)
        if snapshot_path:
            await query.message.reply_photo(photo=open(snapshot_path, "rb"), caption=reply)
            os.unlink(snapshot_path)
            return
        await query.message.reply_text(reply)
        return

    if action in {"artifact_summarize", "artifact_actions", "artifact_ask"}:
        artifact = get_latest_artifact(user_id)
        if not artifact:
            await query.message.reply_text("No recent uploaded file found.")
            return
        if action == "artifact_ask":
            context.user_data["awaiting_artifact_question"] = True
            await query.message.reply_text("Ask your question about the last uploaded file.")
            return
        if action == "artifact_summarize":
            async with processing_indicator(context.bot, query.message.chat_id, status_text="Bob is summarizing your file..."):
                model = get_user_preferences(user_id).selected_model
                out = await asyncio.to_thread(
                    generate_short_model_response,
                    "Summarize this artifact in 5 concise bullets.",
                    artifact["content_text"],
                    model,
                )
            await query.message.reply_text(out)
            return
        async with processing_indicator(context.bot, query.message.chat_id, status_text="Bob is extracting action items..."):
            model = get_user_preferences(user_id).selected_model
            out = await asyncio.to_thread(
                generate_short_model_response,
                "Extract actionable next steps from this artifact.",
                artifact["content_text"],
                model,
            )
        await query.message.reply_text(out)
        return

    await query.message.reply_text("Action not recognized.")


@handler_guard
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conversations[user_id] = []
    get_user_preferences(user_id)
    await update.message.reply_text(
        "Hi! I'm Bob.\n"
        "Use /tools for one-tap actions, /prefs for style/language/timezone, and /help for examples."
    )


@handler_guard
async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conversations[user_id] = []
    await update.message.reply_text("Conversation reset.")


@handler_guard
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "What I can do:\n"
        "- Chat and reasoning\n"
        "- Weather, web search, news, Wikipedia, calculator\n"
        "- Google Calendar + Gmail\n"
        "- Nest status and control\n"
        "- Voice notes and file/image understanding\n"
        "- /model to switch Gemini model\n\n"
        "- /style to quickly change response style\n\n"
        "Try:\n"
        "- 'Summarize my upcoming events'\n"
        "- 'Search latest AI model news'\n"
        "- Upload a PDF and ask questions"
    )


@handler_guard
async def tools_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args and context.args[0].lower() == "all":
        await update.message.reply_text(
            format_all_tools_text()
        )
        return
    await update.message.reply_text("Choose a tool:", reply_markup=tools_keyboard())


@handler_guard
async def prefs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prefs = get_user_preferences(update.effective_user.id)
    await update.message.reply_text(
        f"Current prefs:\n- style: {prefs.response_style}\n- language: {prefs.language}\n- timezone: {prefs.timezone}\n\n"
        "Use /style for clearer style options. Quick update:",
        reply_markup=style_keyboard(prefs.response_style),
    )


@handler_guard
async def model_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prefs = get_user_preferences(update.effective_user.id)
    model_name = MODEL_CHOICES.get(prefs.selected_model, prefs.selected_model)
    await update.message.reply_text(
        "Choose the model for your responses:\n"
        "- Gemini 3.1 Flash-Lite Preview: faster/lower cost\n"
        "- Gemini 3.1 Pro Preview: stronger reasoning\n\n"
        f"Current: {model_name}",
        reply_markup=model_keyboard(prefs.selected_model),
    )


@handler_guard
async def style_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prefs = get_user_preferences(update.effective_user.id)
    await update.message.reply_text(
        "Choose response style:\n"
        "- Short: concise, high-signal output\n"
        "- Normal: balanced detail\n"
        "- Detailed: more depth and context\n\n"
        f"Current: {prefs.response_style}",
        reply_markup=style_keyboard(prefs.response_style),
    )


@handler_guard
async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = (update.message.text or "").strip()
    command = raw.split()[0] if raw else "that command"
    await update.message.reply_text(
        f"I don't know how to handle `{command}` yet.\n\n"
        "Try one of these commands:\n"
        "- /start\n"
        "- /help\n"
        "- /tools\n"
        "- /prefs\n"
        "- /style\n"
        "- /model\n"
        "- /reset\n\n"
        "Or tell me what you're trying to accomplish in plain language and I can guide you."
    )


def format_all_tools_text() -> str:
    return (
        "All tools:\n\n"
        "Research\n"
        "- Web Search\n"
        "- News\n"
        "- Wikipedia\n"
        "- Country Info\n"
        "- Dictionary\n\n"
        "Comms\n"
        "- Upcoming Events\n"
        "- Search Calendar\n"
        "- Recent Emails\n"
        "- Search Emails\n\n"
        "Home\n"
        "- Nest Devices\n"
        "- Thermostat Status\n"
        "- Camera Status\n"
        "- Camera Snapshot\n"
        "- Doorbell Snapshot\n\n"
        "Utilities\n"
        "- Time\n"
        "- Weather\n"
        "- Calculator\n\n"
        "Media\n"
        "- Send an image, PDF, or text file for analysis"
    )


async def on_post_stop(app):
    if not OFFLINE_BROADCAST_ENABLED:
        return
    user_ids = list_known_user_ids()
    if not user_ids:
        return
    logger.info("Broadcasting offline notice to %s user(s)", len(user_ids))
    for user_id in user_ids:
        try:
            await app.bot.send_message(
                chat_id=user_id,
                text="Bob is currently offline. I will be back soon.",
            )
        except Exception:
            logger.debug("Failed to send offline notice", extra={"user_id": user_id}, exc_info=True)


async def on_post_init(app):
    if not ONLINE_BROADCAST_ENABLED:
        return
    user_ids = list_known_user_ids()
    if not user_ids:
        return
    logger.info("Broadcasting online notice to %s user(s)", len(user_ids))
    for user_id in user_ids:
        try:
            await app.bot.send_message(
                chat_id=user_id,
                text="I am back online.",
            )
        except Exception:
            logger.debug("Failed to send online notice", extra={"user_id": user_id}, exc_info=True)


def main():
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    init_storage()

    app = (
        ApplicationBuilder()
        .token(token)
        .post_init(on_post_init)
        .post_stop(on_post_stop)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("tools", tools_command))
    app.add_handler(CommandHandler("prefs", prefs_command))
    app.add_handler(CommandHandler("style", style_command))
    app.add_handler(CommandHandler("model", model_command))
    app.add_handler(CommandHandler("reset", reset))

    # Keep this after known CommandHandlers so it only catches unknown commands.
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot started. Polling...")
    app.run_polling()


if __name__ == "__main__":
    main()
