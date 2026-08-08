"""Localized, payload-free handoffs for unsafe oracle requests."""

from dataclasses import dataclass
from enum import StrEnum

from app.domain.oracle_safety import OracleRiskCategory, OracleSafetyAction


class HandoffResourceKind(StrEnum):
    LOCAL_EMERGENCY_SERVICES = "local_emergency_services"
    TRUSTED_PERSON = "trusted_person"
    CRISIS_DIRECTORY = "crisis_directory"
    MEDICAL_PROFESSIONAL = "medical_professional"
    LEGAL_PROFESSIONAL = "legal_professional"
    FINANCIAL_PROFESSIONAL = "financial_professional"


@dataclass(frozen=True, slots=True)
class HandoffResource:
    kind: HandoffResourceKind
    label: str
    instruction: str
    url: str | None = None


@dataclass(frozen=True, slots=True)
class OracleCrisisHandoff:
    locale: str
    action: OracleSafetyAction
    categories: tuple[OracleRiskCategory, ...]
    title: str
    body: str
    resources: tuple[HandoffResource, ...]
    mystical_flow_stopped: bool = True


class OracleCrisisHandoffService:
    """Build neutral handoffs without accepting or echoing private user text."""

    crisis_directory_url = "https://findahelpline.com/"
    supported_locales = frozenset({"ru", "en"})

    def build(
        self,
        action: OracleSafetyAction,
        categories: tuple[OracleRiskCategory, ...],
        *,
        locale: str | None,
    ) -> OracleCrisisHandoff:
        normalized_locale = self._locale(locale)
        unique_categories = tuple(dict.fromkeys(categories))
        if OracleRiskCategory.SELF_HARM in unique_categories:
            return self._self_harm(action, unique_categories, normalized_locale)
        if OracleRiskCategory.VIOLENCE_OR_STALKING in unique_categories:
            return self._violence(action, unique_categories, normalized_locale)
        return self._high_stakes(action, unique_categories, normalized_locale)

    @staticmethod
    def render_text(handoff: OracleCrisisHandoff) -> str:
        resource_lines = [
            f"• {resource.label}: {resource.instruction}"
            + (f"\n  {resource.url}" if resource.url else "")
            for resource in handoff.resources
        ]
        resources = "\n".join(resource_lines)
        return (
            f"{handoff.title}\n\n{handoff.body}\n\n{resources}"
            if resources
            else (f"{handoff.title}\n\n{handoff.body}")
        )

    def _self_harm(
        self,
        action: OracleSafetyAction,
        categories: tuple[OracleRiskCategory, ...],
        locale: str,
    ) -> OracleCrisisHandoff:
        if locale == "ru":
            return OracleCrisisHandoff(
                locale=locale,
                action=action,
                categories=categories,
                title="Сейчас важнее ваша безопасность",
                body=(
                    "Мне жаль, что вам сейчас так тяжело. Я не буду продолжать мистический "
                    "разбор. Если вы можете причинить себе вред прямо сейчас, обратитесь в "
                    "местную экстренную службу или попросите человека рядом остаться с вами."
                ),
                resources=(
                    HandoffResource(
                        HandoffResourceKind.LOCAL_EMERGENCY_SERVICES,
                        "Экстренная помощь",
                        "При непосредственной опасности обратитесь в местную экстренную службу.",
                    ),
                    HandoffResource(
                        HandoffResourceKind.TRUSTED_PERSON,
                        "Человек рядом",
                        "Позвоните тому, кому доверяете, и прямо попросите побыть с вами.",
                    ),
                    HandoffResource(
                        HandoffResourceKind.CRISIS_DIRECTORY,
                        "Линия кризисной поддержки",
                        "Найдите доступную службу для вашей страны и языка.",
                        self.crisis_directory_url,
                    ),
                ),
            )
        return OracleCrisisHandoff(
            locale=locale,
            action=action,
            categories=categories,
            title="Your safety matters more right now",
            body=(
                "I am sorry this feels so difficult. I will not continue the mystical reading. "
                "If you may hurt yourself now, contact local emergency services or ask someone "
                "nearby to stay with you."
            ),
            resources=(
                HandoffResource(
                    HandoffResourceKind.LOCAL_EMERGENCY_SERVICES,
                    "Emergency help",
                    "Contact local emergency services if there is immediate danger.",
                ),
                HandoffResource(
                    HandoffResourceKind.TRUSTED_PERSON,
                    "Someone you trust",
                    "Call them and clearly ask them to stay with you.",
                ),
                HandoffResource(
                    HandoffResourceKind.CRISIS_DIRECTORY,
                    "Crisis support line",
                    "Find an available service for your country and language.",
                    self.crisis_directory_url,
                ),
            ),
        )

    def _violence(
        self,
        action: OracleSafetyAction,
        categories: tuple[OracleRiskCategory, ...],
        locale: str,
    ) -> OracleCrisisHandoff:
        if locale == "ru":
            return OracleCrisisHandoff(
                locale=locale,
                action=action,
                categories=categories,
                title="Я не могу продолжить этот запрос",
                body=(
                    "Я не буду делать мистический разбор, который помогает причинить вред, "
                    "преследовать или тайно отслеживать человека. Если кому-то угрожает "
                    "непосредственная опасность, обратитесь в местную экстренную службу."
                ),
                resources=(
                    HandoffResource(
                        HandoffResourceKind.LOCAL_EMERGENCY_SERVICES,
                        "Экстренная помощь",
                        "Обратитесь в местную экстренную службу при непосредственной опасности.",
                    ),
                    HandoffResource(
                        HandoffResourceKind.TRUSTED_PERSON,
                        "Безопасная пауза",
                        "Отойдите от ситуации и свяжитесь с человеком, которому доверяете.",
                    ),
                ),
            )
        return OracleCrisisHandoff(
            locale=locale,
            action=action,
            categories=categories,
            title="I cannot continue this request",
            body=(
                "I will not provide a mystical reading that helps harm, stalk, or secretly "
                "track someone. If anyone is in immediate danger, contact local emergency "
                "services."
            ),
            resources=(
                HandoffResource(
                    HandoffResourceKind.LOCAL_EMERGENCY_SERVICES,
                    "Emergency help",
                    "Contact local emergency services if there is immediate danger.",
                ),
                HandoffResource(
                    HandoffResourceKind.TRUSTED_PERSON,
                    "Create distance",
                    "Step away from the situation and contact someone you trust.",
                ),
            ),
        )

    def _high_stakes(
        self,
        action: OracleSafetyAction,
        categories: tuple[OracleRiskCategory, ...],
        locale: str,
    ) -> OracleCrisisHandoff:
        resources = self._professional_resources(categories, locale)
        if locale == "ru":
            return OracleCrisisHandoff(
                locale=locale,
                action=action,
                categories=categories,
                title="Этот вопрос требует профильной помощи",
                body=(
                    "Я прекращаю мистическую часть ответа. Карты не могут безопасно решать "
                    "медицинские, юридические, финансовые или азартные вопросы. Обратитесь к "
                    "квалифицированному специалисту и опирайтесь на проверяемые факты."
                ),
                resources=resources,
            )
        return OracleCrisisHandoff(
            locale=locale,
            action=action,
            categories=categories,
            title="This question needs qualified help",
            body=(
                "I am stopping the mystical part of the response. Cards cannot safely decide "
                "medical, legal, financial, or gambling matters. Contact a qualified "
                "professional and rely on verifiable information."
            ),
            resources=resources,
        )

    @staticmethod
    def _professional_resources(
        categories: tuple[OracleRiskCategory, ...],
        locale: str,
    ) -> tuple[HandoffResource, ...]:
        resources: list[HandoffResource] = []
        ru = locale == "ru"
        if OracleRiskCategory.MEDICAL in categories:
            resources.append(
                HandoffResource(
                    HandoffResourceKind.MEDICAL_PROFESSIONAL,
                    "Медицинская помощь" if ru else "Medical help",
                    (
                        "Обратитесь к врачу или лицензированному медицинскому специалисту."
                        if ru
                        else "Contact a doctor or licensed medical professional."
                    ),
                )
            )
        if OracleRiskCategory.LEGAL in categories:
            resources.append(
                HandoffResource(
                    HandoffResourceKind.LEGAL_PROFESSIONAL,
                    "Юридическая помощь" if ru else "Legal help",
                    (
                        "Обратитесь к квалифицированному юристу в вашей юрисдикции."
                        if ru
                        else "Contact a qualified lawyer in your jurisdiction."
                    ),
                )
            )
        if OracleRiskCategory.FINANCIAL_OR_GAMBLING in categories:
            resources.append(
                HandoffResource(
                    HandoffResourceKind.FINANCIAL_PROFESSIONAL,
                    "Финансовая помощь" if ru else "Financial help",
                    (
                        "Не принимайте решение по раскладу; обратитесь к независимому специалисту."
                        if ru
                        else "Do not decide from a reading; contact an independent professional."
                    ),
                )
            )
        return tuple(resources)

    @classmethod
    def _locale(cls, locale: str | None) -> str:
        normalized = (locale or "").casefold().replace("_", "-").split("-", 1)[0]
        return normalized if normalized in cls.supported_locales else "en"
