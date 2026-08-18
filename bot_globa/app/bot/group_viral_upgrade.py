"""Sun-sign fallback for group astrology and three-round Astro Duel."""

from dataclasses import dataclass
from datetime import date
from html import escape

import astronomy
from aiogram import Bot, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot import group_compatibility_handlers as compatibility
from app.bot import group_handlers, group_social_handlers
from app.bot import group_viral_handlers as viral
from app.bot.scene_media import send_art
from app.bot.tarot_art import card_art
from app.domain.natal_chart import NatalBody, NatalChartResult, ZodiacSign
from app.services.birth_profile import BirthProfileService
from app.services.onboarding import OnboardingService

_INSTALL_MARKERS: set[str] = set()
_SIGNS = tuple(ZodiacSign)
_SIGN_CODE = {sign: format(i, "x") for i, sign in enumerate(_SIGNS)}
_SIGN_BY_CODE = {code: sign for sign, code in _SIGN_CODE.items()}
_DUEL_ROUNDS = (
    ("🔥 Марс — напор", NatalBody.MARS, astronomy.Body.Mars),
    ("🌙 Луна — интуиция", NatalBody.MOON, astronomy.Body.Moon),
    ("✨ Венера — обаяние", NatalBody.VENUS, astronomy.Body.Venus),
)


@dataclass(frozen=True, slots=True)
class QuickCompatibility:
    overall: int
    attraction: int
    communication: int
    long_term: int


@dataclass(frozen=True, slots=True)
class DuelRound:
    title: str
    first_score: int
    second_score: int
    first_reason: str
    second_reason: str
    winner_id: int


@dataclass(frozen=True, slots=True)
class DuelSeries:
    rounds: tuple[DuelRound, DuelRound, DuelRound]
    first_wins: int
    second_wins: int
    winner_id: int


def _clamp(value: int) -> int:
    return max(35, min(95, value))


def _sign_index(sign: ZodiacSign) -> int:
    return _SIGNS.index(sign)


def quick_compatibility_for_signs(
    first: ZodiacSign,
    second: ZodiacSign,
) -> QuickCompatibility:
    first_element = _sign_index(first) % 4
    second_element = _sign_index(second) % 4
    if first_element == second_element:
        element = 84
    elif {first_element, second_element} in ({0, 2}, {1, 3}):
        element = 89
    elif {first_element, second_element} in ({0, 3}, {1, 2}):
        element = 63
    else:
        element = 74
    modality = 70 if _sign_index(first) % 3 == _sign_index(second) % 3 else 82
    attraction = _clamp(element + (4 if first != second else 0))
    communication = _clamp((element + modality) // 2)
    long_term = _clamp((element * 2 + modality) // 3)
    return QuickCompatibility(
        round((attraction + communication + long_term) / 3),
        attraction,
        communication,
        long_term,
    )


def _sun_sign(chart: NatalChartResult) -> ZodiacSign:
    return next(position.sign for position in chart.planets if position.body is NatalBody.SUN)


def _pair_payload(first_id: int, second_id: int) -> str:
    return f"{viral._to_base36(first_id)}.{viral._to_base36(second_id)}"


def _decode_pair(payload: str) -> tuple[int, int]:
    first, second = payload.split(".", 1)
    return viral._from_base36(first), viral._from_base36(second)


def _sign_token(chart: NatalChartResult | None) -> str:
    return _SIGN_CODE[_sun_sign(chart)] if chart else "x"


def _decode_signs(payload: str) -> tuple[str, str]:
    first, second = payload.split(".", 1)
    if any(value != "x" and value not in _SIGN_BY_CODE for value in (first, second)):
        raise ValueError("unknown sign")
    return first, second


def _sign_keyboard(
    mode: str,
    first_id: int,
    second_id: int,
    signs: tuple[str, str],
    slot: int,
) -> InlineKeyboardMarkup:
    pair = _pair_payload(first_id, second_id)
    state = ".".join(signs)
    buttons = [
        InlineKeyboardButton(
            text=compatibility._ZODIAC_RU[sign],
            callback_data=(
                f"g2:z:{mode}:{pair}:{state}:{slot}:{_SIGN_CODE[sign]}"
            ),
        )
        for sign in _SIGNS
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=[buttons[index : index + 3] for index in range(0, 12, 3)]
    )


def _fallback_keyboard(
    username: str | None,
    *,
    mode: str,
    first_id: int,
    second_id: int,
    first_name: str,
    second_name: str,
    first_chart: NatalChartResult | None,
    second_chart: NatalChartResult | None,
) -> InlineKeyboardMarkup:
    pair = _pair_payload(first_id, second_id)
    signs = f"{_sign_token(first_chart)}.{_sign_token(second_chart)}"
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="⚡ Быстрый режим по знакам",
                callback_data=f"g2:q:{mode}:{pair}:{signs}",
            )
        ]
    ]
    if username:
        clean_username = username.removeprefix("@")
        for name, chart in (
            (first_name, first_chart),
            (second_name, second_chart),
        ):
            if chart is None:
                rows.append(
                    [
                        InlineKeyboardButton(
                            text=f"🪐 {name}: сделать точнее",
                            url=f"https://t.me/{clean_username}?start=astro",
                        )
                    ]
                )
    rows.append(
        [InlineKeyboardButton(text="← К играм", callback_data="group:party:menu")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _upgrade_keyboard(
    username: str | None,
    *,
    mode: str,
    first_id: int,
    second_id: int,
    first_name: str,
    second_name: str,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if username:
        clean_username = username.removeprefix("@")
        for name in (first_name, second_name):
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"🪐 {name}: натальная карта",
                        url=f"https://t.me/{clean_username}?start=astro",
                    )
                ]
            )
    retry = (
        f"v:C:{viral._encode_users((first_id, second_id))}"
        if mode == "c"
        else f"v:D:{_pair_payload(first_id, second_id)}"
    )
    rows.append(
        [InlineKeyboardButton(text="🔄 Проверить точнее", callback_data=retry)]
    )
    rows.append(
        [InlineKeyboardButton(text="← К играм", callback_data="group:party:menu")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _aspect_score(
    transit: float,
    target: float,
    weight: int,
) -> tuple[int, str | None]:
    separation = viral._angular_distance(transit, target)
    angle, name, value, orb = min(
        viral._ASPECTS,
        key=lambda item: abs(separation - item[0]),
    )
    delta = abs(separation - angle)
    if delta > orb:
        return 0, None
    strength = max(0.35, 1 - delta / orb)
    return round(value * weight * strength), name


def _chart_round_score(
    chart: NatalChartResult,
    for_date: date,
    title: str,
    target_body: NatalBody,
    transit_body: object,
) -> tuple[int, str]:
    transit = viral._longitude(transit_body, viral._astro_time(for_date))
    natal = {
        position.body: position.longitude_millidegrees / 1000
        for position in chart.planets
    }
    score = 50
    strongest: tuple[int, str] | None = None
    for body, weight in ((target_body, 6), (NatalBody.SUN, 3)):
        contribution, aspect = _aspect_score(transit, natal[body], weight)
        score += contribution
        if aspect and (strongest is None or abs(contribution) > abs(strongest[0])):
            strongest = (
                contribution,
                f"{title.split('—')[0].strip()} {aspect} натальной точке",
            )
    if int(transit // 30) % 4 == int(natal[target_body] // 30) % 4:
        score += 3
    reason = strongest[1] if strongest else "космический фон ровный"
    return _clamp(score), reason


def _sign_round_score(
    sign: ZodiacSign,
    for_date: date,
    title: str,
    transit_body: object,
) -> tuple[int, str]:
    transit = viral._longitude(transit_body, viral._astro_time(for_date))
    target = _sign_index(sign) * 30 + 15
    separation = viral._angular_distance(transit, target)
    angle, aspect, value, _orb = min(
        viral._ASPECTS,
        key=lambda item: abs(separation - item[0]),
    )
    closeness = max(0.0, 1 - abs(separation - angle) / 30)
    score = 50 + round(value * 8 * closeness)
    if int(transit // 30) % 4 == _sign_index(sign) % 4:
        score += 4
    reason = f"{title.split('—')[0].strip()} {aspect} солнечному знаку"
    return _clamp(score), reason


def _settle(
    title: str,
    first: tuple[int, str],
    second: tuple[int, str],
    first_id: int,
    second_id: int,
    for_date: date,
) -> DuelRound:
    first_score, first_reason = first
    second_score, second_reason = second
    if first_score == second_score:
        seed = viral._digest(
            "group-duel-round-v2",
            title,
            first_id,
            second_id,
            for_date,
        )
        if seed[0] & 1:
            second_score = _clamp(second_score + 1)
        else:
            first_score = _clamp(first_score + 1)
    winner = first_id if first_score > second_score else second_id
    return DuelRound(
        title,
        first_score,
        second_score,
        first_reason,
        second_reason,
        winner,
    )


def _series(
    rounds: list[DuelRound],
    first_id: int,
    second_id: int,
) -> DuelSeries:
    first_wins = sum(item.winner_id == first_id for item in rounds)
    second_wins = 3 - first_wins
    winner = first_id if first_wins > second_wins else second_id
    return DuelSeries(
        (rounds[0], rounds[1], rounds[2]),
        first_wins,
        second_wins,
        winner,
    )


def duel_series_for_charts(
    first: NatalChartResult,
    second: NatalChartResult,
    first_id: int,
    second_id: int,
    for_date: date,
) -> DuelSeries:
    rounds = [
        _settle(
            title,
            _chart_round_score(first, for_date, title, target, transit),
            _chart_round_score(second, for_date, title, target, transit),
            first_id,
            second_id,
            for_date,
        )
        for title, target, transit in _DUEL_ROUNDS
    ]
    return _series(rounds, first_id, second_id)


def duel_series_for_signs(
    first: ZodiacSign,
    second: ZodiacSign,
    first_id: int,
    second_id: int,
    for_date: date,
) -> DuelSeries:
    rounds = [
        _settle(
            title,
            _sign_round_score(first, for_date, title, transit),
            _sign_round_score(second, for_date, title, transit),
            first_id,
            second_id,
            for_date,
        )
        for title, _target, transit in _DUEL_ROUNDS
    ]
    return _series(rounds, first_id, second_id)


async def _missing_screen(
    message: Message,
    bot: Bot,
    *,
    mode: str,
    first_id: int,
    second_id: int,
    first_name: str,
    second_name: str,
    first_chart: NatalChartResult | None,
    second_chart: NatalChartResult | None,
) -> None:
    missing = [
        name
        for name, chart in (
            (first_name, first_chart),
            (second_name, second_chart),
        )
        if chart is None
    ]
    await message.answer(
        "⚡ <b>Игру можно продолжить сразу</b>\n\n"
        "Для точного расчёта не хватает натальной карты: "
        + ", ".join(escape(name) for name in missing)
        + ".\n\n"
        "Выберите быстрый режим по солнечным знакам прямо в чате. "
        "Полный профиль можно добавить потом.",
        reply_markup=_fallback_keyboard(
            await viral._bot_username(bot),
            mode=mode,
            first_id=first_id,
            second_id=second_id,
            first_name=first_name,
            second_name=second_name,
            first_chart=first_chart,
            second_chart=second_chart,
        ),
    )


async def _couple_v2(
    message: Message,
    bot: Bot,
    onboarding: OnboardingService,
    profiles: BirthProfileService,
    players: tuple[int, ...],
) -> None:
    first_id, second_id = viral.couple_pair_for_day(
        message.chat.id,
        players,
        message.date.date(),
    )
    first_name, second_name = await compatibility._pair_names(
        bot,
        message,
        first_id,
        second_id,
    )
    first_chart = await compatibility._chart_for(first_id, onboarding, profiles)
    second_chart = await compatibility._chart_for(second_id, onboarding, profiles)
    if first_chart and second_chart:
        await viral._render_couple(message, bot, onboarding, profiles, players)
        return
    await _missing_screen(
        message,
        bot,
        mode="c",
        first_id=first_id,
        second_id=second_id,
        first_name=first_name,
        second_name=second_name,
        first_chart=first_chart,
        second_chart=second_chart,
    )


async def _duel_v2(
    message: Message,
    bot: Bot,
    onboarding: OnboardingService,
    profiles: BirthProfileService,
    first_id: int,
    second_id: int,
) -> None:
    first_name, second_name = await compatibility._pair_names(
        bot,
        message,
        first_id,
        second_id,
    )
    first_chart = await compatibility._chart_for(first_id, onboarding, profiles)
    second_chart = await compatibility._chart_for(second_id, onboarding, profiles)
    if not first_chart or not second_chart:
        await _missing_screen(
            message,
            bot,
            mode="d",
            first_id=first_id,
            second_id=second_id,
            first_name=first_name,
            second_name=second_name,
            first_chart=first_chart,
            second_chart=second_chart,
        )
        return
    series = duel_series_for_charts(
        first_chart,
        second_chart,
        first_id,
        second_id,
        message.date.date(),
    )
    await _render_round(
        message,
        bot,
        series,
        first_id,
        second_id,
        first_name,
        second_name,
        0,
        None,
    )


def _round_keyboard(
    first_id: int,
    second_id: int,
    next_round: int,
    signs: tuple[str, str] | None,
) -> InlineKeyboardMarkup:
    pair = _pair_payload(first_id, second_id)
    data = (
        f"g2:r:{pair}:{next_round}"
        if signs is None
        else f"g2:R:{pair}:{'.'.join(signs)}:{next_round}"
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚔️ Следующий раунд", callback_data=data)]
        ]
    )


async def _render_round(
    message: Message,
    bot: Bot,
    series: DuelSeries,
    first_id: int,
    second_id: int,
    first_name: str,
    second_name: str,
    index: int,
    signs: tuple[str, str] | None,
) -> None:
    item = series.rounds[index]
    round_winner = first_name if item.winner_id == first_id else second_name
    text = (
        f"⚔️ <b>Астро-дуэль · раунд {index + 1}/3</b>\n\n"
        f"<b>{item.title}</b>\n\n"
        f"{escape(first_name)} — <b>{item.first_score}%</b>\n"
        f"{item.first_reason}.\n\n"
        f"{escape(second_name)} — <b>{item.second_score}%</b>\n"
        f"{item.second_reason}.\n\n"
        f"🏆 Раунд забирает <b>{escape(round_winner)}</b>."
    )
    if signs:
        text += "\n\n<em>Быстрый режим по солнечным знакам.</em>"
    if index < 2:
        await message.edit_text(
            text,
            reply_markup=_round_keyboard(
                first_id,
                second_id,
                index + 1,
                signs,
            ),
        )
        return
    winner = first_name if series.winner_id == first_id else second_name
    summary = "\n".join(
        f"{round_.title} — "
        f"{escape(first_name if round_.winner_id == first_id else second_name)}"
        for round_ in series.rounds
    )
    await message.edit_text(
        text
        + f"\n\n<b>Итог: {series.first_wins}:{series.second_wins}</b>\n"
        + summary
        + f"\n\n🌌 Победитель — <b>{escape(winner)}</b>.",
        reply_markup=None,
    )
    card = viral._stable_card(
        "group-astro-duel-card-v2",
        first_id,
        second_id,
        message.date.date(),
        winner,
    )
    await send_art(
        bot,
        message.chat.id,
        card_art(card.code),
        f"🃏 <b>Карта битвы — {card.name_ru}</b>\n\n{card.upright_theme}.",
        reply_markup=group_social_handlers._party_back(
            await viral._bot_username(bot),
            "💞 Проверить совместимость",
        ),
    )


async def _quick_couple(
    message: Message,
    bot: Bot,
    first_id: int,
    second_id: int,
    first_sign: ZodiacSign,
    second_sign: ZodiacSign,
) -> None:
    first_name, second_name = await compatibility._pair_names(
        bot,
        message,
        first_id,
        second_id,
    )
    result = quick_compatibility_for_signs(first_sign, second_sign)
    card = viral._stable_card(
        "group-couple-fast-card-v2",
        message.chat.id,
        message.date.date(),
        first_id,
        second_id,
    )
    text = (
        f"💘 <b>Быстрый шиппинг: {escape(first_name)} × "
        f"{escape(second_name)}</b>\n\n"
        f"☀️ {compatibility._ZODIAC_RU[first_sign]} × "
        f"{compatibility._ZODIAC_RU[second_sign]}\n"
        f"💞 Общий вайб — <b>{result.overall}%</b>\n"
        f"🔥 Притяжение — {result.attraction}%\n"
        f"💬 Общение — {result.communication}%\n"
        f"🏠 В долгую — {result.long_term}%\n\n"
        f"🃏 Карта союза — {card.name_ru}: {card.upright_theme}.\n\n"
        "<em>Быстрый режим по солнечным знакам. "
        "Натальная синастрия точнее.</em>"
    )
    await send_art(
        bot,
        message.chat.id,
        card_art(card.code),
        text,
        reply_markup=_upgrade_keyboard(
            await viral._bot_username(bot),
            mode="c",
            first_id=first_id,
            second_id=second_id,
            first_name=first_name,
            second_name=second_name,
        ),
    )


async def _start_sign_picker(
    callback: CallbackQuery,
    message: Message,
    mode: str,
    first_id: int,
    second_id: int,
    signs: tuple[str, str],
) -> None:
    slot = 0 if signs[0] == "x" else 1 if signs[1] == "x" else None
    if slot is None:
        await callback.answer("Знаки уже выбраны ✨")
        return
    expected = first_id if slot == 0 else second_id
    if callback.from_user.id != expected:
        await callback.answer("Сначала свой знак должен выбрать другой участник.")
        return
    await callback.answer()
    await message.edit_text(
        f"☀️ <b>{escape(callback.from_user.full_name)}, выбери свой знак</b>",
        reply_markup=_sign_keyboard(
            mode,
            first_id,
            second_id,
            signs,
            slot,
        ),
    )


async def _save_sign(
    callback: CallbackQuery,
    message: Message,
    bot: Bot,
    mode: str,
    first_id: int,
    second_id: int,
    signs: tuple[str, str],
    slot: int,
    code: str,
) -> None:
    expected = first_id if slot == 0 else second_id
    if callback.from_user.id != expected or code not in _SIGN_BY_CODE:
        await callback.answer("Эту кнопку должен нажать выбранный участник.")
        return
    values = list(signs)
    values[slot] = code
    if "x" in values:
        next_slot = values.index("x")
        next_id = first_id if next_slot == 0 else second_id
        next_name = await compatibility._member_name(bot, message, next_id)
        await callback.answer("Знак выбран ✨")
        await message.edit_text(
            f"☀️ Теперь <b>{escape(next_name)}</b> выбирает свой знак.",
            reply_markup=_sign_keyboard(
                mode,
                first_id,
                second_id,
                (values[0], values[1]),
                next_slot,
            ),
        )
        return
    await callback.answer("Готово ✨")
    first_sign = _SIGN_BY_CODE[values[0]]
    second_sign = _SIGN_BY_CODE[values[1]]
    if mode == "c":
        await message.edit_text(
            "💘 Знаки выбраны. Считаю быстрый шиппинг…",
            reply_markup=None,
        )
        await _quick_couple(
            message,
            bot,
            first_id,
            second_id,
            first_sign,
            second_sign,
        )
        return
    first_name, second_name = await compatibility._pair_names(
        bot,
        message,
        first_id,
        second_id,
    )
    series = duel_series_for_signs(
        first_sign,
        second_sign,
        first_id,
        second_id,
        message.date.date(),
    )
    await _render_round(
        message,
        bot,
        series,
        first_id,
        second_id,
        first_name,
        second_name,
        0,
        (values[0], values[1]),
    )


async def viral_action_v2(
    callback: CallbackQuery,
    bot: Bot,
    onboarding: OnboardingService,
    birth_profile_service: BirthProfileService,
) -> None:
    message = callback.message
    data = callback.data
    if not isinstance(message, Message) or data is None:
        await callback.answer()
        return
    try:
        if data.startswith("v:C:"):
            players = viral._decode_users(data[4:])
            if len(players) < 2:
                await callback.answer("Нужно хотя бы два участника.")
                return
            await callback.answer("Пара выбрана ✨")
            await message.edit_reply_markup(reply_markup=None)
            await _couple_v2(
                message,
                bot,
                onboarding,
                birth_profile_service,
                players,
            )
            return
        if data.startswith("v:d:"):
            first_id = viral._from_base36(data[4:])
            second_id = callback.from_user.id
            if first_id == second_id:
                await callback.answer("Нужен соперник 🙂")
                return
            await callback.answer("Вызов принят ⚔️")
            await message.edit_reply_markup(reply_markup=None)
            await _duel_v2(
                message,
                bot,
                onboarding,
                birth_profile_service,
                first_id,
                second_id,
            )
            return
        if data.startswith("v:D:"):
            first_id, second_id = _decode_pair(data[4:])
            if callback.from_user.id not in {first_id, second_id}:
                await callback.answer("Проверить дуэль могут только её участники.")
                return
            await callback.answer("Проверяю профили ✨")
            await _duel_v2(
                message,
                bot,
                onboarding,
                birth_profile_service,
                first_id,
                second_id,
            )
            return
        if data.startswith("g2:q:"):
            _, _, mode, pair, raw_signs = data.split(":", 4)
            first_id, second_id = _decode_pair(pair)
            await _start_sign_picker(
                callback,
                message,
                mode,
                first_id,
                second_id,
                _decode_signs(raw_signs),
            )
            return
        if data.startswith("g2:z:"):
            _, _, mode, pair, raw_signs, slot, code = data.split(":", 6)
            first_id, second_id = _decode_pair(pair)
            await _save_sign(
                callback,
                message,
                bot,
                mode,
                first_id,
                second_id,
                _decode_signs(raw_signs),
                int(slot),
                code,
            )
            return
        if data.startswith("g2:r:"):
            _, _, pair, raw_index = data.split(":", 3)
            first_id, second_id = _decode_pair(pair)
            if callback.from_user.id not in {first_id, second_id}:
                await callback.answer("Раунд продолжают участники дуэли.")
                return
            first_chart = await compatibility._chart_for(
                first_id,
                onboarding,
                birth_profile_service,
            )
            second_chart = await compatibility._chart_for(
                second_id,
                onboarding,
                birth_profile_service,
            )
            if not first_chart or not second_chart:
                await callback.answer("Натальная карта пока не готова.")
                return
            first_name, second_name = await compatibility._pair_names(
                bot,
                message,
                first_id,
                second_id,
            )
            await callback.answer("Следующий раунд ⚔️")
            await _render_round(
                message,
                bot,
                duel_series_for_charts(
                    first_chart,
                    second_chart,
                    first_id,
                    second_id,
                    message.date.date(),
                ),
                first_id,
                second_id,
                first_name,
                second_name,
                int(raw_index),
                None,
            )
            return
        if data.startswith("g2:R:"):
            _, _, pair, raw_signs, raw_index = data.split(":", 4)
            first_id, second_id = _decode_pair(pair)
            if callback.from_user.id not in {first_id, second_id}:
                await callback.answer("Раунд продолжают участники дуэли.")
                return
            sign_codes = _decode_signs(raw_signs)
            if "x" in sign_codes:
                raise ValueError("missing sign")
            first_name, second_name = await compatibility._pair_names(
                bot,
                message,
                first_id,
                second_id,
            )
            await callback.answer("Следующий раунд ⚔️")
            await _render_round(
                message,
                bot,
                duel_series_for_signs(
                    _SIGN_BY_CODE[sign_codes[0]],
                    _SIGN_BY_CODE[sign_codes[1]],
                    first_id,
                    second_id,
                    message.date.date(),
                ),
                first_id,
                second_id,
                first_name,
                second_name,
                int(raw_index),
                sign_codes,
            )
            return
    except (KeyError, TypeError, ValueError):
        await callback.answer("Не получилось продолжить игру.")
        return
    await viral.viral_action(
        callback,
        bot,
        onboarding,
        birth_profile_service,
    )


def install_group_viral_upgrade() -> None:
    if "group_viral_upgrade" in _INSTALL_MARKERS:
        return
    router = group_handlers.router
    router.callback_query.handlers[:] = [
        handler
        for handler in router.callback_query.handlers
        if handler.callback is not viral.viral_action
    ]
    router.callback_query(F.data.startswith(("v:", "g2:")))(viral_action_v2)
    _INSTALL_MARKERS.add("group_viral_upgrade")
