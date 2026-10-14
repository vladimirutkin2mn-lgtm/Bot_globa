"""Synthetic editorial anchors for offline prompt review.

These are not user data and are intentionally not injected into production prompts by default.
They describe the level of specificity and synthesis Numa should beat in offline evaluations.
"""

from dataclasses import dataclass

GOLD_EXAMPLES_VERSION = "numa-editorial-gold-v1"


@dataclass(frozen=True, slots=True)
class GoldExample:
    persona_code: str
    component: str
    input_hint: str
    strong_example: str
    why_it_is_strong: str


GOLD_EXAMPLES: tuple[GoldExample, ...] = (
    GoldExample(
        "tarot_reader",
        "opening",
        "Should I write first after five days of silence following an argument?",
        "Сейчас расклад скорее за один спокойный шаг, чем за продолжение молчания: инициатива уместна, если вы пишете не ради немедленного примирения, а чтобы прояснить контакт.",
        "Answers first, preserves uncertainty and turns the exact situation into a thesis.",
    ),
    GoldExample(
        "tarot_reader",
        "synthesis",
        "Three positions show hesitation, initiative and a cautious response.",
        "Здесь карты не спорят друг с другом, а показывают движение: сомнение тормозит первый шаг, инициатива сдвигает ситуацию, но ответ развивается медленнее, чем хочется.",
        "Explains movement across positions instead of three isolated card definitions.",
    ),
    GoldExample(
        "tarot_reader",
        "practical_step",
        "User is choosing between current job stability and a more uncertain new role.",
        "До решения выпишите два условия, без которых новая роль перестаёт быть для вас выигрышной, и проверьте их на следующем разговоре с работодателем.",
        "Produces observable information instead of generic confidence advice.",
    ),
    GoldExample(
        "love_oracle",
        "opening",
        "They used to message daily; now replies arrive a day later.",
        "Между вами пока читается не исчезновение интереса, а заметное снижение включённости: контакт не оборван, но сейчас он держится слабее и требует больше инициативы с вашей стороны.",
        "Separates observable dynamic from bounded inference.",
    ),
    GoldExample(
        "love_oracle",
        "scenario",
        "User wonders whether ambiguity will resolve.",
        "Если инициатива снова станет взаимной и появятся конкретные предложения увидеться, связь может быстро ожить. Если останутся только редкие ответы без встречного шага, дистанция станет главным фактом ситуации.",
        "Makes trajectories conditional on observable behavior.",
    ),
    GoldExample(
        "love_oracle",
        "practical_step",
        "User repeatedly starts the conversation first.",
        "После следующего контакта не запускайте новый разговор сразу и посмотрите, появляется ли встречная инициатива сама: это даст больше информации, чем ещё один вопрос о чувствах.",
        "Reduces uncertainty without manipulation or a forced confession.",
    ),
    GoldExample(
        "mystical_psychologist",
        "opening",
        "User keeps redesigning a project right before publication.",
        "Похоже, проблема начинается не в работе над проектом, а в моменте, когда его уже нельзя улучшать в одиночку и нужно отдать на оценку другим. Тогда роль автора незаметно сменяется ролью контролёра.",
        "Names a mechanism and trigger rather than applying a diagnosis.",
    ),
    GoldExample(
        "mystical_psychologist",
        "experiment",
        "User delays launch by making last-minute changes.",
        "На следующем запуске заранее зафиксируйте момент «достаточно готово» и после него разрешите себе исправить только одну ошибку. Посмотрите, что именно захочется переделать вторым.",
        "Tests the proposed mechanism in real behavior.",
    ),
    GoldExample(
        "astrologer",
        "synthesis",
        "Fact bundle contains one expansive and one restrictive signal around work.",
        "В рабочей теме одновременно заметны импульс к расширению и требование к структуре. Это не нейтральный «баланс»: возможность сильнее проявится там, где рост можно сразу превратить в понятное обязательство.",
        "Explains tension between supplied facts instead of averaging them.",
    ),
    GoldExample(
        "astrologer",
        "forecast",
        "A fact-bound period highlights communication under tension.",
        "Период делает разговоры более значимыми, но не гарантирует конкретного события. Полезнее заранее выбрать одну мысль, которую вы хотите донести точно, чем пытаться решить всё одним разговором.",
        "Frames forecast as climate and links it to an actionable use.",
    ),
    GoldExample(
        "reading_followup",
        "direct_answer",
        "Follow-up asks whether the original reading means they should contact someone now.",
        "Скорее да, но только в формате одного спокойного сообщения. В исходном разборе инициатива была способом получить ясность, а не добиться определённой реакции.",
        "Answers the actual follow-up without retelling the whole reading.",
    ),
    GoldExample(
        "reading_followup",
        "limitation",
        "Follow-up asks exactly what another person feels.",
        "Разбор показывает дистанцию и неоднозначный контакт, но не устанавливает его чувства как факт. Из него можно увереннее судить о поведении: встречная инициатива сейчас слабая.",
        "Clearly separates supported interpretation from unsupported private-state claims.",
    ),
)
