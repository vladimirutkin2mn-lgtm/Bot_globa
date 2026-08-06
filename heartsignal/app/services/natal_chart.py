"""Deterministic natal chart facts calculated from normalized encrypted inputs."""

from collections.abc import Callable
from itertools import combinations
from typing import Any, Protocol
from uuid import UUID

import astronomy

from app.domain.birth_profile import (
    CURRENT_BIRTH_PROFILE_NORMALIZATION_VERSION,
    BirthProfileInput,
)
from app.domain.natal_chart import (
    NATAL_CHART_ENGINE_VERSION,
    NATAL_CHART_HOUSE_SYSTEM,
    NATAL_CHART_SCHEMA_VERSION,
    NatalAspect,
    NatalAspectKind,
    NatalBody,
    NatalChartResult,
    NatalHouse,
    NatalPlanetPosition,
    NatalTimePrecision,
    ZodiacSign,
)

_SIGNS = tuple(ZodiacSign)
_BODIES: tuple[tuple[NatalBody, Any], ...] = (
    (NatalBody.SUN, astronomy.Body.Sun),
    (NatalBody.MOON, astronomy.Body.Moon),
    (NatalBody.MERCURY, astronomy.Body.Mercury),
    (NatalBody.VENUS, astronomy.Body.Venus),
    (NatalBody.MARS, astronomy.Body.Mars),
    (NatalBody.JUPITER, astronomy.Body.Jupiter),
    (NatalBody.SATURN, astronomy.Body.Saturn),
    (NatalBody.URANUS, astronomy.Body.Uranus),
    (NatalBody.NEPTUNE, astronomy.Body.Neptune),
    (NatalBody.PLUTO, astronomy.Body.Pluto),
)
_ASPECTS: tuple[tuple[NatalAspectKind, int, int], ...] = (
    (NatalAspectKind.CONJUNCTION, 0_000, 8_000),
    (NatalAspectKind.SEXTILE, 60_000, 4_000),
    (NatalAspectKind.SQUARE, 90_000, 6_000),
    (NatalAspectKind.TRINE, 120_000, 6_000),
    (NatalAspectKind.OPPOSITION, 180_000, 8_000),
)


class NatalChartCalculationError(RuntimeError):
    """Safe calculation failure without birth data in the error message."""


class BirthProfileUnavailableError(LookupError):
    """No authorized active BirthProfile is available for calculation."""


class BirthProfileOperationRunner(Protocol):
    async def use_profile(
        self,
        user_id: UUID,
        operation: Callable[[BirthProfileInput], NatalChartResult],
    ) -> NatalChartResult | None: ...


class NatalChartCalculator(Protocol):
    def calculate(self, profile: BirthProfileInput) -> NatalChartResult: ...


class ConsentedNatalChartService:
    """Calculate while the authorized encrypted profile remains user-locked."""

    def __init__(
        self,
        profiles: BirthProfileOperationRunner,
        calculator: NatalChartCalculator,
    ) -> None:
        self._profiles = profiles
        self._calculator = calculator

    async def calculate_for_user(self, user_id: UUID) -> NatalChartResult:
        result = await self._profiles.use_profile(
            user_id,
            self._calculator.calculate,
        )
        if result is None:
            raise BirthProfileUnavailableError("active birth profile is required")
        return result


class AstronomyEngineNatalChartCalculator:
    """Calculate tropical geocentric positions and deterministic equal houses."""

    def calculate(self, profile: BirthProfileInput) -> NatalChartResult:
        utc = profile.utc_calculation_datetime()
        astro_time = astronomy.Time.Make(
            utc.year,
            utc.month,
            utc.day,
            utc.hour,
            utc.minute,
            utc.second + utc.microsecond / 1_000_000,
        )
        planets = tuple(
            self._planet_position(body, engine_body, astro_time)
            for body, engine_body in _BODIES
        )
        aspects = self._aspects(planets)
        if profile.time_known:
            ascendant = self._ascendant(astro_time, profile.latitude, profile.longitude)
            houses = tuple(
                NatalHouse(
                    number=number,
                    cusp_longitude_millidegrees=(ascendant + (number - 1) * 30_000)
                    % 360_000,
                    sign=self._sign(
                        (ascendant + (number - 1) * 30_000) % 360_000
                    ),
                )
                for number in range(1, 13)
            )
            precision = NatalTimePrecision.EXACT
            assumption = None
            house_system = NATAL_CHART_HOUSE_SYSTEM
        else:
            ascendant = None
            houses = ()
            precision = NatalTimePrecision.DATE_ONLY
            assumption = "local_noon"
            house_system = None
        return NatalChartResult(
            schema_version=NATAL_CHART_SCHEMA_VERSION,
            engine_version=NATAL_CHART_ENGINE_VERSION,
            normalization_version=CURRENT_BIRTH_PROFILE_NORMALIZATION_VERSION,
            time_precision=precision,
            calculation_utc=utc,
            calculation_assumption=assumption,
            planets=planets,
            aspects=aspects,
            houses=houses,
            ascendant_longitude_millidegrees=ascendant,
            house_system=house_system,
        )

    def _planet_position(
        self,
        body: NatalBody,
        engine_body: Any,
        astro_time: Any,
    ) -> NatalPlanetPosition:
        longitude = self._longitude(engine_body, astro_time)
        before = self._longitude(engine_body, astro_time.AddDays(-0.5))
        after = self._longitude(engine_body, astro_time.AddDays(0.5))
        motion = self._signed_angle(after - before)
        longitude_millidegrees = self._millidegrees(longitude)
        return NatalPlanetPosition(
            body=body,
            longitude_millidegrees=longitude_millidegrees,
            sign=self._sign(longitude_millidegrees),
            sign_degree_millidegrees=longitude_millidegrees % 30_000,
            retrograde=motion < 0.0,
        )

    @staticmethod
    def _longitude(engine_body: Any, astro_time: Any) -> float:
        vector = astronomy.GeoVector(engine_body, astro_time, True)
        return float(astronomy.Ecliptic(vector).elon) % 360.0

    def _aspects(
        self,
        planets: tuple[NatalPlanetPosition, ...],
    ) -> tuple[NatalAspect, ...]:
        found: list[NatalAspect] = []
        for first, second in combinations(planets, 2):
            separation = abs(first.longitude_millidegrees - second.longitude_millidegrees)
            separation = min(separation, 360_000 - separation)
            match = min(
                _ASPECTS,
                key=lambda candidate: abs(separation - candidate[1]),
            )
            kind, exact_angle, maximum_orb = match
            orb = abs(separation - exact_angle)
            if orb > maximum_orb:
                continue
            first_body, second_body = sorted(
                (first.body, second.body),
                key=lambda body: body.value,
            )
            found.append(
                NatalAspect(
                    first_body=first_body,
                    second_body=second_body,
                    kind=kind,
                    separation_millidegrees=separation,
                    orb_millidegrees=orb,
                )
            )
        return tuple(
            sorted(
                found,
                key=lambda aspect: (
                    aspect.first_body.value,
                    aspect.second_body.value,
                    aspect.kind.value,
                ),
            )
        )

    def _ascendant(self, astro_time: Any, latitude: float, longitude: float) -> int:
        if abs(latitude) >= 89.999:
            raise NatalChartCalculationError(
                "natal houses are unavailable at the selected polar latitude"
            )
        observer = astronomy.Observer(latitude, longitude, 0.0)
        rotation = astronomy.CombineRotation(
            astronomy.Rotation_ECT_EQD(astro_time),
            astronomy.Rotation_EQD_HOR(astro_time, observer),
        )

        def horizon(longitude_degrees: float) -> tuple[float, float]:
            ecliptic = astronomy.VectorFromSphere(
                astronomy.Spherical(0.0, longitude_degrees % 360.0, 1.0),
                astro_time,
            )
            horizontal = astronomy.RotateVector(rotation, ecliptic)
            sphere = astronomy.HorizonFromVector(
                horizontal,
                astronomy.Refraction.Airless,
            )
            return float(sphere.lat), float(sphere.lon)

        roots: list[float] = []
        step = 2.0
        previous_longitude = 0.0
        previous_altitude, _ = horizon(previous_longitude)
        for index in range(1, int(360 / step) + 1):
            current_longitude = index * step
            current_altitude, _ = horizon(current_longitude)
            if previous_altitude == 0.0:
                roots.append(previous_longitude % 360.0)
            elif previous_altitude * current_altitude < 0.0:
                roots.append(
                    self._bisect_horizon(
                        horizon,
                        previous_longitude,
                        current_longitude,
                        previous_altitude,
                    )
                )
            previous_longitude = current_longitude
            previous_altitude = current_altitude
        unique_roots: list[float] = []
        for root in roots:
            if all(
                self._angular_distance(root, existing) > 0.01
                for existing in unique_roots
            ):
                unique_roots.append(root)
        if not unique_roots:
            raise NatalChartCalculationError(
                "unable to calculate the eastern ecliptic horizon"
            )
        ascendant = min(
            unique_roots,
            key=lambda root: self._angular_distance(horizon(root)[1], 90.0),
        )
        if self._angular_distance(horizon(ascendant)[1], 90.0) > 90.0:
            raise NatalChartCalculationError(
                "unable to identify the eastern ecliptic horizon"
            )
        return self._millidegrees(ascendant)

    @staticmethod
    def _bisect_horizon(
        horizon: Any,
        left: float,
        right: float,
        left_altitude: float,
    ) -> float:
        for _ in range(40):
            midpoint = (left + right) / 2.0
            midpoint_altitude, _ = horizon(midpoint)
            if abs(midpoint_altitude) < 1.0e-10:
                return midpoint % 360.0
            if left_altitude * midpoint_altitude <= 0.0:
                right = midpoint
            else:
                left = midpoint
                left_altitude = midpoint_altitude
        return ((left + right) / 2.0) % 360.0

    @staticmethod
    def _millidegrees(value: float) -> int:
        return round((value % 360.0) * 1000.0) % 360_000

    @staticmethod
    def _sign(longitude_millidegrees: int) -> ZodiacSign:
        return _SIGNS[longitude_millidegrees // 30_000]

    @staticmethod
    def _signed_angle(value: float) -> float:
        return (value + 540.0) % 360.0 - 180.0

    @staticmethod
    def _angular_distance(first: float, second: float) -> float:
        return abs((first - second + 180.0) % 360.0 - 180.0)
