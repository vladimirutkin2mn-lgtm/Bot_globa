# MVP backlog — персональный AI-оракул

Этот backlog переводит архитектурный план в последовательность небольших pull requests. Приоритет — как можно раньше получить работающий paid vertical slice, не переписывая зрелые billing, privacy и release-механизмы HeartSignal.

Обозначения:

- **P0** — блокирует MVP;
- **P1** — нужно для ограниченного коммерческого запуска;
- **P2** — рост после подтверждения спроса;
- **S/M/L** — относительный размер задачи, а не календарная оценка.

---

## Milestone 0 — перенести и зафиксировать рабочую базу

### ORA-001 · Extract HeartSignal subtree — P0 / L

- [ ] Получить split-ветку из `fabric_bot/ideas/ai-relationship-platform` с сохранением истории.
- [ ] Импортировать её в отдельную ветку `migration/heartsignal-baseline`.
- [ ] Поднять PostgreSQL и приложение через Docker Compose.
- [ ] Запустить весь исходный test suite.
- [ ] Зафиксировать baseline commit и результат тестов в PR.
- [ ] Не менять поведение приложения в этом PR.

**Acceptance:** код собирается, миграции применяются на чистую БД, исходные тесты зелёные, CI работает в `Bot_globa`.

### ORA-002 · Repository and package identity — P0 / S

- [ ] Переименовать package/project metadata.
- [ ] Обновить README, env example, Docker image names и CI labels.
- [ ] Удалить ссылки на старый repository deployment.
- [ ] Проверить отсутствие секретов и production identifiers.

**Acceptance:** поиск по старому имени не находит пользовательских текстов и deployment identifiers; исторические migration IDs не переписываются.

### ORA-003 · Freeze platform invariants — P0 / M

- [ ] Описать invariants для ledger, purchases, subscriptions, refunds и follow-up entitlement.
- [ ] Добавить characterization tests перед доменной переделкой.
- [ ] Зафиксировать privacy deletion и encryption round-trip tests.

**Acceptance:** тесты падают при повторном списании, двойной выдаче entitlement, утечке plaintext или неидемпотентном webhook replay.

---

## Milestone 1 — один работающий расклад от вопроса до оплаты

### ORA-101 · Reading domain — P0 / L

- [ ] Добавить новые Alembic migrations.
- [ ] Создать `Persona`, `Reading`, `ReadingPrivateContent`, `ReadingSymbol`.
- [ ] Добавить статусы `draft`, `generating`, `preview_ready`, `full_ready`, `failed`, `deleted`.
- [ ] Зашифровать question, optional context и full output.
- [ ] Добавить repository/service слой без Telegram-зависимостей.

**Acceptance:** CRUD и state transitions покрыты unit/integration tests; sensitive fields отсутствуют в plaintext БД и логах.

### ORA-102 · Persona registry — P0 / M

- [ ] Создать registry с versioned persona definitions.
- [ ] Реализовать persona `tarot_reader_v1`.
- [ ] Разделить global policy, persona style и runtime request.
- [ ] Сохранять persona/prompt/schema versions в `Reading`.
- [ ] Запретить persona prompt переопределять global policy.

**Acceptance:** один и тот же reading можно воспроизвести с сохранёнными версиями; неизвестная/выключенная persona не запускается.

### ORA-103 · Deterministic symbolic engine — P0 / M

- [ ] Завести versioned catalog карт/символов.
- [ ] Выбирать символы по seed, связанному с `reading_id`.
- [ ] Поддержать spread positions и upright/reversed configuration.
- [ ] Передавать модели уже выбранные символы.
- [ ] Не менять расклад при LLM retry или worker replay.

**Acceptance:** повторный запуск одного reading возвращает те же symbol IDs, positions и orientations.

### ORA-104 · Structured ReadingResult — P0 / L

- [ ] Описать строгую Pydantic-схему результата.
- [ ] Добавить provider adapter, validation и один controlled repair retry.
- [ ] Проверять соответствие symbol IDs входному раскладу.
- [ ] Разделить model result и Telegram renderer.
- [ ] Добавить golden fixtures для типовых тем.

**Acceptance:** невалидный JSON не попадает пользователю; модель не может подменить выбранные карты; repair metrics доступны.

### ORA-105 · Telegram intake — P0 / L

- [ ] Новый `/start` и onboarding.
- [ ] 18+ gate и короткое объяснение развлекательного формата.
- [ ] Выбор persona и topic.
- [ ] Ввод вопроса и необязательного контекста.
- [ ] Возможность отменить/исправить вопрос до генерации.
- [ ] Защита от двойного callback/retry.

**Acceptance:** пользователь проходит путь от нового аккаунта до preview; повтор Telegram update не создаёт второй reading.

### ORA-106 · Preview/full renderer — P0 / M

- [ ] Сформировать законченный бесплатный preview.
- [ ] Сформировать полный Telegram report из той же схемы.
- [ ] Исключить приватные поля из preview analytics/logging.
- [ ] Добавить pagination для длинного ответа.
- [ ] Сохранить безопасный replay готового результата.

**Acceptance:** preview и full не противоречат друг другу; replay не вызывает LLM и не списывает кредиты повторно.

### ORA-107 · Free entitlement and paid unlock — P0 / L

- [ ] Создать one-time free preview entitlement для нового пользователя.
- [ ] Добавить SKU `reading_single`.
- [ ] Связать full generation/unlock с существующим ledger.
- [ ] Списывать exactly once после подтверждённого entitlement.
- [ ] Обработать race между callback, webhook и worker replay.

**Acceptance:** один пользователь не получает бесконечные free previews; paid reading не списывается дважды; после восстановления worker результат доступен.

---

## Milestone 2 — безопасность как часть движка

### ORA-201 · Oracle input risk classifier — P0 / L

- [ ] Определять self-harm, violence/stalking, medical, legal, financial/gambling и high-stakes certainty requests.
- [ ] Разделить `allow`, `allow_with_limits`, `handoff`, `block`.
- [ ] Не передавать заблокированный запрос в persona prompt.
- [ ] Сохранять только минимальную audit-категорию без чувствительного текста.

**Acceptance:** adversarial fixture set стабильно маршрутизируется; blocked content не генерирует мистический ответ.

### ORA-202 · Output safety validator — P0 / L

- [ ] Ловить гарантии будущего и точные даты как факты.
- [ ] Ловить утверждения о мыслях третьего лица.
- [ ] Ловить смерть, болезнь, беременность, измену, преступление и проклятие как “достоверные выводы”.
- [ ] Ловить страховые upsell-паттерны и зависимость.
- [ ] Делать safe repair либо заменять ответ безопасным fallback.

**Acceptance:** запрещённые паттерны покрыты тестами; невалидный ответ не показывается и не становится share payload.

### ORA-203 · Crisis and real-world handoffs — P0 / M

- [ ] Создать отдельные neutral templates для кризиса, насилия и медицинских симптомов.
- [ ] В чувствительном сценарии прекращать гадательную часть.
- [ ] Добавить локализуемую конфигурацию ресурсов помощи.
- [ ] Не использовать такой handoff для маркетинга или upsell.

**Acceptance:** handoff отображается вместо расклада; событие аналитики не содержит исходный текст.

### ORA-204 · Safety regression suite — P0 / M

- [ ] Набор минимум из benign, ambiguous и adversarial сценариев для всех persona.
- [ ] Проверка prompt injection внутри вопроса пользователя.
- [ ] Проверка malicious memory items.
- [ ] Проверка share-card sanitization.
- [ ] Подключить suite к LLM staging quality gate.

**Acceptance:** release readiness блокирует деплой при safety regression.

---

## Milestone 3 — персональный оракул с памятью

### ORA-301 · Memory model and consent — P0 / L

- [ ] Добавить `MemoryItem` с source reading, type, confidence, timestamps и deletion state.
- [ ] Получать явное согласие на долгосрочную память.
- [ ] По умолчанию не сохранять model speculation.
- [ ] Ограничить типы разрешённых memory facts.
- [ ] Шифровать чувствительное значение.

**Acceptance:** без consent новый memory item не создаётся; speculative output невозможно сохранить как fact.

### ORA-302 · Memory extraction — P0 / L

- [ ] Извлекать candidate items только из пользовательского вопроса/подтверждённых данных.
- [ ] Дедуплицировать повторяющиеся темы и людей.
- [ ] Хранить source IDs и provenance.
- [ ] Ограничить число items, отправляемых в один prompt.
- [ ] Добавить expiry/retention policy.

**Acceptance:** extractor не превращает интерпретацию модели в биографический факт; prompt context имеет фиксированный лимит.

### ORA-303 · User memory controls — P0 / M

- [ ] Экран “Что я помню”.
- [ ] Удаление отдельного элемента.
- [ ] Полная очистка.
- [ ] Отключение/повторное включение памяти.
- [ ] Подтверждение необратимого удаления.

**Acceptance:** удалённый item физически/криптографически недоступен и не появляется в следующих prompts.

### ORA-304 · Contextual continuity — P1 / M

- [ ] Показывать пользователю, когда используется прошлый контекст.
- [ ] Добавлять source-aware формулировки “ранее ты рассказывала…”.
- [ ] Не выдавать continuity за подтверждение предсказания.
- [ ] Добавить opt-out для конкретного reading.

**Acceptance:** пользователь понимает происхождение персонализации и может исключить память из запроса.

### ORA-305 · Paid contextual follow-up — P0 / M

- [ ] Адаптировать существующий follow-up entitlement.
- [ ] Один follow-up входит в полный reading.
- [ ] Ответ grounding только на текущем reading и разрешённой памяти.
- [ ] Exactly-once consumption и безопасный replay.

**Acceptance:** follow-up не создаёт новый расклад, не меняет символы и не списывается повторно.

---

## Milestone 4 — три персонажа и продуктовый каталог

### ORA-401 · Love Oracle persona — P0 / M

- [ ] Новый prompt/style pack.
- [ ] Специальный запрет на claims о точных мыслях/чувствах другого человека.
- [ ] Темы: дистанция, границы, выбор, коммуникация, повторяющийся паттерн.
- [ ] Golden и adversarial tests.

**Acceptance:** ответы остаются рефлексивными, не подтверждают измену и не советуют преследование/манипуляцию.

### ORA-402 · Mystical Psychologist persona — P0 / M

- [ ] Новый prompt/style pack.
- [ ] Не использовать клинические диагнозы и псевдотерапевтические утверждения.
- [ ] Делать акцент на архетипах, наблюдениях и вопросах.
- [ ] Golden и adversarial tests.

**Acceptance:** persona не называет расстройства и не выдаёт себя за лицензированного специалиста.

### ORA-403 · Product catalog migration — P0 / M

- [ ] Создать versioned catalog новых SKU.
- [ ] Убрать relationship-analysis labels из checkout и receipts.
- [ ] Настроить credits для single/pack/subscription.
- [ ] Сохранить provider reconciliation и refund paths.
- [ ] Проверить Stripe/YooKassa sandbox acceptance.

**Acceptance:** каждый provider event однозначно связан с новым SKU; refund возвращает право/деньги по существующим invariants.

### ORA-404 · Subscription and daily message entitlement — P1 / L

- [ ] Выдавать подписочные кредиты exactly once за период.
- [ ] Добавить opt-in на daily message.
- [ ] Ограничить частоту и тихие часы пользователя.
- [ ] Не создавать тревожные push-тексты.
- [ ] Позволить отключить сообщения отдельно от подписки.

**Acceptance:** retry scheduler не создаёт дубликаты; отписка от daily messages применяется немедленно.

---

## Milestone 5 — вирусность без утечки приватности

### ORA-501 · Safe share payload — P1 / M

- [ ] Генерировать headline/short text как часть structured result.
- [ ] Пропускать payload через отдельный safety/sensitivity validator.
- [ ] Не включать вопрос, контекст, память и имена по умолчанию.
- [ ] Дать пользователю preview и явное подтверждение.

**Acceptance:** карточка может быть опубликована без раскрытия приватного reading; unsafe payload блокируется.

### ORA-502 · Telegram sharing and attribution — P1 / M

- [ ] Создать deep link/referral token без user ID в открытом виде.
- [ ] Добавить Telegram share action.
- [ ] Атрибутировать start/activation/purchase.
- [ ] Установить TTL и abuse limits для token.

**Acceptance:** переход по ссылке не раскрывает владельца reading; повтор/бот-трафик не раздаёт unlimited rewards.

### ORA-503 · Image card renderer — P2 / L

- [ ] Versioned visual templates.
- [ ] Safe typography/layout для длинного текста.
- [ ] Object storage lifecycle и deletion hooks.
- [ ] Alt text/accessibility.

**Acceptance:** удаление аккаунта удаляет связанные assets; renderer не получает исходный приватный вопрос.

---

## Milestone 6 — аналитика и ограниченный запуск

### ORA-601 · Product event taxonomy — P0 / M

- [ ] Реализовать события из архитектурного плана.
- [ ] Ввести anonymous/user-scoped identifiers по privacy правилам.
- [ ] Не логировать вопросы и полный текст readings.
- [ ] Проверить event deduplication.

**Acceptance:** funnel и retention считаются без доступа к приватному содержимому.

### ORA-602 · Cost and quality observability — P0 / M

- [ ] Tokens/cost/latency по provider, model, persona и prompt version.
- [ ] JSON validation и repair rate.
- [ ] Safety fallback/handoff rate.
- [ ] Billing/refund/reconciliation health.
- [ ] Алерты без sensitive payloads.

**Acceptance:** можно определить дорогую или нестабильную persona/prompt version без просмотра пользовательского текста.

### ORA-603 · Oracle staging quality gate — P0 / L

- [ ] Fixed evaluation dataset по персонажам и темам.
- [ ] Structural, safety и style assertions.
- [ ] Проверка deployed prompt/schema/model versions.
- [ ] Артефакт с provenance и сроком действия.
- [ ] Интеграция с существующим release-readiness control plane.

**Acceptance:** stale/missing/failed quality evidence блокирует production release.

### ORA-604 · Limited-release controls — P0 / M

- [ ] Feature flag/allowlist или процентный rollout.
- [ ] Kill switch для LLM generation и отдельных persona.
- [ ] Spend cap и rate limits.
- [ ] Runbook для provider outage, unsafe output spike и billing incident.
- [ ] Rollback rehearsal.

**Acceptance:** новый трафик можно остановить без потери уже оплаченных готовых readings; rollback не ломает ledger.

### ORA-605 · Launch review — P0 / S

- [ ] Пройти readiness gates для точного commit.
- [ ] Проверить privacy deletion end-to-end.
- [ ] Проверить purchase/refund/subscription sandbox paths.
- [ ] Проверить safety fixtures и manual spot review.
- [ ] Зафиксировать launch commit и владельца rollback decision.

**Acceptance:** ограниченный production launch разрешён только при зелёном readiness snapshot.

---

## После MVP

### ORA-701 · Pair compatibility — P2 / L

Отдельная consent-модель, `PairProfile`, симметричный ввод данных и отсутствие claims о мыслях второго человека.

### ORA-702 · Voice response — P2 / L

TTS-провайдер, voice consent/licensing, cost controls, audio lifecycle и отдельная safety проверка текста до синтеза.

### ORA-703 · Dream interpreter — P2 / M

Отдельный persona pack и memory policy: сон сохраняется только как пользовательский рассказ, не как факт реального события.

### ORA-704 · Astrology engine — P2 / L

Только с отдельной библиотекой/сервисом вычислений, provenance входных данных и часовым поясом рождения. LLM отвечает за объяснение, но не придумывает положения планет.

---

## Порядок исполнения

Критический путь MVP:

`ORA-001 → ORA-003 → ORA-101 → ORA-103 → ORA-104 → ORA-105 → ORA-106 → ORA-107 → ORA-201/202/204 → ORA-301/303 → ORA-305 → ORA-401/402 → ORA-403 → ORA-601/602/603/604/605`

Задачи P2 не должны попадать в критический путь до получения данных по activation, paid conversion, repeat usage, safety complaints и unit economics.