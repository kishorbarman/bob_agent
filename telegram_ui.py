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
                InlineKeyboardButton("Elaborate", callback_data=make_callback("elaborate", ctx)),
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
                InlineKeyboardButton("Calendar", callback_data=make_callback("tool_calendar")),
            ],
            [
                InlineKeyboardButton("Research", callback_data=make_callback("toolcat_research")),
                InlineKeyboardButton("Comms", callback_data=make_callback("toolcat_comms")),
            ],
            [
                InlineKeyboardButton("Home", callback_data=make_callback("toolcat_home")),
                InlineKeyboardButton("Utilities", callback_data=make_callback("toolcat_utilities")),
            ],
            [
                InlineKeyboardButton("Media", callback_data=make_callback("toolcat_media")),
                InlineKeyboardButton("All Tools", callback_data=make_callback("tools_all")),
            ],
        ]
    )


def tools_category_keyboard(category: str) -> InlineKeyboardMarkup:
    if category == "research":
        rows = [
            [InlineKeyboardButton("Web Search", callback_data=make_callback("tool_web_search"))],
            [InlineKeyboardButton("News", callback_data=make_callback("tool_news"))],
            [InlineKeyboardButton("Wikipedia", callback_data=make_callback("tool_wikipedia"))],
            [InlineKeyboardButton("Country Info", callback_data=make_callback("tool_country"))],
            [InlineKeyboardButton("Dictionary", callback_data=make_callback("tool_define"))],
        ]
    elif category == "comms":
        rows = [
            [InlineKeyboardButton("Upcoming Events", callback_data=make_callback("tool_calendar"))],
            [InlineKeyboardButton("Search Calendar", callback_data=make_callback("tool_calendar_search"))],
            [InlineKeyboardButton("Recent Emails", callback_data=make_callback("tool_email"))],
            [InlineKeyboardButton("Search Emails", callback_data=make_callback("tool_email_search"))],
        ]
    elif category == "home":
        rows = [
            [InlineKeyboardButton("Nest Devices", callback_data=make_callback("tool_nest_devices"))],
            [InlineKeyboardButton("Thermostat Status", callback_data=make_callback("tool_nest"))],
            [InlineKeyboardButton("Camera Status", callback_data=make_callback("tool_camera_status"))],
            [InlineKeyboardButton("Camera Snapshot", callback_data=make_callback("tool_camera_snapshot"))],
            [InlineKeyboardButton("Doorbell Snapshot", callback_data=make_callback("tool_doorbell_snapshot"))],
        ]
    elif category == "utilities":
        rows = [
            [InlineKeyboardButton("Time", callback_data=make_callback("tool_time"))],
            [InlineKeyboardButton("Weather", callback_data=make_callback("tool_weather"))],
            [InlineKeyboardButton("Calculator", callback_data=make_callback("tool_calculate"))],
        ]
    elif category == "media":
        rows = [
            [InlineKeyboardButton("How Media Works", callback_data=make_callback("tool_media_help"))],
        ]
    else:
        rows = []

    rows.append([InlineKeyboardButton("Back", callback_data=make_callback("tools_home"))])
    return InlineKeyboardMarkup(rows)


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


def style_keyboard(current_style: str) -> InlineKeyboardMarkup:
    short_label = "Short (current)" if current_style == "short" else "Short"
    normal_label = "Normal (current)" if current_style == "normal" else "Normal"
    detailed_label = "Detailed (current)" if current_style == "detailed" else "Detailed"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(short_label, callback_data=make_callback("pref_style_short"))],
            [InlineKeyboardButton(normal_label, callback_data=make_callback("pref_style_normal"))],
            [InlineKeyboardButton(detailed_label, callback_data=make_callback("pref_style_detailed"))],
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


def model_keyboard(current_model: str) -> InlineKeyboardMarkup:
    flash = "Flash-Lite"
    pro = "Pro"
    if current_model == "models/gemini-3.1-flash-lite-preview":
        flash = "Flash-Lite ✓"
    if current_model == "models/gemini-3.1-pro-preview":
        pro = "Pro ✓"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(flash, callback_data=make_callback("model_flash_lite"))],
            [InlineKeyboardButton(pro, callback_data=make_callback("model_pro"))],
        ]
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
