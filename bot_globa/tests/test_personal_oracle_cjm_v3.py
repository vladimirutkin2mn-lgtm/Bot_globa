from app.bot.horoscope_flow import topics_keyboard as astrology_topics_keyboard
from app.bot.keyboards import main_menu_keyboard, more_menu_keyboard
from app.bot.personal_oracle_handlers import choose_route, personal_oracle_safety_intake
from app.bot.persona_flows import LOVE_ORACLE_FLOW, MYSTICAL_PSYCHOLOGIST_FLOW, TAROT_FLOW
from app.bot.states import IntakeStates


def _buttons(keyboard):
    return [button for row in keyboard.inline_keyboard for button in row]


def test_main_menu_is_one_oracle_plus_explicit_practices() -> None:
    buttons = _buttons(main_menu_keyboard())
    callbacks = {button.callback_data for button in buttons}
    labels = {button.text for button in buttons}

    assert "oracle:auto" in callbacks
    assert "oracle:tarot" in callbacks
    assert "oracle:love" in callbacks
    assert "oracle:astro" in callbacks
    assert "✨ Рассказать Numa" in labels
    assert not any((callback or "").startswith("psy:") for callback in callbacks)
    assert not any((callback or "").startswith("tarot:topic:") for callback in callbacks)
    assert not any((callback or "").startswith("love:topic:") for callback in callbacks)


def test_more_menu_is_utilities_not_a_second_persona_storefront() -> None:
    buttons = _buttons(more_menu_keyboard())
    callbacks = {button.callback_data for button in buttons}

    assert callbacks == {"menu:memory", "menu:balance", "menu:privacy", "menu:home"}


def test_astrology_menu_exposes_only_astrology_native_scopes() -> None:
    callbacks = {button.callback_data for button in _buttons(astrology_topics_keyboard())}

    assert "astro:topic:natal_profile" in callbacks
    assert "astro:topic:day_forecast" in callbacks
    assert "astro:topic:week_forecast" in callbacks
    assert "astro:topic:month_forecast" in callbacks
    assert "astro:topic:decision" not in callbacks
    assert "astro:topic:love" not in callbacks


def test_numa_routes_relationship_questions_to_love_oracle() -> None:
    communication = choose_route("Мы давно не общались. Стоит ли мне написать ему первой?")
    feelings = choose_route("Что он ко мне чувствует после нашей последней встречи?")

    assert communication.flow is LOVE_ORACLE_FLOW
    assert communication.topic == "communication"
    assert feelings.flow is LOVE_ORACLE_FLOW
    assert feelings.topic == "love"


def test_numa_routes_repeating_inner_pattern_to_internal_reflection_mode() -> None:
    choice = choose_route("Почему я снова и снова отступаю, когда всё начинает получаться?")

    assert choice.flow is MYSTICAL_PSYCHOLOGIST_FLOW
    assert choice.topic == "repeating_pattern"


def test_numa_routes_choice_and_open_questions_to_tarot() -> None:
    decision = choose_route("Я выбираю между двумя предложениями. Какой вариант мне ближе?")
    open_question = choose_route("Что мне сейчас важно увидеть в своей ситуации?")

    assert decision.flow is TAROT_FLOW
    assert decision.topic == "decision"
    assert open_question.flow is TAROT_FLOW
    assert open_question.topic == "general_forecast"


def test_personal_oracle_free_text_is_registered_as_safety_intake() -> None:
    intake = personal_oracle_safety_intake()

    assert intake.persona_code == "personal_oracle"
    assert intake.question_state == IntakeStates.waiting_for_conversation.state
