# CJM v2 · фактический продукт

Статус: source of truth для фактического Telegram-CJM Numa на `main` после Tasks 01–07.

Этот документ описывает эффективное поведение после регистрации роутеров и runtime-installers,
а не только базовые фабрики клавиатур. Если старый Miro-фрейм, JPEG, README или предыдущий PR
расходится с зарегистрированным flow, источником истины считается код + regression tests.

## 1. Основной вход

### Новый пользователь: `/start`

Первый экран не заставляет сначала выбирать одну из четырёх «персон». Он сразу даёт полезные
варианты:

- `✨ Рассказать Numa` — пользователь описывает ситуацию, а Numa выбирает подходящий формат;
- `🔮 Таро`;
- `💞 Любовный оракул`;
- `🪐 Астрология`;
- `☀️ Сегодня для меня`;
- `📚 Мои истории`;
- `⋯ Ещё` — память, покупки, privacy.

Общее согласие не блокирует просмотр меню. Оно запрашивается just-in-time перед первым
персональным действием, где нужен пользовательский текст.

### Вернувшийся пользователь

`/start` и `← В меню` возвращают в тот же основной hub. Повторный onboarding не нужен.
Сохранённые entitlement, истории, настройки daily, birth profile и memory state продолжают
жить независимо от нового входа в меню.

### Прямые входы

`/love`, `/tarot`, `/psy`, `/astro` и поддерживаемые фиксированные `?start=` deep links ведут
в обещанный сценарий. Deep links не содержат пользовательский вопрос, полный результат,
birth data или другие приватные данные.

## 2. Персональный разбор

Tarot, Love и Mystical Psychologist используют общий structured-reading flow. Astrology имеет
отдельный calculated flow, но после расчёта использует тот же коммерческий принцип: полезный
первый слой → full result при наличии entitlement → post-result actions.

Обычный путь:

1. Выбрать практику или `Рассказать Numa`.
2. При необходимости принять just-in-time consent.
3. Выбрать тему или свой вопрос.
4. Написать один вопрос/ситуацию.
5. Numa создаёт reading; для Tarot символы и layout фиксируются до интерпретации.
6. Пользователь получает разрешённый бесплатный слой.
7. Feedback доступен на результате; негативный feedback не тупик — после причины предлагается
   перейти в новый Tarot, Psy или Astro сценарий.
8. Если нужна глубина, пользователь открывает текущий reading или выбирает продукт оплаты.
9. После подтверждённого unlock открывается именно сохранённый результат, а не новый draw.
10. Полный результат остаётся доступным из `Моих историй`.
11. После полного результата действует 24-часовой сеанс с максимум 3 уточняющими вопросами.

### Бесплатный preview и эксперимент

Для Tarot/Love/Psy действует `free_preview_v1` со стабильным назначением пользователя в одну
из двух веток:

- `baseline` — старый короткий первый ответ;
- `complete` — более законченный бесплатный ответ: конкретное наблюдение + один образ, если он
  есть, + небольшой практический шаг.

Назначение 50/50 стабильно по внутреннему UUID пользователя и не зависит от source. Entry
source нужно анализировать отдельно. Astrology в `free_preview_v1` **не участвует**: у неё
другой calculation engine, renderer и отдельный продуктовый контракт.

One-time preview entitlement и experiment arm — разные вещи. Если бесплатный первый reading
уже использован, следующий reading может показать micro-preview независимо от того, к какой
ветке `free_preview_v1` относится пользователь.

## 3. Практики

### 🔮 Tarot

Тематический spread фиксируется до LLM-интерпретации. Retry того же reading не перетягивает
новые карты. Reveal показывает те же карты и ориентации, которые объясняет итоговый ответ.

### 💞 Love Oracle

Работает с наблюдаемой динамикой отношений: инициативой, дистанцией, повторяющимися паттернами
и возможными траекториями. Numa не заявляет достоверное чтение мыслей или чувств другого
человека.

### 🌙 Mystical Psychologist

Рефлексивный сценарий через паттерны, метафоры и проверяемый следующий шаг. Он не выдаётся за
медицинскую/психологическую диагностику или профессиональную high-stakes услугу.

### 🪐 Astrology

Personal Astrology использует расчётный natal/transit engine. LLM интерпретирует рассчитанную
структуру и не выдумывает положение небесных тел.

Если consent/profile отсутствует, пользователь проходит intake:

1. дата рождения;
2. место рождения;
3. время рождения или `Не знаю время`;
4. при неоднозначном локальном времени — выбор UTC offset;
5. сохранение профиля.

Если profile уже сохранён, повторный questionnaire не показывается. После удаления profile он
не восстанавливается из прошлых readings автоматически.

## 4. Daily Horoscope

Daily — бесплатный retention surface и отдельный вход в personal Astrology.

### Первый вход

Если solar sign ещё не сохранён, Numa сначала спрашивает только знак. Дата, место и время
рождения для общего daily не нужны. `Все знаки` остаётся явной альтернативой и не стирает
сохранённый знак.

### Обычный daily screen

Для сохранённого знака показывается компактный text-only forecast. Manual view и scheduled
worker используют один и тот же daily content contract: для одного знака и даты прогноз не
должен расходиться только из-за способа доставки.

Основные действия под прогнозом:

1. `✨ Что сегодня важно именно для меня?`;
2. `📤 Поделиться темой дня`;
3. вторичный `Ещё` и возврат в меню.

В `Ещё` находятся выбор знака, `Все знаки`, дополнительный Tarot-вопрос и daily settings.

### Personal day

`daily:personal` сохраняет intent `DAY_FORECAST_INTENT`. Дальше:

- при сохранённом birth profile пользователь сразу продолжает personal Astrology;
- без profile проходит consent/profile intake и затем возвращается в исходный personal-day
  intent;
- после входа предлагаются быстрые фокусы `Отношения`, `Работа`, `Деньги`, `Общее` и `Свой
  вопрос`.

### Доставка и настройки

Настройки показывают сохранённый sign, enabled/disabled state, `08:00` по локальному времени,
разницу с Москвой и evening-feedback state. Daily можно отключить и снова включить; ручной
просмотр остаётся доступным независимо от рассылки.

## 5. Share

### Daily share

Share общего daily не отправляет наружу sign-specific текст, вопрос, profile или историю.
Публичная карточка содержит только общую дату/тему дня и бренд Numa.

Flow двухшаговый:

1. Numa показывает **точный текст**, который будет передан Telegram share picker;
2. пользователь нажимает `✅ Подтвердить текст`;
3. только после подтверждения появляется `📤 Выбрать чат`.

`SHARE_INTENT` считается после подтверждения, а не после простого открытия preview. Deep link
получателя агрегированный, без sender/recipient/readings IDs. Получатель daily-card получает
прямой CTA в `Гороскоп на сегодня`, а не обязан искать его из главного меню.

### Share персонального insight

Существующий paid-reading share сохраняет отдельный privacy-safe explicit-confirm flow.
Оригинальный вопрос и полный private reading не должны становиться публичным payload.

## 6. Мои истории и возврат к ситуации

`📚 Мои истории` — основной возвратный surface вместо старого разрозненного списка
`Мои разборы`.

Hub показывает последние readings по реальной хронологии и пользовательские folders/stories.
Активные 24-часовые sessions помечаются как активные, пока есть оставшиеся включённые вопросы.
Готовый Tarot/Love/Psy/Astro reading можно явно добавить в существующую story.

`Продолжить историю` использует самый поздний reading по `created_at`, а не порядок добавления
в folder:

- **активный сеанс + remaining questions > 0** → следующий вопрос расходует включённый
  follow-up без дополнительного списания;
- **сеанс закончился / вопросы исчерпаны** → Numa явно предупреждает, что создаётся новый
  самостоятельный reading;
- новый reading не получает автоматически тексты старой story; сохранённая memory участвует
  только если пользователь ранее включил её;
- для Astro continuation без текущего birth profile Numa просит восстановить profile перед
  новым calculated reading.

Checkout/payment resume сохраняет target story, поэтому reading после оплаты можно вернуть в
ту же пользовательскую историю.

## 7. Память: off/on

Memory выключена по умолчанию и не нужна для обычного персонального ответа.

- `off`: новая сессия не получает скрытый контекст старых вопросов; story остаётся
  навигационной сущностью, а не неявным prompt-memory;
- `on`: разрешённые memory items могут помогать следующим readings;
- memory consent предлагается после появления пользовательской ценности, а не на первом
  экране;
- пользователь может просматривать, изменять, удалять memory items и выключить memory;
- отключение/отзыв согласия не должно тихо включать память обратно.

## 8. Group CJM

Runtime-installers меняют эффективный групповой UX, поэтому базовые legacy handlers сами по
себе не описывают первый экран.

### Основной вход группы

После добавления Numa или открытия primary group menu показываются только две основные игры:

- `💞 Совместимость`;
- `⚔️ Астро-дуэль`.

Legacy group commands могут оставаться зарегистрированными ради совместимости, но они не
конкурируют с двумя core games в первом решении пользователя.

### Совместимость

Пользователи выбирают ракурс (отношения/дружба/работа/поездка). Выбранный контекст переживает
весь flow.

- если natal charts доступны, можно считать точный вариант;
- если profile отсутствует, игра не уходит в intermediate upsell: каждый участник сам
  подтверждает свой solar sign кнопкой;
- quick result явно называется быстрым режимом по солнечным знакам;
- CTA `сделать точнее` ведёт участника в personal Astrology;
- context-specific retry не сбрасывает выбранный ракурс.

### Astro Duel

Если natal profile отсутствует, участники также начинают с self-confirmed sign intake. После
результата private CTA продолжает Astro-контекст, а не случайный Tarot-flow.

### Privacy boundary группы

Numa не читает обычную переписку группы и не требует admin rights для core games. Group →
private attribution использует безопасные scenario/source codes, а не текст чата или private
user content.

## 9. Покупка, возврат после оплаты и доступ

Покупка доступна из paywall и раздела покупок. Конкретные provider routes и SKU зависят от
billing configuration; UI не должен обещать маршрут, которого нет в runtime.

Неизменяемые финансовые invariants:

- ledger/idempotency;
- exactly-once unlock;
- authoritative provider confirmation;
- reconciliation;
- корректный refund path;
- payment resume возвращает к конкретному reading/story, ради которого пользователь начал
  checkout.

Тестовые цены нельзя менять только ради CJM validation.

## 10. Effective source/state matrix

При проверке CJM нельзя тестировать только один happy path.

| Координата | Фактические варианты | Что должно сохраняться |
| --- | --- | --- |
| Пользователь | новый / вернувшийся | returning не проходит onboarding заново |
| Entry source | обычный / group / daily / share | обещанный scenario и privacy-safe source attribution |
| Practice | auto / Tarot / Love / Psy / Astro | выбранный или определённый формат не меняется случайно |
| Memory | off / on | off не подмешивает прошлый private text; on использует только разрешённую память |
| Birth profile | отсутствует / есть / удалён | Astro intake только когда он реально нужен |
| Free preview | `baseline` / `complete` | один и тот же user получает стабильный arm; source анализируется отдельно |
| Preview entitlement | первый preview / уже использован | эксперимент не отменяет one-time entitlement |
| Session | active / expired or exhausted | active даёт included follow-up; expired запускает новый reading явно |
| Story | нет / есть target story | add/continue/payment resume не теряют выбранную story |
| Daily | sign отсутствует / сохранён / all-sign | first daily не требует natal profile |
| Share | preview / confirmed / recipient entry | picker только после подтверждения exact public text |

## 11. Router/installer contract

При изменении CJM разработчик обязан смотреть не только `keyboards.py`, но и фактическую
композицию роутеров.

Критичные примеры:

- `daily_entry_router` перехватывает `menu:daily` раньше legacy core daily-handler;
- personal-day topics имеют отдельный router и продолжают тот же Astro generation path;
- reading-feedback router включает share/story continuation surfaces;
- group installers заменяют primary party menu и compatibility rendering после регистрации
  legacy mechanics;
- parent chat-scope redirect должен срабатывать до private-only child routers.

Regression test на кнопку должен проверять не только label/callback length, но и то, что
callback действительно зарегистрирован в эффективном runtime flow.

## 12. Визуальный контракт

Illustration — смысловая пунктуация, а не chrome для каждого сообщения.

Текущий `MEDIA_SCENES`:

- `O-01` onboarding start;
- `T-01` Tarot entry;
- `L-01` Love entry;
- `P-01` Psy entry;
- `A-01` Astro birth-data consent;
- `A-11` birth profile saved;
- `G-04` generating;
- `G-11` generation already in progress;
- `G-05` preview;
- `G-06` preview already used;
- `G-09` full reading;
- `F-03` follow-up result;
- `E-01` first-time daily zodiac picker.

`E-02 Daily Horoscope` существует как scene ID, но сам forecast намеренно text-only: manual
и scheduled delivery должны выглядеть как один продукт.

Tarot card art — отдельный слой и обязан соответствовать frozen symbol contract конкретного
reading.

## 13. Safety, privacy и неизменяемые границы

- никакой проверки 18+;
- mystical framing не выдаётся за достоверное предсказание или профессиональную услугу;
- crisis/violence/high-stakes handoff — plain text без мистической декоративности;
- Tarot symbols фиксируются до interpretation;
- Astrology опирается на calculated engine;
- birth data имеет отдельное согласие;
- privacy/deletion доступны из utility navigation;
- group mechanics не заявляют фактические мысли/чувства людей и не читают обычный chat;
- private question/full answer/birth profile не входят в product analytics payload;
- analytics использует структурированные funnel/source/variant/payment/feedback metadata.

## 14. Что ещё не является фактом продукта

Task 08 содержит эмпирическую часть issue #191: 10–15 реальных first-use sessions и mobile
visual QA на настоящем Telegram client. Пока такие наблюдения не проведены и не записаны по
privacy-safe template, их нельзя отмечать как completed или заменять CI/synthetic tests.

Следующий update этого документа после live validation должен ссылаться на воспроизводимые
issues/PR для найденных дефектов, а продуктовые гипотезы должны оставаться помечены как
гипотезы, а не как наблюдаемый факт.
