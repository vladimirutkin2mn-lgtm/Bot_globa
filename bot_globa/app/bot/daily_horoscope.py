"""A privacy-free, deterministic daily digest for all twelve zodiac signs."""

from datetime import date
from types import MappingProxyType

from app.domain.daily_horoscope import (
    DailyHoroscopeMode,
    DailyHoroscopePreferenceView,
    daily_horoscope_enabled,
    moscow_time_difference_for_timezone,
)

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

_THEMES = (
    "сначала прояснить главное, а уже затем действовать",
    "оставить место для паузы и проверить свои границы",
    "выбрать один посильный шаг вместо попытки решить всё сразу",
    "заметить повторяющийся сценарий и попробовать другой ответ",
    "отделить чужие ожидания от собственных приоритетов",
    "говорить конкретнее и не додумывать за другого человека",
    "сохранить энергию для того, что действительно можно изменить",
)

_SIGNS = (
    ("♈", "Овен", "направьте импульс в один ясный следующий шаг"),
    ("♉", "Телец", "проверьте, что даёт устойчивость, а что лишь удерживает на месте"),
    ("♊", "Близнецы", "один прямой разговор окажется полезнее нескольких догадок"),
    ("♋", "Рак", "назовите свою потребность до того, как защищать её молчанием"),
    ("♌", "Лев", "ищите признание в собственном решении, а не только в реакции других"),
    ("♍", "Дева", "достаточно улучшить одну деталь — идеального момента ждать не нужно"),
    ("♎", "Весы", "сравните варианты по своим критериям, а не по желанию всем угодить"),
    ("♏", "Скорпион", "не спешите с выводом: сначала отделите факт от интерпретации"),
    ("♐", "Стрелец", "проверьте направление маленьким экспериментом"),
    ("♑", "Козерог", "пересмотрите нагрузку и оставьте только обязательное"),
    ("♒", "Водолей", "необычная идея станет полезнее после одного практического шага"),
    ("♓", "Рыбы", "дайте интуиции форму: запишите чувство и возможное действие отдельно"),
)


def render_daily_horoscope(for_date: date) -> str:
    """Render the same short, non-personal digest for every user on a given date."""

    theme = _THEMES[for_date.toordinal() % len(_THEMES)]
    lines = [
        f"Гороскоп на сегодня · {for_date:%d.%m.%Y}",
        f"Общая тема дня: {theme}.",
        "",
    ]
    lines.extend(f"{emoji} {name} — {advice}." for emoji, name, advice in _SIGNS)
    # The digest is the one message this product sends unprompted, and it now goes to the
    # whole active base. Its framing as entertainment travels with the text rather than
    # living on the screen the user opened it from.
    lines.extend(("", "Это общий развлекательный прогноз."))
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
