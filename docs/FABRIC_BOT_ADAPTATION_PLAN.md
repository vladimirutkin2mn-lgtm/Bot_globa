# План адаптации `fabric_bot` под персонального AI-оракула

## 1. Решение

**Проект целесообразно строить на базе подпроекта `ideas/ai-relationship-platform` (HeartSignal) из `fabric_bot`, а не писать нового бота с нуля.**

Проанализированная база: `vladimirutkin2mn-lgtm/fabric_bot`, ветка `main`, commit `3fb6b6151756b5745e748768d878b20b87e1199e`.

HeartSignal уже содержит Telegram/FastAPI/PostgreSQL, LLM orchestration, строгую валидацию ответов, историю разборов, шифрование чувствительных данных, кредиты, платежи, подписки, возвраты, workers, аналитику, Docker, CI и release gates.

Задача — сохранить производственное ядро и заменить домен анализа переписки на персональные символические и астрологические разборы.

---

## 2. Позиционирование

> Персональный AI-оракул — развлекательный и рефлексивный сервис, который помогает взглянуть на вопрос через символы, архетипы, астрологические расчёты и наводящие вопросы. Он не сообщает достоверное будущее и не заменяет профессиональную помощь.

Принципы:

1. Эмоциональная ценность и персонализация важнее заявлений о «точности».
2. Память связывает новые разборы с ранее рассказанным пользователем.
3. Персонажи меняют стиль, но не могут отменить общий safety policy.
4. Продукт не гарантирует события, мысли третьих лиц или конкретные даты.
5. Запрещены продажи через страх, «проклятия» и формирование зависимости.

---

## 3. Главное решение по MVP

Первый MVP включает **четыре направления**.

### 3.1. Таролог

Символический расклад, карты, возможные сценарии и вопросы для рефлексии. Карты выбирает приложение по воспроизводимому seed, а не LLM.

### 3.2. Любовный оракул

Вопросы об отношениях, притяжении, дистанции, границах и выборе следующего шага. Ответ не утверждает, что достоверно знает мысли или чувства другого человека.

### 3.3. Мистический психолог

Архетипы, повторяющиеся сценарии и рефлексивные вопросы без диагнозов и выдачи продукта за психотерапию.

### 3.4. Гороскоп / астролог

Персональный разбор по дате, времени и месту рождения, а также прогноз на выбранный период.

Гороскоп реализуется двумя слоями:

1. `Astrology Calculation Engine` нормализует место и часовой пояс, рассчитывает положения планет, дома и аспекты и возвращает строгий версионированный результат.
2. `LLM Interpreter` объясняет уже рассчитанные данные, связывает их с вопросом и разрешённой памятью, но не может менять или придумывать астрономические данные.

Если время рождения неизвестно, продукт не выдумывает асцендент и дома и явно помечает ограничения расчёта.

### 3.5. Что остаётся после MVP

Нумеролог, толкователь снов, свободный конструктор персонажей, голосовые ответы и расширенные астрологические режимы добавляются только после проверки спроса.

---

## 4. Основной пользовательский путь

1. `/start`, короткое объяснение формата и явное согласие на обработку данных.
2. Выбор одного из четырёх направлений.
3. Выбор темы или периода прогноза.
4. Ввод вопроса и контекста.
5. Для гороскопа — дата, время и место рождения; неизвестное время можно отметить явно.
6. Бесплатный законченный preview.
7. Paywall на полный разбор.
8. Полный ответ с одним contextual follow-up.
9. Сохранение в историю и предложение подтвердить безопасные элементы памяти.
10. Безопасная карточка для публикации без исходного вопроса и приватной истории.

---

## 5. Первый набор товаров

- один бесплатный preview новому пользователю;
- один полный разбор за кредиты;
- пакет разборов;
- персональный натальный профиль;
- недельный или месячный гороскоп;
- совместимость пары как отдельный продукт;
- месячная подписка с кредитами и ежедневным коротким посланием;
- голосовой ответ и годовой прогноз — после MVP.

Существующий credit ledger сохраняется.

---

## 6. Что переиспользуем и меняем

| Область HeartSignal | Решение | Изменение |
|---|---|---|
| Telegram/FastAPI/PostgreSQL/Docker/CI | Переиспользовать | Новый бренд и навигация |
| Users, privacy, encryption | Переиспользовать | Явное согласие на память и BirthProfile |
| LLM provider, retries, schema validation | Переиспользовать | Новые схемы ReadingResult и NatalChartInterpretation |
| Analysis/history | Адаптировать | Переименовать в Reading и убрать обязательную переписку |
| Follow-up entitlement | Переиспользовать | Один follow-up к полному reading |
| Credits/payments/subscriptions/refunds | Переиспользовать | Новый product catalog |
| Conversation parser | Убрать из основного пути | Возможный будущий импорт контекста |
| Relationship scoring | Заменить | Symbolic Engine, Astrology Engine и persona prompts |
| Safety layer | Расширить | Запреты для гаданий, зависимости и high-stakes решений |
| Release gates | Переиспользовать | Oracle/astrology quality datasets |

---

## 7. Целевая архитектура

```text
Telegram / future Web App
        │
        ▼
Intake & Persona Router
        ├── consent / safety pre-check
        ├── topic classification
        ├── birth-data validation when needed
        └── memory retrieval
        │
        ▼
Oracle Orchestrator
        ├── Persona Prompt Registry
        ├── Symbolic Engine
        ├── Astrology Calculation Engine
        ├── User Memory Service
        ├── LLM Provider
        ├── Structured Output Validator
        └── Safety Post-Processor
        │
        ▼
Reading Renderer
        ├── free preview
        ├── full Telegram report
        ├── follow-up
        └── share-card payload
```

### 7.1. Symbolic Engine

Таро-символы генерируются приложением детерминированно по `reading_id`. Retry модели или worker replay не меняют карты.

### 7.2. Astrology Calculation Engine

Астрологический движок получает нормализованные входы и возвращает строгую схему с версией расчёта и provenance. LLM получает только рассчитанные положения и не может их переписать.

---

## 8. Доменная модель

- `Persona` — код, имя, стиль, доступные темы и версии prompts.
- `Reading` — пользователь, направление, тема, статус, стоимость и версии движков.
- `ReadingPrivateContent` — зашифрованные вопрос, контекст и полный результат.
- `ReadingSymbol` — карта/символ, позиция, orientation и seed/version.
- `BirthProfile` — зашифрованные исходные данные рождения и normalized location/timezone.
- `NatalChart` — рассчитанные положения, дома, аспекты, engine version и provenance.
- `MemoryItem` — подтверждённый пользователем факт или повторяющаяся тема.
- `PersonProfile` / `PairProfile` — данные для вопросов о человеке и совместимости.
- `ShareCard` — публичный payload без приватного содержания.
- `DailyMessage` — запланированное послание подписчику.

Финансовые, audit, jobs и release tables сохраняются.

---

## 9. Контракты результатов

`ReadingResult` остаётся строгой схемой и включает title, opening, symbols или chart references, patterns, possible scenarios, reflection questions, practical step, uncertainty note, share payload и safety flags.

Для астрологии добавляется `NatalChartResult` с вычисленными объектами:

- normalized birth datetime and timezone;
- planetary positions;
- houses only when time quality permits;
- aspects;
- calculation engine/version;
- warnings about unknown or approximate inputs.

Renderer формирует preview, full report, follow-up context и share payload из одной валидированной схемы.

---

## 10. Память и персонализация

Два уровня:

1. полная зашифрованная история разборов;
2. компактная память из подтверждённых пользовательских сведений.

Можно сохранять цели, повторяющиеся темы, введённые имена/псевдонимы, прошлые решения, любимого персонажа и настройки тона.

Нельзя сохранять как факт предсказания, предполагаемые мысли третьего лица, диагнозы, измену, беременность, болезнь, смерть, преступление или любую интерпретацию модели без подтверждения пользователя.

Пользователь может просмотреть, удалить, очистить или отключить память. Данные рождения управляются отдельно и также удаляются по запросу.

---

## 11. Prompt-архитектура

Три слоя:

1. общий policy prompt;
2. persona prompt;
3. runtime request с вопросом, разрешённой памятью и рассчитанными символами/астрологическими данными.

Persona не может отменять policy. Версии prompts, schemas, symbolic engine и astrology engine сохраняются в Reading.

---

## 12. Безопасность

Запрещены:

- гарантии любви, богатства, выигрыша и конкретной даты события;
- утверждения о точных мыслях другого человека;
- достоверные выводы об измене, беременности, болезни, смерти, преступлении и проклятии;
- медицинские, юридические, финансовые и азартные решения по раскладу или гороскопу;
- отказ от реальной помощи;
- преследование, шантаж и нарушение границ;
- допродажа через страх;
- механики зависимости и бесконечных повторных гаданий.

При риске насилия, самоповреждения, медицинской угрозе или high-stakes финансовом запросе продукт прекращает мистическую часть и показывает безопасный handoff.

---

## 13. Монетизация и вирусность

Бесплатный preview должен иметь самостоятельную ценность. Платная часть раскрывает полный разбор, сценарии, разрешённую персонализацию, практический шаг и follow-up.

Карточки создаются из отдельного безопасного поля и не содержат исходный вопрос, данные рождения, имена без подтверждения, приватную историю или чувствительные утверждения.

Примеры карточек:

- «Главная энергия месяца»;
- «Что сейчас просит твоего внимания»;
- «Твоя скрытая сильная сторона»;
- «Какой паттерн пора отпустить»;
- «Три главные темы твоей натальной карты».

---

## 14. Стратегия переноса

1. Извлечь `ideas/ai-relationship-platform` из `fabric_bot` с историей.
2. Перенести baseline в отдельную ветку `migration/heartsignal-baseline`.
3. Открыть технический PR без продуктовых изменений.
4. Подтвердить сборку, миграции, тесты и CI.
5. Только после зелёного baseline начинать доменную миграцию маленькими PR.

Финансовые миграции не переписываются задним числом; все изменения выполняются новыми Alembic revisions.

---

## 15. Этапы реализации

### Этап 0 — baseline

- перенос HeartSignal;
- зелёные исходные тесты и CI;
- repository metadata;
- фиксация billing/privacy/release invariants.

### Этап 1 — Tarot vertical slice

- Persona/Reading/ReadingPrivateContent/ReadingSymbol;
- question intake;
- deterministic Symbolic Engine;
- structured result;
- preview/full renderer;
- free entitlement и paid unlock.

### Этап 2 — safety и память

- input/output safety;
- adversarial regression suite;
- MemoryItem и explicit controls;
- contextual follow-up.

### Этап 3 — четыре направления

- Love Oracle;
- Mystical Psychologist;
- BirthProfile и Astrology Calculation Engine;
- Horoscope persona и chart renderer;
- общий prompt registry и quality fixtures.

### Этап 4 — коммерческий запуск

- новый product catalog;
- Stripe/YooKassa staging acceptance;
- подписка и daily messages;
- аналитика, feature flags и release gates.

### Этап 5 — рост

- image share cards;
- referral attribution;
- совместимость пары;
- голос;
- дополнительные направления по данным спроса.

---

## 16. Аналитика MVP

События: onboarding, persona selected, birth profile started/completed, question submitted, preview viewed, paywall viewed, checkout completed, full reading opened, follow-up completed, memory actions, share actions, repeat reading и safety handoff.

Метрики: activation, preview-to-purchase, repeat usage 7/30d, revenue/margin, retention по направлению, share rate, LLM/astrology cost and latency, validation/repair rate, refund, complaint и safety rate.

---

## 17. Критерии ограниченного запуска

- четыре изолированных persona-набора;
- строгие схемы и safe repair;
- deterministic tarot symbols;
- воспроизводимый astrology calculation с provenance;
- неизвестное время рождения не создаёт выдуманные дома/асцендент;
- один free preview без повторной выдачи;
- exactly-once списание;
- replay и follow-up без второго списания;
- полное удаление приватного контента, памяти и BirthProfile;
- safety suite и staging quality gates зелёные;
- production secrets не попадают в логи;
- release-readiness подтверждён для точного commit.

---

## 18. Последовательность pull requests

1. Extract HeartSignal baseline into Bot_globa.
2. Rename product and isolate reusable platform core.
3. Add Reading domain and Tarot vertical slice.
4. Add oracle safety policy and adversarial tests.
5. Add explicit memory and privacy controls.
6. Add Love Oracle persona.
7. Add Mystical Psychologist persona.
8. Add BirthProfile and Astrology Calculation Engine.
9. Add Horoscope persona and chart interpretation.
10. Replace billing catalog and free entitlement.
11. Add safe share payloads and referrals.
12. Run staging acceptance and limited release.

Первый следующий шаг — чистый перенос HeartSignal baseline без одновременной продуктовой переделки.
