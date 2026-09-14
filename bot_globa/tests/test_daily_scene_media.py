"""Daily forecast delivery stays aligned between manual view and worker delivery."""

from app.bot.scene_media import MEDIA_SCENES, Scene, scene_art


def test_daily_forecast_is_plain_text_but_sign_picker_keeps_art() -> None:
    assert Scene.DAILY_HOROSCOPE not in MEDIA_SCENES
    assert scene_art(Scene.DAILY_HOROSCOPE) is None

    assert Scene.DAILY_ZODIAC in MEDIA_SCENES
    assert scene_art(Scene.DAILY_ZODIAC) is not None
