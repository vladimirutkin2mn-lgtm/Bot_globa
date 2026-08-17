# Asset provenance

Этот файл фиксирует происхождение визуальных ассетов, для которых происхождение подтверждено в репозитории. Он не делает предположений о старых CJM reference-файлах без source manifest.

## Tarot · `rws-78-v1`

- **Произведение:** Rider–Waite–Smith Tarot.
- **Оригинальные иллюстрации:** Pamela Colman Smith.
- **Оригинальный издатель:** Rider & Company.
- **Первая публикация:** 1909.
- **Статус оригинального artwork:** public domain.
- **Runtime variant Numa:** единый 720px JPEG-набор для всех 78 карт.
- **Operational source:** `mixvlad/TarotCards`, directory `tarot/rider-waite/720px`.
- **Воспроизводимый импорт:** `scripts/import_rws1909_tarot.py`.
- **Пофайловый manifest:** `docs/tarot-rws1909-sources.json`.

До унификации 56 Младших Арканов уже использовали этот runtime-набор, а 22 Старших были отдельными фирменными иллюстрациями Numa. После унификации все 78 карт происходят из одного набора.

Manifest хранит source filename, URL, SHA-1 и размер локального файла. `tests/test_tarot_art.py` сверяет manifest с `RWS_78_V1` и фактическими байтами в `app/bot/assets/tarot/`.

Public-domain статус относится к оригинальным иллюстрациям 1909 года. Современные recolor, реставрации, перерисовки или иные самостоятельные обработки нельзя автоматически считать свободными только из-за статуса исходного artwork.

## CJM scene illustrations

Файлы в `app/bot/assets/scenes/` исторически собирались отдельным CJM-пакетом. Для всего legacy-набора сейчас нет полного пофайлового provenance manifest, поэтому этот документ **не утверждает** их происхождение или лицензионный статус.

Активный продукт использует только media allowlist из `app/bot/scene_media.py`; остальные scene JPEG остаются design reference. Если активные scene illustrations будут перерисованы/заменены, для нового набора следует добавить отдельный provenance manifest вместо переноса неподтверждённых исторических предположений.
