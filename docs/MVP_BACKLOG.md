# MVP backlog — персональный AI-оракул

Backlog рассчитан на четыре MVP-направления: таролог, любовный оракул, мистический психолог и персональный гороскоп.

Обозначения:

- **P0** — блокирует MVP;
- **P1** — нужно для ограниченного коммерческого запуска;
- **P2** — рост после подтверждения спроса;
- **S/M/L** — относительный размер.

---

## Milestone 0 — перенести и зафиксировать рабочую базу

### ORA-001 · Extract HeartSignal baseline — P0 / L

- [ ] Извлечь `fabric_bot/ideas/ai-relationship-platform` с историей.
- [ ] Импортировать в `migration/heartsignal-baseline`.
- [ ] Поднять PostgreSQL и приложение через Docker Compose.
- [ ] Запустить исходный test suite.
- [ ] Подключить CI в `Bot_globa`.
- [ ] Не менять поведение приложения в этом PR.

**Acceptance:** код собирается, миграции применяются на чистую БД, исходные тесты зелёные.

### ORA-002 · Repository and package identity — P0 / S

- [x] Обновить project metadata, README, env example и image names.
- [x] Удалить старые deployment identifiers и проверить секреты.
- [x] Не переписывать исторические migration IDs.

Каталог `heartsignal/` переименован в `bot_globa/`, базы данных — в `bot_globa` и
`bot_globa_test`, CI-джоба — в `Bot Globa CI`. Не тронуты: ID миграций и три
криптографических идентификатора (HKDF-соли и HMAC-префикс чека) — они входят в
вывод ключей, а не в брендинг.

**Acceptance:** проект запускается из `Bot_globa`, а финансовая история миграций сохранена.

### ORA-003 · Freeze platform invariants — P0 / M

- [ ] Characterization tests для credits, purchases, subscriptions и refunds.
- [ ] Exactly-once tests для entitlement и webhook replay.
- [ ] Encryption round-trip и privacy deletion tests.

**Acceptance:** тесты ловят двойное списание, повторную выдачу entitlement и утечку plaintext.

---

## Milestone 1 — Tarot vertical slice

### ORA-101 · Reading domain — P0 / L

- [ ] Новые Alembic migrations.
- [ ] `Persona`, `Reading`, `ReadingPrivateContent`, `ReadingSymbol`.
- [ ] Состояния draft/generating/preview_ready/full_ready/failed/deleted.
- [ ] Шифрование вопроса, контекста и полного результата.

### ORA-102 · Persona registry — P0 / M

- [ ] Versioned persona definitions.
- [ ] `tarot_reader_v1`.
- [ ] Разделить global policy, persona style и runtime request.
- [ ] Сохранять prompt/schema versions.

### ORA-103 · Deterministic Symbolic Engine — P0 / M

- [ ] Versioned catalog карт.
- [ ] Seed от `reading_id`.
- [ ] Positions и upright/reversed.
- [ ] Один расклад при LLM retry и worker replay.

### ORA-104 · Structured ReadingResult — P0 / L

- [ ] Строгая Pydantic schema.
- [ ] Validation и один controlled repair retry.
- [ ] Проверка symbol IDs.
- [ ] Golden fixtures.

### ORA-105 · Telegram intake — P0 / L

- [ ] Новый onboarding с явным согласием на обработку данных.
- [ ] Выбор persona/topic.
- [ ] Ввод вопроса и контекста.
- [ ] Idempotency Telegram callbacks.

### ORA-106 · Preview/full renderer — P0 / M

- [ ] Законченный бесплатный preview.
- [ ] Полный Telegram report.
- [ ] Pagination и replay без нового LLM.

### ORA-107 · Free entitlement and paid unlock — P0 / L

- [ ] One-time free preview.
- [ ] `reading_single`.
- [ ] Exactly-once unlock/spend.
- [ ] Race handling callback/webhook/worker.

**Milestone acceptance:** новый пользователь получает preview, оплачивает full reading и может открыть его повторно без нового списания.

---

## Milestone 2 — безопасность

### ORA-201 · Input risk classifier — P0 / L

- [ ] Self-harm, violence/stalking, medical, legal, financial/gambling и certainty requests.
- [ ] `allow`, `allow_with_limits`, `handoff`, `block`.
- [ ] Заблокированный запрос не попадает в persona prompt.

### ORA-202 · Output safety validator — P0 / L

- [ ] Гарантии будущего и точные даты как факты.
- [ ] Мысли третьих лиц.
- [ ] Болезнь, смерть, беременность, измена, преступление и проклятие.
- [ ] Fear upsell и dependency patterns.

### ORA-203 · Crisis handoffs — P0 / M

- [ ] Neutral templates.
- [ ] Прекращение мистической части.
- [ ] Локализуемые ресурсы помощи.

### ORA-204 · Safety regression suite — P0 / M

- [ ] Benign, ambiguous и adversarial fixtures для всех четырёх направлений.
- [ ] Prompt injection и malicious memory.
- [ ] Share sanitization.
- [ ] Интеграция в staging quality gate.

---

## Milestone 3 — память и continuity

### ORA-301 · Memory model and consent — P0 / L

- [ ] `MemoryItem`, provenance, confidence и deletion state.
- [ ] Explicit consent.
- [ ] Только разрешённые типы фактов.
- [ ] Шифрование значений.

### ORA-302 · Memory extraction — P0 / L

- [ ] Извлечение только из пользовательского ввода и подтверждений.
- [ ] Deduplication и source IDs.
- [ ] Fixed prompt context limit.

### ORA-303 · User controls — P0 / M

- [ ] «Что я помню».
- [ ] Удаление одного элемента.
- [ ] Полная очистка и отключение памяти.

### ORA-304 · Contextual continuity — P1 / M

- [ ] Source-aware формулировки.
- [ ] Показ использования прошлого контекста.
- [ ] Opt-out для конкретного reading.

### ORA-305 · Paid contextual follow-up — P0 / M

- [x] Один follow-up в полном reading.
- [x] Exactly-once consumption.
- [x] Без нового расклада и повторного списания.

Реализовано на `Reading` для всех четырёх персон: `app/services/reading_followup.py`,
таблица `reading_followups`. Аналогичный механизм на `Analysis` остаётся до удаления
legacy-вертикали.

---

## Milestone 4 — четыре направления

### ORA-401 · Love Oracle persona — P0 / M

- [ ] Prompt/style pack.
- [ ] Темы: дистанция, границы, коммуникация и следующий шаг.
- [ ] Запрет claims о точных мыслях/чувствах другого человека.
- [ ] Golden и adversarial tests.

### ORA-402 · Mystical Psychologist persona — P0 / M

- [ ] Prompt/style pack.
- [ ] Архетипы, наблюдения и рефлексивные вопросы.
- [ ] Никаких диагнозов и claims о лицензированной терапии.
- [ ] Golden и adversarial tests.

### ORA-403 · BirthProfile and Astrology Calculation Engine — P0 / L

- [ ] `BirthProfile` с зашифрованными исходными данными.
- [ ] Нормализация места и часового пояса рождения.
- [ ] Подключение расчётной библиотеки или сервиса.
- [ ] Версионированный `NatalChartResult` с provenance.
- [ ] Planetary positions, aspects и houses только при достаточном качестве времени.
- [ ] Воспроизводимые fixtures для известных входов.

**Acceptance:** одинаковые нормализованные входы дают одинаковую карту; неизвестное время не создаёт асцендент и дома.

### ORA-404 · Horoscope persona and renderer — P0 / L

- [ ] Horoscope prompt/style pack.
- [ ] Натальный профиль и недельный/месячный прогноз.
- [ ] LLM получает только рассчитанные chart facts.
- [ ] Validator запрещает менять положения планет.
- [ ] Ограничения входных данных отображаются пользователю.
- [ ] Golden и adversarial tests.

**Acceptance:** текст ссылается только на расчётный payload и не выдаёт прогноз за гарантированное событие.

### ORA-405 · Product catalog migration — P0 / M

- [ ] `reading_single`, packs, subscription и astrology SKUs.
- [ ] Новые checkout/receipt labels.
- [ ] Provider reconciliation и refund paths.
- [ ] Stripe/YooKassa sandbox acceptance.

### ORA-406 · Subscription and daily messages — P1 / L

- [ ] Exactly-once subscription credits.
- [ ] Opt-in и quiet hours.
- [ ] Отдельное отключение daily messages.
- [ ] Никаких тревожных push-текстов.

---

## Milestone 5 — вирусность

### ORA-501 · Safe share payload — P1 / M

- [ ] Headline/short text в structured result.
- [ ] Отдельная safety/sensitivity validation.
- [ ] Без вопроса, контекста, памяти, имён и birth data по умолчанию.
- [ ] Preview и явное подтверждение.

### ORA-502 · Telegram sharing and attribution — P1 / M

- [ ] Deep link/referral token без открытого user ID.
- [ ] Attribution start/activation/purchase.
- [ ] TTL и abuse limits.

### ORA-503 · Image card renderer — P2 / L

- [ ] Versioned templates.
- [ ] Storage lifecycle и deletion hooks.
- [ ] Alt text/accessibility.

---

## Milestone 6 — аналитика и запуск

### ORA-601 · Product event taxonomy — P0 / M

- [ ] Funnel, persona, astrology intake, purchase, memory, follow-up, share и safety events.
- [ ] Не логировать вопросы, readings и birth data.
- [ ] Event deduplication.

### ORA-602 · Cost and quality observability — P0 / M

- [ ] LLM cost/latency по model/persona/prompt version.
- [ ] Astrology calculation latency/errors/version.
- [ ] Validation, repair, safety fallback и billing health.

### ORA-603 · Oracle staging quality gate — P0 / L

- [ ] Fixed dataset по четырём направлениям.
- [ ] Structural, calculation, safety и style assertions.
- [ ] Проверка deployed prompt/schema/model/engine versions.

### ORA-604 · Limited-release controls — P0 / M

- [ ] Feature flags и rollout.
- [ ] Kill switch по persona/engine.
- [ ] Spend caps, rate limits и rollback runbook.

### ORA-605 · Launch review — P0 / S

- [ ] Privacy deletion end-to-end, включая BirthProfile.
- [ ] Purchase/refund/subscription sandbox paths.
- [ ] Safety и astrology fixtures.
- [ ] Readiness snapshot для точного commit.

---

## Milestone 7 — интерфейс, который ощущается

Продуктовое содержание экранов зафиксировано в `bot_globa/docs/cjm-v2.md`; этот milestone
про то, как оно подаётся. Правила поведения интерфейса — `bot_globa/docs/telegram-ux-contract.md`,
он авторитет для всех тикетов ниже.

Диагноз, с которого начат milestone: чат — лента, а не приложение. 152 точки отправки, ни
одной правки сообщения на месте; ни `parse_mode`, ни `send_chat_action`, ни `set_my_commands`,
ни deep-link. Один расклад оставляет за собой шесть иллюстраций, пять из которых мусор через
десять секунд.

### ORA-801 · Screen contract — P0 / L

- [x] `app/bot/screen.py`: `show_screen` правит текущий экран, `answer_scene` остаётся для артефактов.
- [x] Указатель живёт в отдельной FSM-записи (`destiny="screen"`), поэтому `state.clear()` физически не может его стереть.
- [x] Смена типа сообщения (фото ↔ текст) — удалить свой экран и отправить новый.
- [x] `message is not modified`, устаревшее сообщение и отказ правки деградируют в отправку.
- [x] Навигационные сцены переведены на `show_screen`; превью, полный разбор, гороскоп, чек и safety-хендофф остаются артефактами.

### ORA-802 · Типографика и безопасное экранирование — P0 / M

- [x] Глобальный `parse_mode=HTML` в polling- и webhook-бутстрапе.
- [x] `html.escape` на границе рендера для текста пользователя, вывода LLM и геокодера.
- [x] Ошибка разбора разметки → повторная отправка простым текстом, а не потеря сообщения.
- [x] Заголовки, дисклеймер и границы интерпретации размечены по контракту.

### ORA-803 · Telegram-хром — P0 / M

- [x] `set_my_commands` с описаниями и `MenuButton`.
- [x] Deep-link `?start=<scenario>` по белому списку сценариев.
- [x] Payload дальше кода сценария никуда не передаётся.

### ORA-804 · Живое ожидание — P0 / M

- [x] `send_chat_action("typing")` перед операциями дольше секунды.
- [ ] Статус генерации правится по реальным стадиям, не по таймеру.
- [ ] Не чаще одной правки в две секунды.

### ORA-805 · Инвариант «у каждого экрана есть выход» — P0 / S

- [ ] Тест перечисляет сцены-экраны и требует клавиатуру с выходом.
- [ ] Тест бюджета подписи для экранов с иллюстрацией.

### ORA-806 · Ритуал раскрытия карт — P1 / M

- [x] Карты, уже выбранные движком, раскрываются по одной правкой одного сообщения.
- [x] Ритуал не выдумывает символы и не меняет детерминированный расклад.
- [x] Не применяется к safety, оплате и ошибкам.

Раскрытие идёт параллельно генерации, а не перед ней: `create_preview` разделён на
`create_draft` и `generate_existing_preview`, поэтому расклад известен до вызова модели.
Ожидание заполняется вместо того, чтобы удлиняться.

### ORA-807 · Изображения карт таро — P1 / M

- [x] Спецификация ассетов: `bot_globa/docs/tarot-card-assets.md`.
- [ ] 22 изображения Старших Арканов по спецификации в `app/bot/assets/tarot/`.
- [ ] Ритуал подменяет изображение экрана на каждом шаге; `file_id` кэшируется как у сцен.
- [ ] Пустой каталог оставляет текстовый ритуал без изменений.

Не 78 карт, а 22: движок работает только со Старшими Арканами (`tarot-major-v1`).
Перевёрнутое положение отдельными файлами не рисуется — ориентацию сообщает текст.

### ORA-808 · Прогресс-бар интейка астролога — P1 / S

- [x] Шаги дата → место → время → вопрос показывают позицию в последовательности.
- [ ] Подтверждение распознанного места одной кнопкой.

### ORA-809 · Спойлер-превью пейволла — P1 / S

- [x] Закрытая часть полного разбора показывается под `<tg-spoiler>`.
- [x] Цена названа в тексте кнопки.

### ORA-810 · История как дневник — P1 / M

- [ ] В списке разборов видно, о чём был разбор, а не только дата и тема.
- [ ] Подпись расшифровывается только владельцу и не попадает в логи.

Размер поднят с S до M: `ReadingHistoryService` намеренно работает только на метаданных,
а вопрос лежит в `ReadingPrivateContent` с ограниченным сроком хранения — подпись,
построенная на вопросе, у старых записей опустеет. Долговечный вариант — заголовок
разбора из зашифрованного результата, а он требует расшифровки страницы в репозитории.

### ORA-811 · Уборка мёртвых клавиатур HeartSignal — P2 / S

- [x] Удалены 13 неиспользуемых фабрик HeartSignal вместе с их копирайтом: `exit_rows`,
      `cancel_keyboard`, `participant_keyboard`, `goal_keyboard`, `stage_keyboard`,
      `report_actions_keyboard`, `feedback_keyboard`, `deletion_keyboard`,
      `corrupted_report_keyboard`, `history_keyboard`, `billing_keyboard`,
      `paywall_keyboard`, `preview_actions_keyboard` — 224 строки.

**Milestone acceptance:** пользователь проходит расклад, не получив ни одного лишнего
сообщения; в чате остаются только его вопросы и готовые разборы; ожидание показывает, что
происходит на самом деле.

---

## После MVP

### ORA-701 · Pair compatibility — P2 / L

Отдельная consent-модель, `PairProfile` и отсутствие claims о мыслях второго человека.

### ORA-702 · Voice response — P2 / L

TTS, лицензирование голоса, cost controls и safety до синтеза.

### ORA-703 · Dream interpreter — P2 / M

Отдельный persona pack; сон хранится как пользовательский рассказ, а не реальное событие.

### ORA-704 · Advanced astrology — P2 / L

Ректификация времени, хорарная астрология, расширенные транзиты и синастрия после проверки спроса.

---

## Критический путь

`ORA-001 → ORA-003 → ORA-101/102/103/104/105/106/107 → ORA-201/202/204 → ORA-301/303/305 → ORA-401 → ORA-402 → ORA-403 → ORA-404 → ORA-405 → ORA-601/602/603/604/605`

Первый следующий шаг: `ORA-001 · Extract HeartSignal baseline`.

Milestone 7 идёт параллельно и не блокирует запуск, но его фундамент упорядочен строго:
`ORA-801 → ORA-802 → ORA-803/804/805 → ORA-806 → ORA-808/809/810`. `ORA-807` ждёт ассеты.
