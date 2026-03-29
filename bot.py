import os
import logging
import math
import httpx
from datetime import datetime
from zoneinfo import ZoneInfo
import wikipedia
from duckduckgo_search import DDGS
from anthropic import Anthropic
from google_services import get_upcoming_events, search_calendar_events, get_recent_emails, search_emails
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, ContextTypes, filters

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

anthropic = Anthropic()

# Per-user conversation history
conversations: dict[int, list[dict]] = {}

SYSTEM_PROMPT = """You are a helpful personal assistant called Bob. Be concise and direct.
Use tools whenever they will give a better answer than your training data alone."""

TOOLS = [
    {
        "name": "get_current_time",
        "description": "Get the current date and time, optionally in a specific timezone.",
        "input_schema": {
            "type": "object",
            "properties": {
                "timezone": {"type": "string", "description": "IANA timezone name, e.g. 'Europe/London', 'America/New_York', 'Asia/Tokyo'. Defaults to local system time."}
            },
            "required": []
        }
    },
    {
        "name": "get_weather",
        "description": "Get current weather and forecast for a city.",
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "City name, e.g. 'London' or 'New York'"}
            },
            "required": ["city"]
        }
    },
    {
        "name": "web_search",
        "description": "Search the web for current information on any topic.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "max_results": {"type": "integer", "description": "Number of results (default 5)", "default": 5}
            },
            "required": ["query"]
        }
    },
    {
        "name": "get_news",
        "description": "Get latest news articles on a topic.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "News topic"},
                "max_results": {"type": "integer", "description": "Number of articles (default 5)", "default": 5}
            },
            "required": ["query"]
        }
    },
    {
        "name": "wikipedia_search",
        "description": "Search Wikipedia for a summary of a topic.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Topic to look up on Wikipedia"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "calculate",
        "description": "Evaluate a mathematical expression. Supports +, -, *, /, **, sqrt, sin, cos, tan, log, pi, e.",
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "Math expression, e.g. '2 ** 10' or 'sqrt(144)'"}
            },
            "required": ["expression"]
        }
    },
    {
        "name": "get_country_info",
        "description": "Get information about a country: capital, population, region, languages, currency.",
        "input_schema": {
            "type": "object",
            "properties": {
                "country": {"type": "string", "description": "Country name, e.g. 'Germany' or 'Japan'"}
            },
            "required": ["country"]
        }
    },
    {
        "name": "define_word",
        "description": "Get the definition, phonetics, and examples for a word.",
        "input_schema": {
            "type": "object",
            "properties": {
                "word": {"type": "string", "description": "Word to define"}
            },
            "required": ["word"]
        }
    },
    {
        "name": "get_upcoming_events",
        "description": "Get the user's upcoming Google Calendar events.",
        "input_schema": {
            "type": "object",
            "properties": {
                "max_results": {"type": "integer", "description": "Number of events to return (default 10)", "default": 10}
            },
            "required": []
        }
    },
    {
        "name": "search_calendar_events",
        "description": "Search the user's Google Calendar for events matching a query.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search term, e.g. 'dentist' or 'team meeting'"},
                "max_results": {"type": "integer", "description": "Number of results (default 5)", "default": 5}
            },
            "required": ["query"]
        }
    },
    {
        "name": "get_recent_emails",
        "description": "Get the user's most recent emails from Gmail inbox.",
        "input_schema": {
            "type": "object",
            "properties": {
                "max_results": {"type": "integer", "description": "Number of emails to return (default 5)", "default": 5}
            },
            "required": []
        }
    },
    {
        "name": "search_emails",
        "description": "Search the user's Gmail for emails matching a query.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Gmail search query, e.g. 'from:boss@company.com' or 'invoice'"},
                "max_results": {"type": "integer", "description": "Number of results (default 5)", "default": 5}
            },
            "required": ["query"]
        }
    }
]


# --- Tool implementations ---

def get_current_time(timezone: str = "") -> str:
    try:
        tz = ZoneInfo(timezone) if timezone else None
        now = datetime.now(tz)
        tz_label = timezone if timezone else "local"
        return now.strftime(f"%A, %d %B %Y %H:%M:%S ({tz_label})")
    except Exception:
        return f"Unknown timezone '{timezone}'. Use IANA format e.g. 'Europe/London'."

def fetch_weather(city: str) -> str:
    geo = httpx.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": city, "count": 1},
        timeout=10
    ).json()
    if not geo.get("results"):
        return f"Could not find location: {city}"
    result = geo["results"][0]
    lat, lon, name = result["latitude"], result["longitude"], result["name"]
    weather = httpx.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min,weather_code",
            "forecast_days": 3,
            "timezone": "auto"
        },
        timeout=10
    ).json()
    current = weather["current"]
    daily = weather["daily"]
    lines = [
        f"Weather in {name}:",
        f"Now: {current['temperature_2m']}°C (feels like {current['apparent_temperature']}°C), wind {current['wind_speed_10m']} km/h",
        "3-day forecast:"
    ]
    for i in range(3):
        lines.append(f"  {daily['time'][i]}: {daily['temperature_2m_min'][i]}–{daily['temperature_2m_max'][i]}°C")
    return "\n".join(lines)


def search_web(query: str, max_results: int = 5) -> str:
    with DDGS() as ddgs:
        results = list(ddgs.text(query, max_results=max_results))
    if not results:
        return "No results found."
    return "\n\n".join(f"**{r['title']}**\n{r['body']}\n{r['href']}" for r in results)


def get_news(query: str, max_results: int = 5) -> str:
    with DDGS() as ddgs:
        results = list(ddgs.news(query, max_results=max_results))
    if not results:
        return "No news found."
    return "\n\n".join(f"**{r['title']}** ({r['date']})\n{r['body']}\n{r['url']}" for r in results)


def wikipedia_search(query: str) -> str:
    try:
        summary = wikipedia.summary(query, sentences=5, auto_suggest=True)
        page = wikipedia.page(query, auto_suggest=True)
        return f"{summary}\n\nMore: {page.url}"
    except wikipedia.DisambiguationError as e:
        return f"Ambiguous query. Did you mean: {', '.join(e.options[:5])}?"
    except wikipedia.PageError:
        return f"No Wikipedia page found for '{query}'."


def calculate(expression: str) -> str:
    allowed = {
        "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan,
        "log": math.log, "log10": math.log10, "abs": abs, "round": round,
        "pi": math.pi, "e": math.e,
    }
    try:
        result = eval(expression, {"__builtins__": {}}, allowed)
        return str(result)
    except Exception as ex:
        return f"Error: {ex}"


def get_country_info(country: str) -> str:
    response = httpx.get(
        f"https://restcountries.com/v3.1/name/{country}",
        params={"fullText": "false"},
        timeout=10
    )
    if response.status_code != 200:
        return f"Country not found: {country}"
    data = response.json()[0]
    languages = ", ".join(data.get("languages", {}).values())
    currencies = ", ".join(
        f"{v['name']} ({v.get('symbol', '')})"
        for v in data.get("currencies", {}).values()
    )
    return (
        f"**{data['name']['common']}** ({data['name']['official']})\n"
        f"Capital: {', '.join(data.get('capital', ['N/A']))}\n"
        f"Region: {data.get('region')} / {data.get('subregion')}\n"
        f"Population: {data.get('population', 0):,}\n"
        f"Languages: {languages}\n"
        f"Currency: {currencies}"
    )


def define_word(word: str) -> str:
    response = httpx.get(
        f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}",
        timeout=10
    )
    if response.status_code != 200:
        return f"No definition found for '{word}'."
    data = response.json()[0]
    phonetic = data.get("phonetic", "")
    lines = [f"**{word}** {phonetic}"]
    for meaning in data.get("meanings", [])[:3]:
        lines.append(f"\n_{meaning['partOfSpeech']}_")
        for defn in meaning.get("definitions", [])[:2]:
            lines.append(f"• {defn['definition']}")
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
    if name == "get_upcoming_events":
        return get_upcoming_events(tool_input.get("max_results", 10))
    if name == "search_calendar_events":
        return search_calendar_events(tool_input["query"], tool_input.get("max_results", 5))
    if name == "get_recent_emails":
        return get_recent_emails(tool_input.get("max_results", 5))
    if name == "search_emails":
        return search_emails(tool_input["query"], tool_input.get("max_results", 5))
    return "Unknown tool"


# --- Telegram handlers ---

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    if user_id not in conversations:
        conversations[user_id] = []

    conversations[user_id].append({"role": "user", "content": text})
    history = conversations[user_id][-20:]

    while True:
        response = anthropic.messages.create(
            model="claude-opus-4-6",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=history,
        )

        if response.stop_reason == "end_turn":
            reply = next(b.text for b in response.content if b.type == "text")
            conversations[user_id].append({"role": "assistant", "content": response.content})
            await update.message.reply_text(reply)
            break

        if response.stop_reason == "tool_use":
            history.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = run_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result
                    })
            history.append({"role": "user", "content": tool_results})


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conversations[user_id] = []
    await update.message.reply_text(
        "Hi! I'm Bob. I can help with:\n"
        "• Weather\n"
        "• Web search & news\n"
        "• Wikipedia\n"
        "• Calculator\n"
        "• Country info\n"
        "• Dictionary\n\n"
        "Just ask!"
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conversations[user_id] = []
    await update.message.reply_text("Conversation reset.")


def main():
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot started. Polling...")
    app.run_polling()


if __name__ == "__main__":
    main()
