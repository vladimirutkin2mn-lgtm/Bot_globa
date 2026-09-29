# Росаккредитация v5: API-запросы прямо из Chrome

Эта версия не использует Python `requests` для обращения к `pub.fsa.gov.ru`.

Схема:
1. Selenium открывает настоящий Chrome/Edge.
2. FSA создаёт обычную публичную браузерную сессию.
3. Скрипт ловит cookies и Authorization.
4. Chrome **остаётся открытым**.
5. Запросы сертификатов и деклараций выполняются через `fetch()` прямо внутри страницы FSA.
6. Поэтому используются тот же TLS, cookies, proxy/VPN и сетевой стек, с которыми сам сайт уже работает.

Это сделано из-за того, что на некоторых Windows/VPN/корпоративных сетях браузер открывает FSA нормально, а Python HTTP-клиент получает self-signed certificate или ReadTimeout.

## Windows

В папке скрапера:

```powershell
py -m pip install -r requirements_fsa.txt
py -3.12 enrich_fsa_1000_browser.py
```

Или запустите `run_fsa_windows.bat`.

Важно: **не закрывайте Chrome**, пока прогон не закончится.

## Что должно быть в терминале

После строки:

```
Шаг 2/2: запросы к FSA идут ПРЯМО ИЗ БРАУЗЕРА
```

должны пойти статусы `FOUND` / `NOT_FOUND`.

Если browser-native API не работает, v5 специально остановится **после первого ИНН**, а не напечатает 1 000 одинаковых ошибок. Пришлите вывод первого ИНН и `output_fsa_1000/summary.json`.

## Результаты

Папка `output_fsa_1000`:
- `fsa_1000.csv`
- `fsa_1000_raw.json`
- `summary.json`
- `browser_session_debug.json`

В debug-файле не сохраняются значения token/cookie.
