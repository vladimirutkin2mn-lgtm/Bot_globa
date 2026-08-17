"""High-interaction, privacy-safe viral games for Telegram groups.

The mechanics in this module never enumerate chat members or read ordinary group
messages. People opt in through callbacks, and the small participant set is encoded in
the callback itself so collective games survive worker restarts without new storage.
"""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from html import escape
from typing import Any

import astronomy
from aiogram import Bot, F
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot import group_compatibility_handlers as compatibility
from app.bot import group_handlers, group_social_handlers
from app.bot.scene_media import send_art
from app.bot.tarot_art import card_art
from app.domain.natal_chart import NatalBody, NatalChartResult, ZodiacSign
from app.domain.reading import SymbolOrientation
from app.domain.synastry import CompatibilityContext, calculate_synastry
from app.domain.tarot import RWS_78_V1, TarotCard
from app.services.birth_profile import BirthProfileService
from app.services.onboarding import OnboardingService

_GROUP_CHAT = F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP})
_GROUP_TYPES = {ChatType.GROUP, ChatType.SUPERGROUP}
_INSTALL_MARKERS: set[str] = set()
_PREVIOUS_PARTY_MENU: Callable[[], InlineKeyboardMarkup] | None = None
_MAX_COUPLE_PLAYERS = 5
_SEANCE_THRESHOLD = 3

_ZODIAC_RU = tuple(compatibility._ZODIAC_RU[sign] for sign in ZodiacSign)
_TRANSIT_BODIES: tuple[tuple[NatalBody, Any, str, int], ...] = (
    (NatalBody.SUN, astronomy.Body.Sun, "Солнце", 2),
    (NatalBody.MOON, astronomy.Body.Moon, "Луна", 1),
    (NatalBody.VENUS, astronomy.Body.Venus, "Венера", 2),
    (NatalBody.MARS, astronomy.Body.Mars, "Марс", 2),
    (NatalBody.JUPITER, astronomy.Body.Jupiter, "Юпитер", 3),
)
_NATAL_TARGETS: tuple[tuple[NatalBody, str], ...] = (
    (NatalBody.SUN, "Солнцу"),
    (NatalBody.MOON, "Луне"),
    (NatalBody.VENUS, "Венере"),
    (NatalBody.MARS, "Марсу"),
)
_ASPECTS: tuple[tuple[float, str, int, float], ...] = (
    (0.0, "в соединении с", 3, 8.0),
    (60.0, "в секстиле к", 2, 5.0),
    (90.0, "в квадрате к", -2, 6.0),
    (120.0, "в тригоне к", 3, 6.0),
    (180.0, "в оппозиции к", -3, 8.0),
)
_ADVICE_BY_ELEMENT: dict[str, tuple[str, ...]] = {
    "fire": (
        "Сегодня полезнее действовать, чем бесконечно согласовывать. Оставьте место импровизации.",
        "Энергии много: направьте её в один смелый план, а не в пять параллельных споров.",
    ),
    "earth": (
        "Лучше всего сработает конкретика: один план, один ответственный, один следующий шаг.",
        "Не усложняйте. Сегодня космос любит простые решения, сроки и здравый смысл.",
    ),
    "air": (
        "Разговор сегодня важнее догадок. Спросите прямо то, что обычно обсуждаете намёками.",
        "Хороший день для идей и неожиданных связей. Не отвергайте странную мысль слишком быстро.",
    ),
    "water": (
        "Не игнорируйте настроение группы: сегодня интонация может быть важнее формулировки.",
        "Если спор заходит в тупик, сначала поймите эмоцию, а уже потом возвращайтесь к аргументам.",
    ),
}
_SEANCE_MESSAGES = (
    "В этом чате назревает решение, которое сначала покажется слишком спонтанным.",
    "Скоро кто-то скажет фразу, которую остальные ещё долго будут цитировать.",
    "У группы есть один незакрытый вопрос. Ответ появится после неожиданного разговора.",
    "Ближайший хороший сюжет начнётся не по плану — и именно поэтому запомнится.",
    "Кто-то здесь недооценивает идею, которая ещё вернётся в разговор.",
)


@dataclass(frozen=True, slots=True)
class CosmicEnergy:
    score: int
    reason: str


@dataclass(frozen=True, slots=True)
class CosmicAdvice:
    mercury_retrograde: bool
    mercury_sign: str
    moon_sign: str
    text: str


@dataclass(frozen=True, slots=True)
class TarotYesNo:
    card: TarotCard
    orientation: SymbolOrientation
    answer: str
    reason: str


def _digest(*parts: object) -> bytes:
    return hashlib.sha256(":".join(str(part) for part in parts).encode()).digest()


def _stable_card(namespace: str, *parts: object) -> TarotCard:
    seed = _digest(namespace, *parts)
    return RWS_78_V1.cards[int.from_bytes(seed[:4], "big") % len(RWS_78_V1.cards)]


def _to_base36(value: int) -> str:
    if value <= 0:
        raise ValueError("Telegram user id must be positive")
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    digits: list[str] = []
    while value:
        value, remainder = divmod(value, 36)
        digits.append(alphabet[remainder])
    return "".join(reversed(digits))


def _from_base36(value: str) -> int:
    parsed = int(value, 36)
    if parsed <= 0:
        raise ValueError("Telegram user id must be positive")
    return parsed


def _encode_users(user_ids: tuple[int, ...] | list[int]) -> str:
    normalized = tuple(sorted(set(user_ids)))
    return ".".join(_to_base36(user_id) for user_id in normalized)


def _decode_users(payload: str) -> tuple[int, ...]:
    if not payload:
        return ()
    return tuple(sorted({_from_base36(part) for part in payload.split(".") if part}))


def couple_pair_for_day(chat_id: int, user_ids: tuple[int, ...], for_date: date) -> tuple[int, int]:
    players = tuple(sorted(set(user_ids)))
    if not 2 <= len(players) <= _MAX_COUPLE_PLAYERS:
        raise ValueError("couple pool must contain two to five participants")
    ranked = sorted(
        players,
        key=lambda user_id: _digest("group-couple-v1", chat_id, for_date.isoformat(), user_id),
    )
    return ranked[0], ranked[1]


def tarot_yes_no_for_question(
    chat_id: int,
    user_id: int,
    question: str,
    for_date: date,
) -> TarotYesNo:
    normalized = " ".join(question.casefold().split())
    if not normalized:
        raise ValueError("question is required")
    seed = _digest("group-taro-yes-no-v1", chat_id, user_id, for_date.isoformat(), normalized)
    card = RWS_78_V1.cards[int.from_bytes(seed[:4], "big") % len(RWS_78_V1.cards)]
    orientation = SymbolOrientation.REVERSED if seed[4] & 1 else SymbolOrientation.UPRIGHT
    if orientation is SymbolOrientation.UPRIGHT:
        return TarotYesNo(card, orientation, "ДА", card.upright_theme)
    return TarotYesNo(card, orientation, "НЕТ", card.reversed_theme)


def _astro_time(for_date: date) -> Any:
    return astronomy.Time.Make(for_date.year, for_date.month, for_date.day, 12, 0, 0.0)


def _longitude(body: Any, astro_time: Any) -> float:
    vector = astronomy.GeoVector(body, astro_time, True)
    return float(astronomy.Ecliptic(vector).elon) % 360.0


def _signed_angle(value: float) -> float:
    return (value + 540.0) % 360.0 - 180.0


def _angular_distance(first: float, second: float) -> float:
    return abs((first - second + 180.0) % 360.0 - 180.0)


def _sign_name(longitude: float) -> str:
    return _ZODIAC_RU[int(longitude % 360.0) // 30]


def cosmic_energy_for_day(chart: NatalChartResult, for_date: date) -> CosmicEnergy:
    """Score current transit support against a natal chart for one UTC day."""

    astro_time = _astro_time(for_date)
    natal = {position.body: position.longitude_millidegrees / 1000.0 for position in chart.planets}
    score = 55
    strongest: tuple[int, str] | None = None
    for _body, engine_body, transit_name, weight in _TRANSIT_BODIES:
        transit_longitude = _longitude(engine_body, astro_time)
        for target_body, target_name in _NATAL_TARGETS:
            target_longitude = natal.get(target_body)
            if target_longitude is None:
                continue
            separation = _angular_distance(transit_longitude, target_longitude)
            aspect = min(_ASPECTS, key=lambda item: abs(separation - item[0]))
            angle, aspect_name, value, maximum_orb = aspect
            if abs(separation - angle) > maximum_orb:
                continue
            contribution = value * weight
            score += contribution
            reason = f"{transit_name} {aspect_name} натальному {target_name}"
            if strongest is None or abs(contribution) > abs(strongest[0]):
                strongest = contribution, reason
    bounded = max(35, min(95, score))
    if strongest is None:
        moon_sign = _sign_name(_longitude(astronomy.Body.Moon, astro_time))
        return CosmicEnergy(bounded, f"Луна в знаке {moon_sign}: день без явного перевеса")
    return CosmicEnergy(bounded, strongest[1])


def cosmic_advice_for_day(for_date: date) -> CosmicAdvice:
    astro_time = _astro_time(for_date)
    mercury = _longitude(astronomy.Body.Mercury, astro_time)
    mercury_before = _longitude(astronomy.Body.Mercury, astro_time.AddDays(-0.5))
    mercury_after = _longitude(astronomy.Body.Mercury, astro_time.AddDays(0.5))
    retrograde = _signed_angle(mercury_after - mercury_before) < 0.0
    moon = _longitude(astronomy.Body.Moon, astro_time)
    mercury_sign = _sign_name(mercury)
    moon_sign = _sign_name(moon)
    if retrograde:
        text = (
            "Меркурий ретроградный: перепроверьте договорённости, не спешите с выводами "
            "и оставляйте людям шанс уточнить, что они имели в виду."
        )
    else:
        moon_index = int(moon % 360.0) // 30
        element = ("fire", "earth", "air", "water")[moon_index % 4]
        options = _ADVICE_BY_ELEMENT[element]
        seed = _digest("group-advice-v1", for_date.isoformat(), moon_sign, mercury_sign)
        text = options[seed[0] % len(options)]
    return CosmicAdvice(retrograde, mercury_sign, moon_sign, text)


def _couple_keyboard(user_ids: tuple[int, ...]) -> InlineKeyboardMarkup:
    payload = _encode_users(user_ids)
    rows: list[list[InlineKeyboardButton]] = []
    if len(user_ids) < _MAX_COUPLE_PLAYERS:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"💘 Участвовать · {len(user_ids)}/{_MAX_COUPLE_PLAYERS}",
                    callback_data=f"v:c:{payload}",
                )
            ]
        )
    if len(user_ids) >= 2:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🔮 Выбрать кармическую пару",
                    callback_data=f"v:C:{payload}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="← К играм", callback_data="group:party:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _seance_keyboard(user_ids: tuple[int, ...]) -> InlineKeyboardMarkup:
    payload = _encode_users(user_ids)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"🕯 Присоединиться · {len(user_ids)}/{_SEANCE_THRESHOLD}",
                    callback_data=f"v:s:{payload}",
                )
            ],
            [InlineKeyboardButton(text="← К играм", callback_data="group:party:menu")],
        ]
    )


def _duel_keyboard(challenger_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⚔️ Принять вызов",
                    callback_data=f"v:d:{_to_base36(challenger_id)}",
                )
            ],
            [InlineKeyboardButton(text="← К играм", callback_data="group:party:menu")],
        ]
    )


def _retry_keyboard(
    bot_username: str | None,
    *,
    retry_callback: str,
    missing_names: tuple[str, ...],
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if bot_username:
        for name in missing_names:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"🪐 {name}: заполнить астропрофиль",
                        url=f"https://t.me/{bot_username.removeprefix('@')}?start=astro",
                    )
                ]
            )
    rows.append([InlineKeyboardButton(text="🔄 Проверить снова", callback_data=retry_callback)])
    rows.append([InlineKeyboardButton(text="← К играм", callback_data="group:party:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _personal_tarot_keyboard(bot_username: str | None) -> InlineKeyboardMarkup | None:
    if not bot_username:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔮 Личный расклад",
                    url=group_handlers.private_deep_link(bot_username, "tarot"),
                )
            ]
        ]
    )


def _viral_party_menu() -> InlineKeyboardMarkup:
    if _PREVIOUS_PARTY_MENU is None:
        raise RuntimeError("viral party menu is not installed")
    current = _PREVIOUS_PARTY_MENU()
    rows = [list(row) for row in current.inline_keyboard]
    insert_at = 1 if rows and any(button.callback_data == "gcu:open" for button in rows[0]) else 0
    rows[insert_at:insert_at] = [
        [
            InlineKeyboardButton(text="💘 Кармическая пара", callback_data="v:o:c"),
            InlineKeyboardButton(text="⚔️ Астро-дуэль", callback_data="v:o:d"),
        ],
        [InlineKeyboardButton(text="🕯 Спиритический сеанс", callback_data="v:o:s")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _bot_username(bot: Bot) -> str | None:
    return (await bot.get_me()).username


def _group_message(callback: CallbackQuery) -> Message | None:
    message = callback.message
    if isinstance(message, Message) and message.chat.type in _GROUP_TYPES:
        return message
    return None


async def group_couple(message: Message) -> None:
    await message.answer(
        "💘 <b>Кармическая пара дня</b>\n\n"
        "Numa выберет двоих только среди добровольцев. Нажимая «Участвовать», вы "
        "разрешаете использовать сохранённый астропрофиль для этого группового результата.\n\n"
        "Нужно минимум два человека.",
        reply_markup=_couple_keyboard(()),
    )


async def _send_duel_lobby(message: Message, challenger_id: int, challenger_name: str) -> None:
    await message.answer(
        f"⚔️ <b>{escape(challenger_name)} вызывает чат на Астро-дуэль</b>\n\n"
        "Кто принимает? Победителя определят сегодняшние транзиты к вашим натальным картам.\n\n"
        "Нажатие кнопки означает согласие использовать сохранённый астропрофиль для этой дуэли.",
        reply_markup=_duel_keyboard(challenger_id),
    )


async def astro_duel_entry(message: Message) -> None:
    author = message.from_user
    if author is None:
        return
    await _send_duel_lobby(message, author.id, author.full_name)


async def group_seance(message: Message) -> None:
    await message.answer(
        "🕯 <b>Спиритический сеанс</b>\n\n"
        f"Чтобы Numa открыла послание для группы, нужны {_SEANCE_THRESHOLD} разных участника.\n"
        "Каждый должен коснуться круга сам.",
        reply_markup=_seance_keyboard(()),
    )


async def group_advice(message: Message) -> None:
    advice = cosmic_advice_for_day(message.date.date())
    mercury_motion = "ретроградный" if advice.mercury_retrograde else "прямой"
    await message.answer(
        "🪐 <b>Космический советник</b>\n\n"
        f"☿ Меркурий — {advice.mercury_sign}, {mercury_motion}\n"
        f"☾ Луна — {advice.moon_sign}\n\n"
        f"{advice.text}\n\n"
        "<em>Игровая астрологическая рекомендация.</em>"
    )


async def group_taro_yes_no(message: Message, bot: Bot) -> None:
    text = message.text or ""
    parts = text.split(maxsplit=1)
    if len(parts) != 2 or not parts[1].strip():
        await message.answer(
            "🎱 <b>Таро-рулетка Да/Нет</b>\n\n"
            "Напишите вопрос после команды:\n"
            "<code>/taro Стоит ли сегодня соглашаться на эту авантюру?</code>"
        )
        return
    question = parts[1].strip()
    if len(question) > 240:
        await message.answer("Сделайте вопрос короче — до 240 символов.")
        return
    author = message.from_user
    if author is None:
        return
    result = tarot_yes_no_for_question(message.chat.id, author.id, question, message.date.date())
    orientation = "перевёрнутая" if result.orientation is SymbolOrientation.REVERSED else "прямая"
    answer = (
        "🎱 <b>Таро-рулетка</b>\n\n"
        f"Вопрос: <i>{escape(question)}</i>\n\n"
        f"<b>{result.answer}</b>\n"
        f"{result.card.name_ru} · {orientation}\n"
        f"Почему: {result.reason}.\n\n"
        "<em>Это игра. Решения о здоровье, деньгах и безопасности не стоит отдавать рулетке.</em>"
    )
    await send_art(
        bot,
        message.chat.id,
        card_art(result.card.code),
        answer,
        reply_markup=_personal_tarot_keyboard(await _bot_username(bot)),
    )


async def _render_couple(
    message: Message,
    bot: Bot,
    onboarding: OnboardingService,
    birth_profile_service: BirthProfileService,
    players: tuple[int, ...],
) -> None:
    first_id, second_id = couple_pair_for_day(message.chat.id, players, message.date.date())
    first_name, second_name = await compatibility._pair_names(bot, message, first_id, second_id)
    first_chart = await compatibility._chart_for(first_id, onboarding, birth_profile_service)
    second_chart = await compatibility._chart_for(second_id, onboarding, birth_profile_service)
    union_card = _stable_card(
        "group-couple-card-v1", message.chat.id, message.date.date(), first_id, second_id
    )
    username = await _bot_username(bot)
    missing_names: list[str] = []
    if first_chart is None:
        missing_names.append(first_name)
    if second_chart is None:
        missing_names.append(second_name)
    if missing_names:
        text = (
            f"💘 <b>Кармическая пара дня: {escape(first_name)} × {escape(second_name)}</b>\n\n"
            f"🃏 Карта союза — {union_card.name_ru}.\n"
            f"Шипперский вайб: {union_card.upright_theme}.\n\n"
            "Для настоящей астрологической части нужны натальные профили обоих. "
            "Заполните их и нажмите «Проверить снова»."
        )
        await send_art(
            bot,
            message.chat.id,
            card_art(union_card.code),
            text,
            reply_markup=_retry_keyboard(
                username,
                retry_callback=f"v:C:{_encode_users(players)}",
                missing_names=tuple(missing_names),
            ),
        )
        return
    assert first_chart is not None
    assert second_chart is not None
    synastry = calculate_synastry(first_chart, second_chart, CompatibilityContext.LOVE)
    first_sun = compatibility._sign(first_chart, NatalBody.SUN)
    second_sun = compatibility._sign(second_chart, NatalBody.SUN)
    text = (
        f"💘 <b>Кармическая пара дня: {escape(first_name)} × {escape(second_name)}</b>\n\n"
        f"☀️ {first_sun} × {second_sun}\n"
        f"💞 Астросовместимость — <b>{synastry.overall}%</b>\n"
        f"🔥 Притяжение — {synastry.scores.attraction}%\n"
        f"💬 Общение — {synastry.scores.communication}%\n\n"
        f"✨ Сильная сторона: {synastry.strongest}.\n"
        f"⚡ Где искрит: {synastry.weakest}.\n\n"
        f"🃏 Карта союза — {union_card.name_ru}: {union_card.upright_theme}.\n\n"
        f"<b>Numa шипперит:</b> {synastry.verdict}"
    )
    await send_art(
        bot,
        message.chat.id,
        card_art(union_card.code),
        text,
        reply_markup=group_social_handlers._party_back(username, "💞 А моя совместимость?"),
    )


async def _render_duel(
    message: Message,
    bot: Bot,
    onboarding: OnboardingService,
    birth_profile_service: BirthProfileService,
    first_id: int,
    second_id: int,
) -> None:
    first_name, second_name = await compatibility._pair_names(bot, message, first_id, second_id)
    first_chart = await compatibility._chart_for(first_id, onboarding, birth_profile_service)
    second_chart = await compatibility._chart_for(second_id, onboarding, birth_profile_service)
    username = await _bot_username(bot)
    missing_names: list[str] = []
    if first_chart is None:
        missing_names.append(first_name)
    if second_chart is None:
        missing_names.append(second_name)
    retry = f"v:D:{_to_base36(first_id)}.{_to_base36(second_id)}"
    if missing_names:
        await message.answer(
            "🪐 Для Астро-дуэли нужны натальные профили обоих участников.",
            reply_markup=_retry_keyboard(
                username,
                retry_callback=retry,
                missing_names=tuple(missing_names),
            ),
        )
        return
    assert first_chart is not None
    assert second_chart is not None
    first_energy = cosmic_energy_for_day(first_chart, message.date.date())
    second_energy = cosmic_energy_for_day(second_chart, message.date.date())
    if first_energy.score == second_energy.score:
        seed = _digest("group-astro-duel-tie-v1", first_id, second_id, message.date.date())
        first_wins = not (seed[0] & 1)
    else:
        first_wins = first_energy.score > second_energy.score
    winner_name = first_name if first_wins else second_name
    card = _stable_card(
        "group-astro-duel-card-v1", first_id, second_id, message.date.date(), winner_name
    )
    text = (
        f"⚔️ <b>Битва знаков: {escape(first_name)} × {escape(second_name)}</b>\n\n"
        f"🌌 {escape(first_name)} — <b>{first_energy.score}%</b>\n"
        f"{first_energy.reason}.\n\n"
        f"🌌 {escape(second_name)} — <b>{second_energy.score}%</b>\n"
        f"{second_energy.reason}.\n\n"
        f"🏆 Сегодня космос отдаёт раунд: <b>{escape(winner_name)}</b>.\n\n"
        f"🃏 Карта битвы — {card.name_ru}: {card.upright_theme}.\n\n"
        "<em>Игровая астрология: счёт построен на текущих транзитах к натальным картам.</em>"
    )
    await send_art(
        bot,
        message.chat.id,
        card_art(card.code),
        text,
        reply_markup=group_social_handlers._party_back(username, "💞 Проверить совместимость"),
    )


async def viral_action(
    callback: CallbackQuery,
    bot: Bot,
    onboarding: OnboardingService,
    birth_profile_service: BirthProfileService,
) -> None:
    message = _group_message(callback)
    data = callback.data
    if message is None or data is None:
        await callback.answer()
        return
    if data == "v:o:c":
        await callback.answer()
        await group_couple(message)
        return
    if data == "v:o:d":
        await callback.answer()
        await _send_duel_lobby(message, callback.from_user.id, callback.from_user.full_name)
        return
    if data == "v:o:s":
        await callback.answer()
        await group_seance(message)
        return

    parts = data.split(":", 2)
    if len(parts) != 3 or parts[0] != "v":
        await callback.answer()
        return
    action, payload = parts[1], parts[2]
    try:
        if action == "c":
            players = list(_decode_users(payload))
            user_id = callback.from_user.id
            if user_id in players:
                await callback.answer("Ты уже в круге 💘")
                return
            if len(players) >= _MAX_COUPLE_PLAYERS:
                await callback.answer("Круг уже собран.")
                return
            players.append(user_id)
            normalized = tuple(sorted(players))
            await callback.answer("Ты участвуешь 💘")
            await message.edit_text(
                "💘 <b>Кармическая пара дня</b>\n\n"
                f"В круге: {len(normalized)}/{_MAX_COUPLE_PLAYERS}. "
                "Когда будет хотя бы двое — можно открывать пару.\n\n"
                "Участие означает согласие использовать сохранённый астропрофиль для результата.",
                reply_markup=_couple_keyboard(normalized),
            )
            return
        if action == "C":
            players = _decode_users(payload)
            if len(players) < 2:
                await callback.answer("Нужно хотя бы два участника.")
                return
            await callback.answer("Пара выбрана ✨")
            await message.edit_reply_markup(reply_markup=None)
            await _render_couple(message, bot, onboarding, birth_profile_service, players)
            return
        if action == "s":
            players = list(_decode_users(payload))
            user_id = callback.from_user.id
            if user_id in players:
                await callback.answer("Твоё присутствие уже чувствуется 🕯")
                return
            players.append(user_id)
            normalized = tuple(sorted(players))
            if len(normalized) < _SEANCE_THRESHOLD:
                await callback.answer("Круг становится сильнее…")
                await message.edit_text(
                    "🕯 <b>Спиритический сеанс</b>\n\n"
                    f"В круге: {len(normalized)}/{_SEANCE_THRESHOLD}. "
                    "Нужны разные участники.",
                    reply_markup=_seance_keyboard(normalized),
                )
                return
            await callback.answer("Круг замкнулся ✨")
            await message.edit_text(
                "🕯 <b>Круг замкнулся.</b> Numa открывает послание…",
                reply_markup=None,
            )
            seed = _digest("group-seance-v1", message.chat.id, message.date.date(), *normalized)
            secret = _SEANCE_MESSAGES[seed[0] % len(_SEANCE_MESSAGES)]
            card = _stable_card("group-seance-card-v1", message.chat.id, message.date.date(), *normalized)
            await send_art(
                bot,
                message.chat.id,
                card_art(card.code),
                "🔮 <b>Послание для круга</b>\n\n"
                f"{secret}\n\n"
                f"Карта сеанса — {card.name_ru}: {card.upright_theme}.",
                reply_markup=group_social_handlers._party_back(
                    await _bot_username(bot), "🔮 Личное послание"
                ),
            )
            return
        if action == "d":
            challenger_id = _from_base36(payload)
            opponent_id = callback.from_user.id
            if opponent_id == challenger_id:
                await callback.answer("Нужен соперник 🙂")
                return
            await callback.answer("Вызов принят ⚔️")
            await message.edit_reply_markup(reply_markup=None)
            await _render_duel(
                message,
                bot,
                onboarding,
                birth_profile_service,
                challenger_id,
                opponent_id,
            )
            return
        if action == "D":
            first_raw, second_raw = payload.split(".", 1)
            first_id, second_id = _from_base36(first_raw), _from_base36(second_raw)
            if callback.from_user.id not in {first_id, second_id}:
                await callback.answer("Проверить дуэль могут только её участники.")
                return
            await callback.answer("Проверяю карты ✨")
            await _render_duel(
                message,
                bot,
                onboarding,
                birth_profile_service,
                first_id,
                second_id,
            )
            return
    except (TypeError, ValueError):
        await callback.answer("Не получилось продолжить игру.")
        return
    await callback.answer()


GROUP_VIRAL_HELP = (
    "🔮 Numa в этом чате\n\n"
    "Команды:\n\n"
    "🔮 /card — карта дня для всего чата\n"
    "💞 /compatibility — совместимость участников\n"
    "💘 /couple — кармическая пара дня\n"
    "⚔️ /duel — битва знаков\n"
    "🕯 /seance — коллективное гадание\n"
    "🎱 /taro — Таро Да/Нет\n"
    "🪐 /advice — космический совет дня\n"
    "🎉 /party — игры для компании\n"
    "🃏 /event — расклад на событие\n"
    "🎭 /chat — архетип этого чата\n"
    "✨ /grouphelp — показать эту подсказку\n\n"
    "Как использовать:\n"
    "• /compatibility — откройте лобби; участники сами подтверждают себя кнопками.\n"
    "• /couple — добровольцы входят в круг, затем Numa выбирает пару.\n"
    "• /duel — один вызывает чат, другой принимает вызов кнопкой.\n"
    "• /taro вопрос — одна карта отвечает Да или Нет.\n"
    "• /seance — послание откроется после трёх разных участников.\n"
    "• /party — выберите игру кнопкой.\n"
    "• /event — выберите вечер, поездку или событие кнопкой.\n\n"
    "Алиас карты дня: /card_of_the_day\n\n"
    "Ещё механики:\n"
    "🔮 /forecast — что ждёт чат сегодня\n"
    "🔥 /versus — кто из вас сегодня скорее…\n"
    "👑 /roles — роли дня\n"
    "🃏 /cards — карта каждому добровольцу\n"
    "🔁 /karma — день групповой кармы\n"
    "🏆 /week — итоги недели чата\n\n"
    "Все групповые расклады — игровой формат. Личные вопросы лучше задавать Numa один на один."
)


def install_group_viral_mechanics() -> None:
    """Register viral rituals after the compatibility lobby and extend Party."""

    global _PREVIOUS_PARTY_MENU
    if "group_viral" in _INSTALL_MARKERS:
        return
    router = group_handlers.router
    router.message.handlers[:] = [
        handler for handler in router.message.handlers if handler.callback is not group_social_handlers.group_duel
    ]
    router.message(_GROUP_CHAT, Command("couple"))(group_couple)
    router.message(_GROUP_CHAT, Command("duel"))(astro_duel_entry)
    router.message(_GROUP_CHAT, Command("seance"))(group_seance)
    router.message(_GROUP_CHAT, Command("advice"))(group_advice)
    router.message(_GROUP_CHAT, Command("taro"))(group_taro_yes_no)
    router.message(_GROUP_CHAT, Command("card_of_the_day"))(group_handlers.group_card)
    router.callback_query(F.data.startswith("v:"))(viral_action)
    _PREVIOUS_PARTY_MENU = group_handlers._party_menu_keyboard
    group_handlers._party_menu_keyboard = _viral_party_menu
    group_handlers.GROUP_HELP = GROUP_VIRAL_HELP
    _INSTALL_MARKERS.add("group_viral")
