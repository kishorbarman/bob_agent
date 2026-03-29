from dataclasses import dataclass

from storage import get_user_pref_row, update_user_pref


@dataclass
class UserPreferences:
    user_id: int
    timezone: str = "America/Los_Angeles"
    language: str = "en"
    response_style: str = "normal"
    selected_model: str = "models/gemini-3.1-flash-lite-preview"


def get_user_preferences(user_id: int) -> UserPreferences:
    row = get_user_pref_row(user_id)
    return UserPreferences(
        user_id=user_id,
        timezone=row["timezone"],
        language=row["language"],
        response_style=row["response_style"],
        selected_model=row["selected_model"],
    )


def set_timezone(user_id: int, timezone: str) -> None:
    update_user_pref(user_id, "timezone", timezone)


def set_language(user_id: int, language: str) -> None:
    update_user_pref(user_id, "language", language)


def set_response_style(user_id: int, style: str) -> None:
    update_user_pref(user_id, "response_style", style)


def set_selected_model(user_id: int, model: str) -> None:
    update_user_pref(user_id, "selected_model", model)
