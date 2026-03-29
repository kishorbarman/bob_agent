import base64
import logging
import math
import os
import tempfile
from functools import wraps
from pathlib import Path

import httpx
import wikipedia
from anthropic import Anthropic
from duckduckgo_search import DDGS
from pypdf import PdfReader
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from google_services import (
    get_camera_status,
    get_nest_devices,
    get_recent_emails,
    get_thermostat_status,
    get_upcoming_events,
    search_calendar_events,
    search_emails,
    set_thermostat_temperature,
)
from preferences import (
    get_user_preferences,
    set_language,
    set_response_style,
    set_timezone,
)
from media_utils import detect_document_type
from storage import (
    clear_pending_transcription,
    get_latest_artifact,
    get_message_context,
    get_pending_transcription,
    init_storage,
    is_duplicate_callback,
    save_artifact,
    save_message_context,
    save_pending_transcription,
)
from telegram_ui import (
    artifact_actions_keyboard,
    parse_callback_data,
    prefs_keyboard,
    quick_actions_keyboard,
    render_card,
    tools_keyboard,
    voice_preview_keyboard,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

anthropic = Anthropic()

# Per-user conversation history
conversations: dict[int, list[dict]] = {}

SYSTEM_PROMPT = (
    "You are a helpful personal assistant called Bob. Be concise and direct. "
    "Use tools whenever they will give a better answer than your training data alone."
)

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
    {"name": "get_camera_status", "description": "Get Nest camera status.", "input_schema": {"type": "object", "properties": {}, "required": []}},
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


def env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name, "true" if default else "false").strip().lower()
    return raw in {"1", "true", "yes", "y", "on"}


UX_PHASE1_ENABLED = env_flag("UX_PHASE1_ENABLED", True)
UX_PHASE2_ENABLED = env_flag("UX_PHASE2_ENABLED", True)
UX_PHASE3_ENABLED = env_flag("UX_PHASE3_ENABLED", True)
UX_PHASE4_ENABLED = env_flag("UX_PHASE4_ENABLED", True)


def handler_guard(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            return await func(update, context)
        except Exception:
            logger.exception("Handler failed", extra={"handler": func.__name__})
            if update.callback_query:
                await update.callback_query.answer("Something went wrong. Please try again.")
                await update.callback_query.message.reply_text("I hit an unexpected error. Please try again.")
            elif update.message:
                await update.message.reply_text("I hit an unexpected error. Please try again.")

    return wrapper


def extract_text_blocks(content: list) -> str:
    parts: list[str] = []
    for block in content:
        if getattr(block, "type", "") == "text":
            parts.append(block.text)
    return "\n".join(parts).strip()


def style_reply(text: str, style: str) -> str:
    if style == "short":
        lines = [line for line in text.splitlines() if line.strip()]
        return "\n".join(lines[:4])[:600]
    if style == "detailed" and len(text) < 120:
        return f"{text}\n\nNeed more detail? Tap Retry and ask for a deeper walkthrough."
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
    with DDGS() as ddgs:
        results = list(ddgs.text(query, max_results=max_results))
    if not results:
        return "No results found."
    return "\n\n".join(f"{r['title']}\n{r['body']}\n{r['href']}" for r in results)


def get_news(query: str, max_results: int = 5) -> str:
    with DDGS() as ddgs:
        results = list(ddgs.news(query, max_results=max_results))
    if not results:
        return "No news found."
    return "\n\n".join(f"{r['title']} ({r['date']})\n{r['body']}\n{r['url']}" for r in results)


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


def run_tool(name: str, tool_input: dict) -> str:
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
    if name == "get_camera_status":
        return get_camera_status()
    if name == "get_upcoming_events":
        return get_upcoming_events(tool_input.get("max_results", 10))
    if name == "search_calendar_events":
        return search_calendar_events(tool_input["query"], tool_input.get("max_results", 5))
    if name == "get_recent_emails":
        return get_recent_emails(tool_input.get("max_results", 5))
    if name == "search_emails":
        return search_emails(tool_input["query"], tool_input.get("max_results", 5))
    return "Unknown tool"


def generate_short_model_response(instruction: str, text: str) -> str:
    response = anthropic.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=512,
        system="You are Bob. Be concise and clear.",
        messages=[{"role": "user", "content": f"{instruction}\n\n{text}"}],
    )
    return extract_text_blocks(response.content) or "I could not generate a response."


def generate_agent_response(user_id: int, user_text: str, force_web: bool = False) -> str:
    prefs = get_user_preferences(user_id)
    if user_id not in conversations:
        conversations[user_id] = []

    prompt = user_text
    if force_web:
        prompt = f"Use web search to answer this with current info: {user_text}"

    conversations[user_id].append({"role": "user", "content": prompt})
    history = conversations[user_id][-20:]

    system_prompt = (
        f"{SYSTEM_PROMPT}\n"
        f"User preferences: language={prefs.language}, style={prefs.response_style}, timezone={prefs.timezone}."
    )

    while True:
        response = anthropic.messages.create(
            model="claude-opus-4-6",
            max_tokens=1024,
            system=system_prompt,
            tools=TOOLS,
            messages=history,
        )

        if response.stop_reason == "end_turn":
            reply = extract_text_blocks(response.content)
            conversations[user_id].append({"role": "assistant", "content": response.content})
            return style_reply(reply, prefs.response_style)

        if response.stop_reason == "tool_use":
            history.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = run_tool(block.name, block.input)
                    tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result})
            history.append({"role": "user", "content": tool_results})


def summarize_for_preview(text: str, max_len: int = 700) -> str:
    return text if len(text) <= max_len else text[:max_len] + "..."


def analyze_image(path: Path) -> str:
    media_type = "image/jpeg"
    if path.suffix.lower() == ".png":
        media_type = "image/png"
    b64 = base64.b64encode(path.read_bytes()).decode("utf-8")
    response = anthropic.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=700,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Extract visible text first, then summarize this image in concise bullets."},
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                ],
            }
        ],
    )
    return extract_text_blocks(response.content) or "I could not analyze that image."


def summarize_document_text(text: str) -> str:
    chunk = text[:12000]
    return generate_short_model_response(
        "Summarize this document into key points and include action items if any are implied.",
        chunk,
    )


def extract_pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    pages = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return "\n".join(pages).strip()


async def send_reply_with_actions(update: Update, user_prompt: str, reply_text: str):
    if UX_PHASE1_ENABLED:
        sent = await update.message.reply_text(reply_text)
        save_message_context(update.effective_user.id, sent.message_id, user_prompt, reply_text)
        await sent.edit_reply_markup(reply_markup=quick_actions_keyboard(str(sent.message_id)))
    else:
        await update.message.reply_text(reply_text)


@handler_guard
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    if context.user_data.get("awaiting_tool_query") == "weather":
        context.user_data.pop("awaiting_tool_query", None)
        weather = fetch_weather(text)
        out = render_card("weather", weather) if UX_PHASE2_ENABLED else weather
        await send_reply_with_actions(update, text, out)
        return

    if context.user_data.get("awaiting_tool_query") == "news":
        context.user_data.pop("awaiting_tool_query", None)
        news = get_news(text, 5)
        out = render_card("news", news) if UX_PHASE2_ENABLED else news
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
        answer = generate_short_model_response(
            f"Answer the user question using only this artifact context:\n\n{artifact['content_text']}",
            f"Question: {text}",
        )
        await send_reply_with_actions(update, text, answer)
        return

    reply = generate_agent_response(user_id, text)
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
        "Voice transcription is currently unavailable in Anthropic-only mode. "
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
        summary = analyze_image(temp_path)
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

        if doc_type == "image":
            content = analyze_image(temp_path)
            artifact_type = "image"
        elif doc_type == "pdf":
            extracted = extract_pdf_text(temp_path)
            if not extracted.strip():
                await update.message.reply_text("I could not extract text from that PDF.")
                return
            content = summarize_document_text(extracted)
            artifact_type = "document"
        else:
            extracted = temp_path.read_text(errors="ignore")
            content = summarize_document_text(extracted)
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
        await query.message.reply_text(f"Preference updated: response style = {style}")
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

    if action == "tool_time":
        prefs = get_user_preferences(user_id)
        await query.message.reply_text(get_current_time(prefs.timezone))
        return
    if action == "tool_weather":
        context.user_data["awaiting_tool_query"] = "weather"
        await query.message.reply_text("Send a city name for weather.")
        return
    if action == "tool_news":
        context.user_data["awaiting_tool_query"] = "news"
        await query.message.reply_text("Send a topic for news.")
        return
    if action == "tool_calendar":
        text = get_upcoming_events(8)
        await query.message.reply_text(render_card("calendar", text) if UX_PHASE2_ENABLED else text)
        return
    if action == "tool_email":
        text = get_recent_emails(5)
        await query.message.reply_text(render_card("email", text) if UX_PHASE2_ENABLED else text)
        return
    if action == "tool_nest":
        text = get_thermostat_status()
        await query.message.reply_text(text)
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
        reply = generate_agent_response(user_id, text)
        sent = await query.message.reply_text(reply)
        save_message_context(user_id, sent.message_id, text, reply)
        if UX_PHASE1_ENABLED:
            await sent.edit_reply_markup(reply_markup=quick_actions_keyboard(str(sent.message_id)))
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
            out = generate_short_model_response("Summarize this artifact in 5 concise bullets.", artifact["content_text"])
            await query.message.reply_text(out)
            return
        out = generate_short_model_response("Extract actionable next steps from this artifact.", artifact["content_text"])
        await query.message.reply_text(out)
        return

    if action in {"simplify", "summarize", "translate", "retry", "search_web"}:
        ctx = get_message_context(user_id, message_id)
        if not ctx:
            await query.message.reply_text("I could not find context for this action. Please ask again.")
            return

        source_text = ctx["reply_text"]
        original_prompt = ctx["original_prompt"]

        if action == "simplify":
            out = generate_short_model_response("Rewrite this answer in simpler language.", source_text)
        elif action == "summarize":
            out = generate_short_model_response("Summarize this in 3 to 5 bullets.", source_text)
        elif action == "translate":
            prefs = get_user_preferences(user_id)
            out = generate_short_model_response(
                f"Translate this to {prefs.language}. Keep formatting compact.", source_text
            )
        elif action == "retry":
            out = generate_agent_response(user_id, original_prompt, force_web=True)
        else:
            web_results = search_web(original_prompt, 5)
            out = generate_short_model_response(
                "Create a concise answer from these web snippets and include source URLs.",
                web_results,
            )

        sent = await query.message.reply_text(out)
        save_message_context(user_id, sent.message_id, original_prompt, out)
        if UX_PHASE1_ENABLED:
            await sent.edit_reply_markup(reply_markup=quick_actions_keyboard(str(sent.message_id)))
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
        "- Voice notes and file/image understanding\n\n"
        "Try:\n"
        "- 'Summarize my upcoming events'\n"
        "- 'Search latest AI model news'\n"
        "- Upload a PDF and ask questions"
    )


@handler_guard
async def tools_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Choose a tool:", reply_markup=tools_keyboard())


@handler_guard
async def prefs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prefs = get_user_preferences(update.effective_user.id)
    await update.message.reply_text(
        f"Current prefs:\n- style: {prefs.response_style}\n- language: {prefs.language}\n- timezone: {prefs.timezone}\n\n"
        "Tap to update:",
        reply_markup=prefs_keyboard(),
    )


def main():
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    init_storage()

    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("tools", tools_command))
    app.add_handler(CommandHandler("prefs", prefs_command))
    app.add_handler(CommandHandler("reset", reset))

    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot started. Polling...")
    app.run_polling()


if __name__ == "__main__":
    main()
