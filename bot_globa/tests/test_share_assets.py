from app.api.share_assets import DAILY_SHARE_CARD_PATH, DAILY_SHARE_CARD_ROUTE


def test_daily_share_card_asset_is_packaged() -> None:
    assert DAILY_SHARE_CARD_ROUTE == "/public/share/numa-daily-v1.jpg"
    assert DAILY_SHARE_CARD_PATH.is_file()
    assert DAILY_SHARE_CARD_PATH.stat().st_size > 4_000
