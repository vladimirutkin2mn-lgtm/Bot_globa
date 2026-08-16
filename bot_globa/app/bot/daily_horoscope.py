"""Daily horoscope copy rendered from one calculated sky snapshot per date."""

from datetime import date
from types import MappingProxyType

from app.domain.daily_horoscope import (
    DailyHoroscopeMode,
    DailyHoroscopePreferenceView,
    daily_horoscope_enabled,
    moscow_time_difference_for_timezone,
)
from app.services.daily_sky import DailyHoroscopeSnapshot, SIGN_LABELS, build_daily_horoscope

MODE_CONFIRMATIONS = MappingProxyType(
    {
        DailyHoroscopeMode.MORNING: (
            "Готово. Гороскоп будет приходить каждый день в 08:00 по вашему времени."
        ),
        DailyHoroscopeMode.EVENING: (
            "Готово. Гороскоп будет приходить каждый день в 08:00 по вашему времени."
        ),
        DailyHoroscopeMode.ON_REQUEST: (
            "Готово. Ежедневная отправка отключена — гороскоп останется доступен здесь."
        ),
        DailyHoroscopeMode.DISABLED: (
            "Готово. Ежедневная отправка отключена — гороскоп останется доступен здесь."
        ),
    }
)

TIMEZONE_PROMPT = (
    "Разница с Москвой\n\n"
    "Напишите одним сообщением, на сколько часов ваше время отличается от московского.\n\n"
    "Москва — 0\n"
    "Екатеринбург — +2\n"
    "Калининград — -1\n\n"
    "Если разница меняется летом и зимой, обновите её здесь."
)

TIMEZONE_ERROR = (
    "Не получилось распознать разницу с Москвой. Отправьте целое число от -15 до +11, "
    "например: 0, +2 или -1."
)


def render_daily_horoscope(value: date | DailyHoroscopeSnapshot) -> str:
    """Render one bounded digest shared by every user for the same calculated snapshot."""

    snapshot = build_daily_horoscope(value) if isinstance(value, date) else value
    lines = [
        f"Гороскоп на сегодня · {snapshot.forecast_date:%d.%m.%Y}",
        f"🌙 Тема дня: {snapshot.theme}.",
        "",
    ]
    for item in snapshot.signs:
        emoji, name = SIGN_LABELS[item.sign]
        lines.append(f"{emoji} {name} — {item.text}")
    lines.extend(("", "Это общий прогноз по знаку; персональный учитывает вашу натальную карту."))
    return "\n".join(lines)


def render_daily_settings(preference: DailyHoroscopePreferenceView) -> str:
    """Render the saved delivery switch and Moscow-relative clock in user language."""

    status = "включена" if daily_horoscope_enabled(preference.mode) else "отключена"
    difference = moscow_time_difference_for_timezone(preference.timezone)
    timezone_label = (
        _format_time_difference(difference)
        if difference is not None
        else f"сохранённый часовой пояс: {preference.timezone}"
    )
    return (
        "Настройки гороскопа\n\n"
        f"Ежедневная отправка: {status}.\n"
        "Время отправки: 08:00 по вашему времени.\n"
        f"Разница с Москвой: {timezone_label}."
    )


def render_timezone_saved(preference: DailyHoroscopePreferenceView) -> str:
    """Confirm a clock update without implying delivery is enabled after an opt-out."""

    difference = moscow_time_difference_for_timezone(preference.timezone)
    timezone_label = _format_time_difference(difference) if difference is not None else "сохранена"
    if daily_horoscope_enabled(preference.mode):
        return (
            f"Готово. Разница с Москвой — {timezone_label}. "
            "Гороскоп будет приходить в 08:00 по вашему времени."
        )
    return f"Готово. Разница с Москвой — {timezone_label}. Она применится после включения."


def _format_time_difference(difference: int) -> str:
    if difference > 0:
        return f"+{difference} ч"
    if difference < 0:
        return f"−{abs(difference)} ч"
    return "0 ч"
