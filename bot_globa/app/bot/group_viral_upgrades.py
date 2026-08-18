"""Upgrade group shipping and Astro Duel without requiring full natal profiles.

A missing natal profile no longer stops a group game. The missing participant can choose
only their Sun sign in the group; raw birth data is never requested or exposed there.
Astro Duel is a three-round reveal (Mars, Moon, Venus) and remains fully callback-driven.
"""

from dataclasses import dataclass
from datetime import date
from html import escape
from typing import Any

import astronomy
from aiogram import Bot, F
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot import group_compatibility_handlers as compatibility
from app.bot import group_handlers
from app.bot import group_social_handlers as social
from app.bot import group_viral_handlers as viral
from app.bot.scene_media import send_art
from app.bot.tarot_art import card_art
from app.domain.natal_chart import NatalBody, NatalChartResult, ZodiacSign
from app.services.birth_profile import BirthProfileService
from app.services.onboarding import OnboardingService

_GROUP_CHAT = F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP})
_GROUP_TYPES = {ChatType.GROUP, ChatType.SUPERGROUP}
_INSTALL_MARKERS: set[str] = set()
_ORIGINAL_RENDER_COUPLE = viral._render_couple

_ZODIAC_SIGNS = tuple(ZodiacSign)
_ZODIAC_EMOJI = (
    "♈",
    "♉",
    "♊",
    "♋",
    "♌",
    "♍",
    "♎",
    "♏",
    "♐",
    "♑",
    "♒",
    "♓",
)
_ELEMENT: dict[ZodiacSign, str] = {
    ZodiacSign.ARIES: "fire",
    ZodiacSign.LEO: "fire",
    ZodiacSign.SAGITTARIUS: "fire",
    ZodiacSign.TAURUS: "earth",
    ZodiacSign.VIRGO: "earth",
    ZodiacSign.CAPRICORN: "earth",
    ZodiacSign.GEMINI: "air",
    ZodiacSign.LIBRA: "air",
    ZodiacSign.AQUARIUS: "air",
    ZodiacSign.CANCER: "water",
    ZodiacSign.SCORPIO: "water",
    ZodiacSign.PISCES: "water",
}
_COMPLEMENTARY_ELEMENTS = {frozenset(("fire", "air")), frozenset(("earth", "water"))}


@dataclass(frozen=True, slots=True)
class DuelRound:
    code: str
    emoji: str
    planet: str
    quality: str
    body: Any
    targets: tuple[tuple[NatalBody, str, int], ...]


_DUEL_ROUNDS = (
    DuelRound(
        "m",
        "🔥",
        "Марс",
        "Напор",
        astronomy.Body.Mars,
        ((NatalBody.MARS, "Марсу", 3), (NatalBody.SUN, "Солнцу", 1)),
    ),
    DuelRound(
        "l",
        "🌙",
        "Луна",
        "Интуиция",
        astronomy.Body.Moon,
        ((NatalBody.MOON, "Луне", 3), (NatalBody.SUN, "Солнцу", 1)),
    ),
    DuelRound(
        "v",
        "✨",
        "Венера",
        "Обаяние",
        astronomy.Body.Venus,
        ((NatalBody.VENUS, "Венере", 3), (NatalBody.MOON, "Луне", 1)),
    ),
)
_ROUND_BY_CODE = {item.code: item for item in _DUEL_ROUNDS}


def _sign_code(sign: ZodiacSign | None) -> str:
    if sign is None:
        return "x"
    return format(_ZODIAC_SIGNS.index(sign), "x")


def _sign_from_code(value: str) -> ZodiacSign | None:
    if value == "x":
        return None
    index = int(value, 16)
    if not 0 <= index < len(_ZODIAC_SIGNS):
        raise ValueError("unsupported zodiac sign")
    return _ZODIAC_SIGNS[index]


def _sun_sign(chart: NatalChartResult) -> ZodiacSign:
    for position in chart.planets:
        if position.body is NatalBody.SUN:
            return position.sign
    raise ValueError("natal chart has no Sun")


def _sign_label(sign: ZodiacSign) -> str:
    return compatibility._ZODIAC_RU[sign]


def quick_sign_compatibility(
    first: ZodiacSign,
    second: ZodiacSign,
) -> tuple[int, str]:
    """Return a light, symmetric Sun-sign score that is never presented as synastry."""

    if first is second:
        base = 88
        reason = "один знак — похожий темп и понятные друг другу реакции"
    elif _ELEMENT[first] == _ELEMENT[second]:
        base = 84
        reason = "одна стихия — легко поймать общий ритм"
    elif frozenset((_ELEMENT[first], _ELEMENT[second])) in _COMPLEMENTARY_ELEMENTS:
        base = 80
        reason = "стихии хорошо дополняют друг друга"
    else:
        base = 62
        reason = "стихии разные — интерес держится на контрасте"
    left, right = sorted((first.value, second.value))
    variation = viral._digest("quick-sign-v1", left, right)[0] % 7 - 3
    return max(50, min(92, base + variation)), reason


def duel_round_energy_for_chart(
    chart: NatalChartResult,
    for_date: date,
    round_code: str,
) -> viral.CosmicEnergy:
    """Score one named duel round from the matching transit to natal placements."""

    config = _ROUND_BY_CODE[round_code]
    astro_time = viral._astro_time(for_date)
    transit_longitude = viral._longitude(config.body, astro_time)
    natal = {position.body: position.longitude_millidegrees / 1000.0 for position in chart.planets}
    score = 55
    strongest: tuple[int, str] | None = None
    for target_body, target_name, weight in config.targets:
        target_longitude = natal.get(target_body)
        if target_longitude is None:
            continue
        separation = viral._angular_distance(transit_longitude, target_longitude)
        aspect = min(viral._ASPECTS, key=lambda item: abs(separation - item[0]))
        angle, aspect_name, value, maximum_orb = aspect
        if abs(separation - angle) > maximum_orb:
            continue
        contribution = value * weight
        score += contribution
        reason = f"{config.planet} {aspect_name} натальному {target_name}"
        if strongest is None or abs(contribution) > abs(strongest[0]):
            strongest = contribution, reason
    bounded = max(35, min(95, score))
    if strongest is None:
        transit_sign = viral._sign_name(transit_longitude)
        return viral.CosmicEnergy(
            bounded,
            f"{config.planet} в знаке {transit_sign}: без явного аспекта",
        )
    return viral.CosmicEnergy(bounded, strongest[1])


def duel_round_energy_for_sign(
    sign: ZodiacSign,
    for_date: date,
    round_code: str,
) -> viral.CosmicEnergy:
    """Estimate one duel round from a Sun sign only; this is explicitly a quick mode."""

    config = _ROUND_BY_CODE[round_code]
    astro_time = viral._astro_time(for_date)
    transit_longitude = viral._longitude(config.body, astro_time)
    sign_index = _ZODIAC_SIGNS.index(sign)
    sun_midpoint = sign_index * 30.0 + 15.0
    separation = viral._angular_distance(transit_longitude, sun_midpoint)
    aspect = min(viral._ASPECTS, key=lambda item: abs(separation - item[0]))
    angle, aspect_name, value, maximum_orb = aspect
    seed = viral._digest("quick-duel-v1", sign.value, for_date.isoformat(), round_code)
    score = 50 + seed[0] % 11
    if abs(separation - angle) <= maximum_orb + 5.0:
        score += value * 5
        reason = f"{config.planet} {aspect_name} солнечному знаку"
    else:
        reason = f"{config.planet} сегодня без точного аспекта к солнечному знаку"
    return viral.CosmicEnergy(max(35, min(95, score)), reason)


def duel_round_winner(
    first_id: int,
    second_id: int,
    first_score: int,
    second_score: int,
    for_date: date,
    round_code: str,
) -> int:
    if first_score > second_score:
        return first_id
    if second_score > first_score:
        return second_id
    left, right = sorted((first_id, second_id))
    seed = viral._digest("duel-round-tie-v1", left, right, for_date.isoformat(), round_code)
    return (left, right)[seed[0] & 1]


def duel_winners_for_signs(
    first_id: int,
    second_id: int,
    first_sign: ZodiacSign,
    second_sign: ZodiacSign,
    for_date: date,
) -> tuple[int, int, int]:
    winners: list[int] = []
    for config in _DUEL_ROUNDS:
        first = duel_round_energy_for_sign(first_sign, for_date, config.code)
        second = duel_round_energy_for_sign(second_sign, for_date, config.code)
        winners.append(
            duel_round_winner(
                first_id,
                second_id,
                first.score,
                second.score,
                for_date,
                config.code,
            )
        )
    return winners[0], winners[1], winners[2]


def _pair_payload(first_id: int, second_id: int) -> str:
    return f"{viral._to_base36(first_id)}.{viral._to_base36(second_id)}"


def _zodiac_keyboard(
    kind: str,
    first_id: int,
    second_id: int,
    target_id: int,
    first_sign: ZodiacSign | None,
    second_sign: ZodiacSign | None,
) -> InlineKeyboardMarkup:
    prefix = (
        f"vu:z:{kind}:{_pair_payload(first_id, second_id)}."
        f"{viral._to_base36(target_id)}.{_sign_code(first_sign)}.{_sign_code(second_sign)}"
    )
    buttons = [
        InlineKeyboardButton(
            text=f"{_ZODIAC_EMOJI[index]} {_sign_label(sign)}",
            callback_data=f"{prefix}.{format(index, 'x')}",
        )
        for index, sign in enumerate(_ZODIAC_SIGNS)
    ]
    rows = [buttons[index : index + 3] for index in range(0, len(buttons), 3)]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _duel_accept_keyboard(challenger_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⚔️ Принять вызов",
                    callback_data=f"vu:d:{viral._to_base36(challenger_id)}",
                )
            ],
            [InlineKeyboardButton(text="← К играм", callback_data="group:party:menu")],
        ]
    )


def _duel_payload(
    mode: str,
    first_id: int,
    second_id: int,
    first_sign: ZodiacSign | None = None,
    second_sign: ZodiacSign | None = None,
) -> str:
    pair = _pair_payload(first_id, second_id)
    if mode == "n":
        return pair
    if first_sign is None or second_sign is None:
        raise ValueError("quick duel needs both signs")
    return f"{pair}.{_sign_code(first_sign)}.{_sign_code(second_sign)}"


def _duel_round_keyboard(mode: str, payload: str, round_index: int) -> InlineKeyboardMarkup:
    config = _DUEL_ROUNDS[round_index]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{config.emoji} Раунд {round_index + 1} · {config.planet}",
                    callback_data=f"vu:r:{mode}:{payload}:{round_index}",
                )
            ],
            [InlineKeyboardButton(text="← К играм", callback_data="group:party:menu")],
        ]
    )


def _precision_keyboard(
    bot_username: str | None,
    kind: str,
    first_id: int,
    second_id: int,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if bot_username:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🪐 Сделать точнее по натальной карте",
                    url=f"https://t.me/{bot_username.removeprefix('@')}?start=astro",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="🔄 Проверить точный режим",
                callback_data=f"vu:e:{kind}:{_pair_payload(first_id, second_id)}",
            )
        ]
    )
    rows.append([InlineKeyboardButton(text="← К играм", callback_data="group:party:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _final_duel_keyboard(
    bot_username: str | None,
    *,
    quick_mode: bool,
    first_id: int,
    second_id: int,
) -> InlineKeyboardMarkup:
    if quick_mode:
        return _precision_keyboard(bot_username, "d", first_id, second_id)
    rows: list[list[InlineKeyboardButton]] = []
    if bot_username:
        rows.append(
            [
                InlineKeyboardButton(
                    text="💞 Проверить совместимость",
                    url=group_handlers.private_deep_link(bot_username, "love"),
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="← К играм", callback_data="group:party:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _bot_username(bot: Bot) -> str | None:
    return (await bot.get_me()).username


async def _pair_charts(
    first_id: int,
    second_id: int,
    onboarding: OnboardingService,
    birth_profile_service: BirthProfileService,
) -> tuple[NatalChartResult | None, NatalChartResult | None]:
    first = await compatibility._chart_for(first_id, onboarding, birth_profile_service)
    second = await compatibility._chart_for(second_id, onboarding, birth_profile_service)
    return first, second


async def _ask_for_missing_sign(
    message: Message,
    bot: Bot,
    *,
    kind: str,
    first_id: int,
    second_id: int,
    first_sign: ZodiacSign | None,
    second_sign: ZodiacSign | None,
) -> None:
    if first_sign is None:
        target_id = first_id
    elif second_sign is None:
        target_id = second_id
    else:
        raise ValueError("no missing sign")
    target_name = await compatibility._member_name(bot, message, target_id)
    mode_name = "кармической пары" if kind == "c" else "Астро-дуэли"
    await message.answer(
        f"⚡ <b>Быстрый режим {mode_name}</b>\n\n"
        f"{escape(target_name)}, выбери свой солнечный знак. "
        "Дата рождения в группу не нужна.\n\n"
        "Это быстрый расчёт по знакам; натальная карта даст более точный результат.",
        reply_markup=_zodiac_keyboard(
            kind,
            first_id,
            second_id,
            target_id,
            first_sign,
            second_sign,
        ),
    )


async def _render_quick_couple(
    message: Message,
    bot: Bot,
    first_id: int,
    second_id: int,
    first_sign: ZodiacSign,
    second_sign: ZodiacSign,
) -> None:
    first_name, second_name = await compatibility._pair_names(bot, message, first_id, second_id)
    score, reason = quick_sign_compatibility(first_sign, second_sign)
    card = viral._stable_card(
        "quick-couple-card-v1",
        message.chat.id,
        message.date.date(),
        *sorted((first_id, second_id)),
    )
    text = (
        f"💘 <b>{escape(first_name)} × {escape(second_name)}</b>\n\n"
        "⚡ <b>Быстрый режим по солнечным знакам</b>\n"
        f"☀️ {_sign_label(first_sign)} × {_sign_label(second_sign)}\n"
        f"💞 Вайб пары — <b>{score}%</b>\n"
        f"Почему: {reason}.\n\n"
        f"🃏 Карта союза — {card.name_ru}: {card.upright_theme}.\n\n"
        "Хотите точнее — заполните натальный профиль и запустите точный режим."
    )
    await send_art(
        bot,
        message.chat.id,
        card_art(card.code),
        text,
        reply_markup=_precision_keyboard(
            await _bot_username(bot),
            "c",
            first_id,
            second_id,
        ),
    )


async def _render_couple_upgrade(
    message: Message,
    bot: Bot,
    onboarding: OnboardingService,
    birth_profile_service: BirthProfileService,
    players: tuple[int, ...],
) -> None:
    first_id, second_id = viral.couple_pair_for_day(
        message.chat.id,
        players,
        message.date.date(),
    )
    first_chart, second_chart = await _pair_charts(
        first_id,
        second_id,
        onboarding,
        birth_profile_service,
    )
    if first_chart is not None and second_chart is not None:
        await _ORIGINAL_RENDER_COUPLE(
            message,
            bot,
            onboarding,
            birth_profile_service,
            (first_id, second_id),
        )
        return
    await _ask_for_missing_sign(
        message,
        bot,
        kind="c",
        first_id=first_id,
        second_id=second_id,
        first_sign=_sun_sign(first_chart) if first_chart is not None else None,
        second_sign=_sun_sign(second_chart) if second_chart is not None else None,
    )


async def _send_duel_lobby(message: Message, challenger_id: int, challenger_name: str) -> None:
    await message.answer(
        f"⚔️ <b>{escape(challenger_name)} вызывает чат на Астро-дуэль</b>\n\n"
        "Три раунда:\n"
        "🔥 Марс — напор\n"
        "🌙 Луна — интуиция\n"
        "✨ Венера — обаяние\n\n"
        "Если натальной карты нет, Numa предложит быстрый режим по знаку прямо в группе.",
        reply_markup=_duel_accept_keyboard(challenger_id),
    )


async def astro_duel_entry(message: Message) -> None:
    author = message.from_user
    if author is None:
        return
    await _send_duel_lobby(message, author.id, author.full_name)


async def _start_duel(
    message: Message,
    bot: Bot,
    *,
    mode: str,
    first_id: int,
    second_id: int,
    first_sign: ZodiacSign | None = None,
    second_sign: ZodiacSign | None = None,
) -> None:
    first_name, second_name = await compatibility._pair_names(bot, message, first_id, second_id)
    payload = _duel_payload(mode, first_id, second_id, first_sign, second_sign)
    mode_label = (
        "🪐 Точный режим по натальным картам"
        if mode == "n"
        else "⚡ Быстрый режим по солнечным знакам"
    )
    await message.edit_text(
        f"⚔️ <b>{escape(first_name)} × {escape(second_name)}</b>\n\n"
        f"{mode_label}\n\n"
        "Впереди три раунда. Каждый открывается отдельно — посмотрим, кто заберёт минимум два.",
        reply_markup=_duel_round_keyboard(mode, payload, 0),
    )


async def _prepare_duel(
    message: Message,
    bot: Bot,
    onboarding: OnboardingService,
    birth_profile_service: BirthProfileService,
    first_id: int,
    second_id: int,
) -> None:
    first_chart, second_chart = await _pair_charts(
        first_id,
        second_id,
        onboarding,
        birth_profile_service,
    )
    if first_chart is not None and second_chart is not None:
        await _start_duel(
            message,
            bot,
            mode="n",
            first_id=first_id,
            second_id=second_id,
        )
        return
    await _ask_for_missing_sign(
        message,
        bot,
        kind="d",
        first_id=first_id,
        second_id=second_id,
        first_sign=_sun_sign(first_chart) if first_chart is not None else None,
        second_sign=_sun_sign(second_chart) if second_chart is not None else None,
    )


def _round_energies_for_signs(
    first_sign: ZodiacSign,
    second_sign: ZodiacSign,
    for_date: date,
    round_index: int,
) -> tuple[viral.CosmicEnergy, viral.CosmicEnergy]:
    code = _DUEL_ROUNDS[round_index].code
    return (
        duel_round_energy_for_sign(first_sign, for_date, code),
        duel_round_energy_for_sign(second_sign, for_date, code),
    )


def _round_energies_for_charts(
    first_chart: NatalChartResult,
    second_chart: NatalChartResult,
    for_date: date,
    round_index: int,
) -> tuple[viral.CosmicEnergy, viral.CosmicEnergy]:
    code = _DUEL_ROUNDS[round_index].code
    return (
        duel_round_energy_for_chart(first_chart, for_date, code),
        duel_round_energy_for_chart(second_chart, for_date, code),
    )


async def _render_duel_round(
    message: Message,
    bot: Bot,
    onboarding: OnboardingService,
    birth_profile_service: BirthProfileService,
    *,
    mode: str,
    first_id: int,
    second_id: int,
    round_index: int,
    first_sign: ZodiacSign | None = None,
    second_sign: ZodiacSign | None = None,
) -> None:
    if not 0 <= round_index < len(_DUEL_ROUNDS):
        raise ValueError("invalid duel round")
    first_name, second_name = await compatibility._pair_names(bot, message, first_id, second_id)
    day = message.date.date()
    first_chart: NatalChartResult | None = None
    second_chart: NatalChartResult | None = None
    if mode == "n":
        first_chart, second_chart = await _pair_charts(
            first_id,
            second_id,
            onboarding,
            birth_profile_service,
        )
        if first_chart is None or second_chart is None:
            await _prepare_duel(
                message,
                bot,
                onboarding,
                birth_profile_service,
                first_id,
                second_id,
            )
            return
    elif mode == "z":
        if first_sign is None or second_sign is None:
            raise ValueError("quick duel needs signs")
    else:
        raise ValueError("unsupported duel mode")

    round_results: list[tuple[viral.CosmicEnergy, viral.CosmicEnergy, int]] = []
    for index in range(round_index + 1):
        config = _DUEL_ROUNDS[index]
        if mode == "n":
            assert first_chart is not None
            assert second_chart is not None
            first_energy, second_energy = _round_energies_for_charts(
                first_chart,
                second_chart,
                day,
                index,
            )
        else:
            assert first_sign is not None
            assert second_sign is not None
            first_energy, second_energy = _round_energies_for_signs(
                first_sign,
                second_sign,
                day,
                index,
            )
        winner_id = duel_round_winner(
            first_id,
            second_id,
            first_energy.score,
            second_energy.score,
            day,
            config.code,
        )
        round_results.append((first_energy, second_energy, winner_id))

    current_config = _DUEL_ROUNDS[round_index]
    first_energy, second_energy, current_winner = round_results[-1]
    current_winner_name = first_name if current_winner == first_id else second_name
    first_wins = sum(1 for _, _, winner in round_results if winner == first_id)
    second_wins = len(round_results) - first_wins
    history = "\n".join(
        f"{_DUEL_ROUNDS[index].emoji} {_DUEL_ROUNDS[index].planet} — "
        f"{escape(first_name if winner == first_id else second_name)}"
        for index, (_, _, winner) in enumerate(round_results)
    )
    mode_label = "натальные карты" if mode == "n" else "солнечные знаки"
    text = (
        f"⚔️ <b>Раунд {round_index + 1}/3 · {current_config.emoji} "
        f"{current_config.planet} — {current_config.quality}</b>\n\n"
        f"{escape(first_name)} — <b>{first_energy.score}%</b>\n"
        f"{first_energy.reason}.\n\n"
        f"{escape(second_name)} — <b>{second_energy.score}%</b>\n"
        f"{second_energy.reason}.\n\n"
        f"🏅 Раунд забирает <b>{escape(current_winner_name)}</b>.\n"
        f"Счёт: <b>{first_wins}:{second_wins}</b>\n\n"
        f"{history}\n\n"
        f"<em>Режим: {mode_label}.</em>"
    )
    if round_index < len(_DUEL_ROUNDS) - 1:
        payload = _duel_payload(mode, first_id, second_id, first_sign, second_sign)
        await message.edit_text(
            text,
            reply_markup=_duel_round_keyboard(mode, payload, round_index + 1),
        )
        return

    final_winner_id = first_id if first_wins > second_wins else second_id
    final_winner_name = first_name if final_winner_id == first_id else second_name
    card = viral._stable_card(
        "group-astro-duel-card-v2",
        *sorted((first_id, second_id)),
        day,
        final_winner_id,
    )
    final_text = (
        text
        + f"\n\n🏆 <b>Битва завершена: {first_wins}:{second_wins}</b>\n"
        + f"Победитель сегодня — <b>{escape(final_winner_name)}</b>.\n\n"
        + f"🃏 Карта битвы — {card.name_ru}: {card.upright_theme}."
    )
    await message.edit_text(final_text, reply_markup=None)
    await send_art(
        bot,
        message.chat.id,
        card_art(card.code),
        f"🏆 <b>{escape(final_winner_name)}</b> забирает Астро-дуэль {first_wins}:{second_wins}.\n\n"
        f"🃏 {card.name_ru}: {card.upright_theme}.",
        reply_markup=_final_duel_keyboard(
            await _bot_username(bot),
            quick_mode=mode == "z",
            first_id=first_id,
            second_id=second_id,
        ),
    )


async def _continue_after_sign_choice(
    message: Message,
    bot: Bot,
    onboarding: OnboardingService,
    birth_profile_service: BirthProfileService,
    *,
    kind: str,
    first_id: int,
    second_id: int,
    first_sign: ZodiacSign | None,
    second_sign: ZodiacSign | None,
) -> None:
    if first_sign is None or second_sign is None:
        await _ask_for_missing_sign(
            message,
            bot,
            kind=kind,
            first_id=first_id,
            second_id=second_id,
            first_sign=first_sign,
            second_sign=second_sign,
        )
        return
    if kind == "c":
        await _render_quick_couple(
            message,
            bot,
            first_id,
            second_id,
            first_sign,
            second_sign,
        )
        return
    if kind == "d":
        await _start_duel(
            message,
            bot,
            mode="z",
            first_id=first_id,
            second_id=second_id,
            first_sign=first_sign,
            second_sign=second_sign,
        )
        return
    raise ValueError("unsupported zodiac flow")


async def viral_upgrade_action(
    callback: CallbackQuery,
    bot: Bot,
    onboarding: OnboardingService,
    birth_profile_service: BirthProfileService,
) -> None:
    message = callback.message
    data = callback.data
    if not isinstance(message, Message) or message.chat.type not in _GROUP_TYPES or data is None:
        await callback.answer()
        return
    parts = data.split(":", 3)
    if len(parts) < 3 or parts[0] != "vu":
        await callback.answer()
        return
    action = parts[1]
    try:
        if action == "d" and len(parts) == 3:
            challenger_id = viral._from_base36(parts[2])
            opponent_id = callback.from_user.id
            if opponent_id == challenger_id:
                await callback.answer("Нужен соперник 🙂")
                return
            await callback.answer("Вызов принят ⚔️")
            await message.edit_reply_markup(reply_markup=None)
            await _prepare_duel(
                message,
                bot,
                onboarding,
                birth_profile_service,
                challenger_id,
                opponent_id,
            )
            return
        if action == "z" and len(parts) == 4:
            kind = parts[2]
            fields = parts[3].split(".")
            if len(fields) != 6:
                raise ValueError("invalid zodiac payload")
            first_id = viral._from_base36(fields[0])
            second_id = viral._from_base36(fields[1])
            target_id = viral._from_base36(fields[2])
            first_sign = _sign_from_code(fields[3])
            second_sign = _sign_from_code(fields[4])
            chosen_sign = _sign_from_code(fields[5])
            if chosen_sign is None:
                raise ValueError("sign is required")
            if callback.from_user.id != target_id:
                await callback.answer("Свой знак выбирает сам участник 🙂")
                return
            if target_id == first_id:
                first_sign = chosen_sign
            elif target_id == second_id:
                second_sign = chosen_sign
            else:
                raise ValueError("target is outside pair")
            await callback.answer(f"{_sign_label(chosen_sign)} ✨")
            await message.edit_reply_markup(reply_markup=None)
            await _continue_after_sign_choice(
                message,
                bot,
                onboarding,
                birth_profile_service,
                kind=kind,
                first_id=first_id,
                second_id=second_id,
                first_sign=first_sign,
                second_sign=second_sign,
            )
            return
        if action == "r" and len(parts) == 4:
            mode = parts[2]
            payload, round_raw = parts[3].rsplit(":", 1)
            round_index = int(round_raw)
            fields = payload.split(".")
            first_id = viral._from_base36(fields[0])
            second_id = viral._from_base36(fields[1])
            if callback.from_user.id not in {first_id, second_id}:
                await callback.answer("Раунд открывают только участники дуэли.")
                return
            first_sign = _sign_from_code(fields[2]) if mode == "z" else None
            second_sign = _sign_from_code(fields[3]) if mode == "z" else None
            await callback.answer("Космос считает раунд… ✨")
            await _render_duel_round(
                message,
                bot,
                onboarding,
                birth_profile_service,
                mode=mode,
                first_id=first_id,
                second_id=second_id,
                round_index=round_index,
                first_sign=first_sign,
                second_sign=second_sign,
            )
            return
        if action == "e" and len(parts) == 4:
            kind = parts[2]
            first_raw, second_raw = parts[3].split(".", 1)
            first_id = viral._from_base36(first_raw)
            second_id = viral._from_base36(second_raw)
            if callback.from_user.id not in {first_id, second_id}:
                await callback.answer("Точный режим могут проверить только участники пары.")
                return
            first_chart, second_chart = await _pair_charts(
                first_id,
                second_id,
                onboarding,
                birth_profile_service,
            )
            if first_chart is None or second_chart is None:
                await callback.answer("Пока не хватает одного из натальных профилей.")
                return
            await callback.answer("Натальные карты готовы ✨")
            if kind == "c":
                await _ORIGINAL_RENDER_COUPLE(
                    message,
                    bot,
                    onboarding,
                    birth_profile_service,
                    (first_id, second_id),
                )
                return
            if kind == "d":
                await _start_duel(
                    message,
                    bot,
                    mode="n",
                    first_id=first_id,
                    second_id=second_id,
                )
                return
            raise ValueError("unsupported exact retry")
    except (IndexError, TypeError, ValueError):
        await callback.answer("Не получилось продолжить игру.")
        return
    await callback.answer()


def install_group_viral_upgrades() -> None:
    """Patch couple fallback and replace the one-shot duel with the three-round version."""

    if "group_viral_upgrades" in _INSTALL_MARKERS:
        return
    router = group_handlers.router
    router.message.handlers[:] = [
        handler for handler in router.message.handlers if handler.callback is not viral.astro_duel_entry
    ]
    router.message(_GROUP_CHAT, Command("duel"))(astro_duel_entry)
    router.callback_query(F.data.startswith("vu:"))(viral_upgrade_action)
    viral._render_couple = _render_couple_upgrade
    _INSTALL_MARKERS.add("group_viral_upgrades")
