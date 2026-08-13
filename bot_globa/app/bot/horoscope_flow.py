"""The astrologer's Telegram contract: copy, topics and birth-profile intake keyboards.

The astrologer reuses `ReadingFlow` for everything a reading persona shares — namespace,
result keyboards, history, crisis handoff — and adds the screens that only a birth-data
persona needs. Behavior lives in `app.bot.horoscope_handlers`.
"""

from collections.abc import Sequence
from types import MappingProxyType

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.persona_flow import CANCEL_BUTTON, MENU_BUTTON, PersonaFlowTexts, ReadingFlow
from app.bot.safety_intake import SafetyIntake
from app.bot.states import HoroscopeStates

NAMESPACE = "astro"

HOROSCOPE_TOPIC_LABELS = MappingProxyType(
    {
        "natal_profile": "Натальная карта",
        "week_forecast": "Прогноз на неделю",
        "month_forecast": "Прогноз на месяц",
        "decision": "Выбор",
        "love": "Отношения",
    }
)
HOROSCOPE_TOPIC_EXAMPLES = MappingProxyType(
    {
        "natal_profile": "какие мои сильные стороны и повторяющиеся темы видны в карте",
        "week_forecast": "на что обратить внимание на этой неделе в работе и отношениях",
        "month_forecast": "какие темы месяца стоит учитывать при планировании",
        "decision": "какие мои привычные реакции важно учесть перед решением",
        "love": "как мои привычные способы сближения проявляются в отношениях",
    }
)

CONSENT = (
    "Для персональной карты нужны дата и место рождения; время — если знаете. Место "
    "используется для расчёта координат и часового пояса. Данные хранятся в зашифрованном "
    "виде и их можно удалить в любой момент.\n\n"
    "Для поиска места название города передаётся внешнему геокодеру; остальные данные "
    "ему не отправляются."
)
CONSENT_DECLINED = (
    "Без данных рождения натальную карту рассчитать нельзя. Остальные направления доступны "
    "из главного меню."
)
BIRTH_DATE_PROMPT = "Введите дату рождения в формате ДД.ММ.ГГГГ, например 12.07.1990."
BIRTH_DATE_INVALID = "Не удалось разобрать дату. Нужен формат ДД.ММ.ГГГГ и дата не в будущем."
BIRTH_PLACE_PROMPT = "Введите город рождения. Если нужного города нет, выберите ближайший крупный."
BIRTH_PLACE_INVALID = "Название города должно быть от 2 до 200 символов."
BIRTH_PLACE_EMPTY = "Ничего не нашлось. Попробуйте другое написание или ближайший крупный город."
BIRTH_PLACE_UNAVAILABLE = "Поиск места сейчас недоступен. Попробуйте позже."
BIRTH_TIME_PROMPT = (
    "Введите время рождения в формате ЧЧ:ММ. Без точного времени дома и асцендент не "
    "рассчитываются — тогда нажмите «Не знаю время»."
)
BIRTH_TIME_INVALID = "Не удалось разобрать время. Нужен формат ЧЧ:ММ, например 14:30."
BIRTH_MOMENT_INVALID = (
    "Такого местного времени в этом часовом поясе не существует. Уточните время или место."
)
BIRTH_TIME_AMBIGUOUS = (
    "В эту ночь часы переводили назад, поэтому {clock} было дважды. От выбора зависят дома "
    "и асцендент — укажите, какой это был час."
)
TIME_SUMMER_BUTTON = "{clock} — летнее время ({offset})"
TIME_WINTER_BUTTON = "{clock} — зимнее время ({offset})"
PROFILE_SAVED = "Данные рождения сохранены. Выберите тему разбора."
PROFILE_MISSING = "Данные рождения не найдены. Заполните их заново."
PROFILE_TITLE = "Ваши данные рождения:"
PROFILE_DELETED = "Данные рождения и согласие удалены."
TIME_UNKNOWN_BUTTON = "Не знаю время"
CONSENT_ACCEPT_BUTTON = "Сохранить и продолжить"
CONSENT_DECLINE_BUTTON = "Не сейчас"
PROFILE_BUTTON = "Данные рождения"
PROFILE_EDIT_BUTTON = "Ввести заново"
PROFILE_DELETE_BUTTON = "Удалить данные рождения"

HOROSCOPE_FLOW = ReadingFlow(
    persona_code="astrologer",
    namespace=NAMESPACE,
    states=HoroscopeStates,
    topic_labels=HOROSCOPE_TOPIC_LABELS,
    topic_examples=HOROSCOPE_TOPIC_EXAMPLES,
    texts=PersonaFlowTexts(
        welcome="Что хотите прояснить с помощью персональной карты?",
        processing=(
            "Вопрос принят. Фиксирую расчётные опоры и собираю разбор — обычно это "
            "занимает до 30 секунд."
        ),
        opening="Открываю сохранённый разбор…",
        already_processing="Этот разбор уже обрабатывается. Откройте его немного позже.",
        unavailable="Астролог временно недоступен. Начните новый разбор позже.",
        failed="Не удалось завершить разбор. Расчёт сохранён, поэтому попытку можно повторить.",
        history_title="Ваши последние готовые разборы:",
        history_empty="Готовых разборов пока нет.",
        history_fallback="Разбор",
        locked="Разбор готов. Откройте полный разбор за {price}.",
        unlock_failed="Не удалось открыть полный разбор. Списание отменено или возвращено.",
        unlock_button="Открыть полный разбор — {price}",
        new_button="Новый разбор",
    ),
)


def horoscope_safety_intake() -> SafetyIntake:
    return HOROSCOPE_FLOW.safety_intake()


def callback(*parts: str) -> str:
    return HOROSCOPE_FLOW.callback(*parts)


def consent_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=CONSENT_ACCEPT_BUTTON,
                    callback_data=callback("consent", "grant"),
                )
            ],
            [
                InlineKeyboardButton(
                    text=CONSENT_DECLINE_BUTTON,
                    callback_data=callback("consent", "decline"),
                )
            ],
        ]
    )


def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=CANCEL_BUTTON, callback_data=callback("cancel"))],
        ]
    )


def place_choice_keyboard(labels: Sequence[str]) -> InlineKeyboardMarkup:
    """Reference a candidate by index: a place label would not fit in 64 callback bytes."""
    rows = [
        [InlineKeyboardButton(text=label, callback_data=callback("place", "pick", str(index)))]
        for index, label in enumerate(labels)
    ]
    rows.append(
        [InlineKeyboardButton(text="Искать заново", callback_data=callback("place", "retry"))]
    )
    rows.append([InlineKeyboardButton(text=CANCEL_BUTTON, callback_data=callback("cancel"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def birth_time_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=TIME_UNKNOWN_BUTTON,
                    callback_data=callback("time", "unknown"),
                )
            ],
            [InlineKeyboardButton(text=CANCEL_BUTTON, callback_data=callback("cancel"))],
        ]
    )


def format_offset(minutes: int) -> str:
    """Render a UTC offset the way a user reads it, not as a signed integer."""
    sign = "+" if minutes >= 0 else "−"
    hours, rest = divmod(abs(minutes), 60)
    return f"UTC{sign}{hours}" if rest == 0 else f"UTC{sign}{hours}:{rest:02d}"


def time_choice_keyboard(offsets: Sequence[int], clock: str) -> InlineKeyboardMarkup:
    """One button per repeated hour; the larger offset is the summer one."""
    ordered = sorted(offsets, reverse=True)
    templates = [TIME_SUMMER_BUTTON, TIME_WINTER_BUTTON]
    rows = [
        [
            InlineKeyboardButton(
                text=template.format(clock=clock, offset=format_offset(minutes)),
                callback_data=callback("offset", "pick", str(minutes)),
            )
        ]
        for template, minutes in zip(templates, ordered, strict=False)
    ]
    rows.append(
        [
            InlineKeyboardButton(
                text=TIME_UNKNOWN_BUTTON,
                callback_data=callback("time", "unknown"),
            )
        ]
    )
    rows.append([InlineKeyboardButton(text=CANCEL_BUTTON, callback_data=callback("cancel"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def profile_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=PROFILE_EDIT_BUTTON,
                    callback_data=callback("profile", "edit"),
                )
            ],
            [
                InlineKeyboardButton(
                    text=PROFILE_DELETE_BUTTON,
                    callback_data=callback("profile", "delete"),
                )
            ],
            [InlineKeyboardButton(text=MENU_BUTTON, callback_data=callback("menu"))],
        ]
    )


def topics_keyboard() -> InlineKeyboardMarkup:
    rows = list(HOROSCOPE_FLOW.topics_keyboard().inline_keyboard)
    rows.insert(
        len(HOROSCOPE_TOPIC_LABELS),
        [InlineKeyboardButton(text=PROFILE_BUTTON, callback_data=callback("profile"))],
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
