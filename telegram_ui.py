from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def make_callback(action: str, ctx: str = "") -> str:
    return f"action:{action}|v:1|ctx:{ctx}"


def parse_callback_data(data: str) -> dict[str, str]:
    result = {"action": "", "v": "", "ctx": ""}
    for part in data.split("|"):
        if ":" not in part:
            continue
        key, value = part.split(":", 1)
        if key in result:
            result[key] = value
    if result["action"].startswith("action:"):
        result["action"] = result["action"].split(":", 1)[1]
    return result


def quick_actions_keyboard(ctx: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Search Web", callback_data=make_callback("search_web", ctx)),
                InlineKeyboardButton("Simplify", callback_data=make_callback("simplify", ctx)),
                InlineKeyboardButton("Summarize", callback_data=make_callback("summarize", ctx)),
            ],
            [
                InlineKeyboardButton("Translate", callback_data=make_callback("translate", ctx)),
                InlineKeyboardButton("Retry", callback_data=make_callback("retry", ctx)),
                InlineKeyboardButton("Reset", callback_data=make_callback("reset", ctx)),
            ],
        ]
    )


def tools_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Time", callback_data=make_callback("tool_time")),
                InlineKeyboardButton("Weather", callback_data=make_callback("tool_weather")),
                InlineKeyboardButton("News", callback_data=make_callback("tool_news")),
            ],
            [
                InlineKeyboardButton("Calendar", callback_data=make_callback("tool_calendar")),
                InlineKeyboardButton("Email", callback_data=make_callback("tool_email")),
                InlineKeyboardButton("Nest", callback_data=make_callback("tool_nest")),
            ],
        ]
    )


def prefs_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Style: Short", callback_data=make_callback("pref_style_short")),
                InlineKeyboardButton("Style: Normal", callback_data=make_callback("pref_style_normal")),
                InlineKeyboardButton("Style: Detailed", callback_data=make_callback("pref_style_detailed")),
            ],
            [
                InlineKeyboardButton("Lang: EN", callback_data=make_callback("pref_lang_en")),
                InlineKeyboardButton("Lang: ES", callback_data=make_callback("pref_lang_es")),
                InlineKeyboardButton("Lang: FR", callback_data=make_callback("pref_lang_fr")),
            ],
            [
                InlineKeyboardButton("TZ: PT", callback_data=make_callback("pref_tz_pt")),
                InlineKeyboardButton("TZ: ET", callback_data=make_callback("pref_tz_et")),
                InlineKeyboardButton("TZ: UTC", callback_data=make_callback("pref_tz_utc")),
            ],
        ]
    )


def voice_preview_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("Use", callback_data=make_callback("voice_use")),
            InlineKeyboardButton("Edit", callback_data=make_callback("voice_edit")),
            InlineKeyboardButton("Cancel", callback_data=make_callback("voice_cancel")),
        ]]
    )


def artifact_actions_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("Summarize", callback_data=make_callback("artifact_summarize")),
            InlineKeyboardButton("Extract action items", callback_data=make_callback("artifact_actions")),
        ], [
            InlineKeyboardButton("Ask question", callback_data=make_callback("artifact_ask")),
        ]]
    )


def render_weather_card(text: str) -> str:
    return "Weather Update\n" + text


def render_news_card(text: str) -> str:
    return "News Brief\n" + text


def render_calendar_card(text: str) -> str:
    return "Calendar Snapshot\n" + text


def render_email_card(text: str) -> str:
    return "Inbox Snapshot\n" + text


def render_card(card_type: str, text: str) -> str:
    if card_type == "weather":
        return render_weather_card(text)
    if card_type == "news":
        return render_news_card(text)
    if card_type == "calendar":
        return render_calendar_card(text)
    if card_type == "email":
        return render_email_card(text)
    return text
