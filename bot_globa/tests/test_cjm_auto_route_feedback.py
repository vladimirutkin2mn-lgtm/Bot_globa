from app.bot.personal_oracle_handlers import (
    choose_route,
    route_feedback,
    should_announce_route,
)


def test_auto_route_feedback_explains_the_selected_practice() -> None:
    love = choose_route("Он два дня не пишет. Стоит ли мне написать ему первой?")
    reflection = choose_route("Почему я снова и снова откладываю важный разговор?")
    work = choose_route("Стоит ли менять работу сейчас?")

    assert "Любовный оракул" in route_feedback(love)
    assert "внутренний" in route_feedback(reflection).casefold()
    assert "Таро" in route_feedback(work)


def test_only_automatic_routing_gets_an_explanation() -> None:
    assert should_announce_route("auto")
    assert not should_announce_route("tarot")
    assert not should_announce_route("love")
