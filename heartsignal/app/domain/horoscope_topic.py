"""Canonical persisted Horoscope topics with deterministic forecast anchors."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from app.domain.horoscope import HoroscopeScope


@dataclass(frozen=True, slots=True)
class HoroscopeTopic:
    scope: HoroscopeScope
    reference_date: date | None

    def __post_init__(self) -> None:
        if self.scope is HoroscopeScope.WEEK_FORECAST:
            if self.reference_date is None or self.reference_date.weekday() != 0:
                raise ValueError("weekly Horoscope topic requires a Monday anchor")
        elif self.scope is HoroscopeScope.MONTH_FORECAST:
            if self.reference_date is None or self.reference_date.day != 1:
                raise ValueError("monthly Horoscope topic requires a month-start anchor")
        elif self.reference_date is not None:
            raise ValueError("non-forecast Horoscope topic cannot contain an anchor")

    @classmethod
    def for_request(
        cls,
        scope: HoroscopeScope,
        reference_date: date | None = None,
    ) -> "HoroscopeTopic":
        resolved = reference_date or datetime.now(UTC).date()
        if scope is HoroscopeScope.WEEK_FORECAST:
            return cls(scope, resolved - timedelta(days=resolved.weekday()))
        if scope is HoroscopeScope.MONTH_FORECAST:
            return cls(scope, resolved.replace(day=1))
        return cls(scope, None)

    @classmethod
    def parse(cls, value: str) -> "HoroscopeTopic":
        scope_value, separator, anchor_value = value.partition("@")
        try:
            scope = HoroscopeScope(scope_value)
        except ValueError as exc:
            raise ValueError("unsupported persisted Horoscope scope") from exc
        if scope in {HoroscopeScope.WEEK_FORECAST, HoroscopeScope.MONTH_FORECAST}:
            if separator != "@" or not anchor_value or "@" in anchor_value:
                raise ValueError("forecast Horoscope topic requires one anchor")
            try:
                anchor = date.fromisoformat(anchor_value)
            except ValueError as exc:
                raise ValueError("invalid persisted Horoscope anchor") from exc
            return cls(scope, anchor)
        if separator:
            raise ValueError("non-forecast Horoscope topic cannot contain an anchor")
        return cls(scope, None)

    def storage_value(self) -> str:
        if self.reference_date is None:
            return self.scope.value
        return f"{self.scope.value}@{self.reference_date.isoformat()}"
