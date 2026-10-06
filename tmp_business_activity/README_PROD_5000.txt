PRODUCTION v1 — сбор evidence по сертификатам/декларациям для 5 000 ИНН

Что делает
- S-34 — основной источник.
- СООТВЕТСТВИЕ.РУС — только для ИНН, которые не нашёл S-34.
- List-Org в production не используется: в пилотах не дал дополнительного покрытия и включал CAPTCHA.
- Никаких обходов CAPTCHA/rate-limit.

Вход
Поддерживаются:
- .xlsx
- .csv / .tsv
- .txt

Для исходного Excel по умолчанию ожидается:
- лист: финал
- колонка: ИНН текстом
- максимум: 5000 уникальных корректных ИНН

Быстрый запуск Windows
1. Распакуйте ZIP в новую папку.
2. Положите исходный Excel в эту же папку.
3. Перетащите Excel мышкой на run_business_activity_5000.bat
   ИЛИ запустите из PowerShell:

   py -m pip install -r requirements.txt
   py -3.12 business_activity_prod.py --input "ВАШ_ФАЙЛ.xlsx" --limit 5000

Проверка без запуска браузера
   py -3.12 business_activity_prod.py --input "ВАШ_ФАЙЛ.xlsx" --limit 5000 --dry-run

Resume
Если Windows/Chrome/скрипт остановились, просто запустите ту же команду снова.
Состояние хранится в:
   output_business_activity_prod\checkpoint.sqlite3
Уже финализированные ИНН повторно не обрабатываются.

Выходные файлы
   output_business_activity_prod\business_activity_results.csv
   output_business_activity_prod\summary.json
   output_business_activity_prod\checkpoint.sqlite3
   output_business_activity_prod\cache\...

Основные поля результата
- inn
- final_status: FOUND / NOT_FOUND / ERROR / PENDING
- final_source: S34 / SOOTVETSTVIE
- evidence_class:
  - PRODUCTION_STRONG — компания сама изготовитель
  - TRADE_IMPORT_STRONG — заявитель, но изготовитель другой
  - MIXED_PRODUCTION_AND_TRADE — встречаются оба сценария
  - CERT_EVIDENCE_ROLE_UNKNOWN — документ есть, роль не удалось уверенно определить
  - NO_CERT_EVIDENCE — по каскаду документов не найдено
- s34_status / soot_status
- documents
- same_docs / other_docs
- products
- urls
- last_error

Важно
- NOT_FOUND означает только отсутствие найденного certificate/declaration evidence в выбранных источниках. Это НЕ означает, что компания не ведёт деятельность.
- ERROR отдельно от NOT_FOUND. Ошибки можно безопасно перезапустить.
- S-34 и СООТВЕТСТВИЕ.РУС — evidence-источники. Их результат потом надо объединять с FNS/OKVED/Честным знаком/лицензиями для итоговой классификации бизнеса.

Технические настройки
По умолчанию:
- браузер перезапускается каждые 100 компаний;
- до 3 попыток на источник;
- snapshot CSV/summary каждые 25 компаний;
- лимит 5000.

Примеры:
  py -3.12 business_activity_prod.py --input clients.xlsx --limit 5000
  py -3.12 business_activity_prod.py --input clients.xlsx --limit 5000 --restart-every 50
  py -3.12 business_activity_prod.py --input clients.csv --header "ИНН текстом" --limit 5000

Чтобы НЕ перепроверять ERROR из предыдущего запуска:
  py -3.12 business_activity_prod.py --input clients.xlsx --no-retry-errors

Если видите RUNNING.lock, но скрипт точно не запущен, удалите только файл:
  output_business_activity_prod\RUNNING.lock
и запустите снова.
