from app.domain.natal_chart import ZodiacSign
from app.services.daily_horoscope_generation import DailyEditorialResult, DailyEditorialSign


def test_daily_editorial_schema_requires_canonical_payload_shape() -> None:
    result = DailyEditorialResult(
        theme="Сегодня важнее точность, чем скорость",
        signs=[
            DailyEditorialSign(
                sign=sign,
                text=f"Для {sign.value} сегодня есть конкретный повод проверить один следующий шаг.",
            )
            for sign in ZodiacSign
        ],
    )

    assert len(result.signs) == 12
