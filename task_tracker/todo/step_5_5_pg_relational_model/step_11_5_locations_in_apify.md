# Шаг 11.5: прокинуть locations из JD в Apify-запрос

> Зависит от: step_10 (done)
> Статус: [x] done (2026-06-30)
> Дата: 2026-06-30
> Тип: фикс (баг качества выдачи)
>
> Решение по всплывшей развилке: **вариант A** — транзиентная колонка
> `sessions.pending_apify_params` (зеркало `pending_boolean`). Миграция 004
> добавила обе колонки.
>
> Коммиты: bd51c18 (11.5a), d143ae7 (11.5b), 53939a0 (11.5c), 0f75874 (11.5d).
> Тесты: 133 зелёных (было 117 + 16 новых). Миграция 004 применена на боевой PG.

## Цель

JD "Senior Python Engineer, **Germany**, FastAPI" сейчас даёт кандидатов из
всех стран — геолокация теряется между LLM и Apify. LLM **уже** выдаёт секцию
`## Apify params` с `locations:`, но `bot/pipelines.py` её выбрасывает и зовёт
`discover_candidates(boolean=...)` без `locations`. Нужно распарсить params,
сохранить в БД, протащить в `discover_candidates(locations=...)` и показать
юзеру.

## Видение результата

JD с "Germany" → бот парсит `locations: Germany`, сохраняет
`apify_params = {"locations": ["Germany"], "experience": ["6-10","10+"]}` JSONB
в `searches`, показывает юзеру строку «📍 Локации: Germany» перед confirm, и
Apify-запрос уходит с фильтром по Германии. Кандидаты из других стран в выдачу
не попадают.

## Out-of-scope (НЕ делаем в этом шаге)

- **experience в Apify не прокидываем** — только сохраняем в JSONB на будущее.
  `discover_candidates` пробрасывает лишь `locations` и `pages`; расширять его
  сигнатуру + переносить `EXPERIENCE_MAP` маппинг — отдельный шаг.
- **exclude_titles / titles / seniority** — не парсим, не прокидываем.
- **Редактирование params юзером** (новый шаг state-машины
  `WAITING_PARAMS_CONFIRM`) — нет. v1 = только показать.
- **Бэкфилл старых searches** — нет. Старые строки: `apify_params = NULL` →
  трактуем как `locations=None` (текущее поведение).

## Зафиксированные решения (с Ренатом, 2026-06-30)

1. **Парсим locations + experience, сохраняем оба в JSONB. В Apify прокидываем
   ТОЛЬКО locations.** experience лежит в БД для будущего шага.
2. **Хранение — в `searches`**, новая колонка `apify_params JSONB`. Миграция
   **004** (не 005 — step_11 ушёл в backlog вместе со своей миграцией 004,
   003 — последняя применённая). `db/schema.sql` обновить (snapshot-конвенция).
   `_COLUMNS` guard не трогаем — `searches` пишется явным INSERT, не через
   `**fields`.
3. **Показываем локации юзеру** в `replies.BOOLEAN_GENERATED` отдельной строкой.
4. **JSONB — очищенные списки** (после валидации experience по разрешённому
   множеству `<1,1-2,3-5,6-10,10+`), не сырые строки.
5. **Краевые случаи консервативно:** нет секции / пустой locations / region-
   группировка (DACH, EU) / мусор → пустой список → `locations=None` = текущее
   поведение. Парсинг params НИКОГДА не валит генерацию boolean.

## Подэтапы (= 4 коммита)

### 11.5a — `extract_apify_params()` в generator.py + тест

`core/boolean_generator/generator.py`: рядом с `extract_boolean()` (строка 70)
добавить:

```python
def extract_apify_params(llm_output: str) -> dict:
    """Parse the '## Apify params' block into cleaned lists.

    Returns {"locations": [...], "experience": [...]}. Missing/empty/garbage
    → empty lists (caller treats as None). Never raises.
    """
```

- Регэксп на блок `## Apify params` (тот же приём что `extract_boolean`).
- Внутри блока парсить строки `- locations: a, b, c` и `- experience: x, y`.
- `locations`: split по запятой, strip, отбросить пустые. БЕЗ валидации по
  словарю стран (Apify сам отфильтрует нераспознанное — решение #5).
- `experience`: split по запятой, strip, **оставить только значения из**
  `{"<1","1-2","3-5","6-10","10+"}` (мусор типа "5+", "senior" отбросить).
- Нет блока / пустые → `{"locations": [], "experience": []}`.

**Тесты** (новый `tests/test_extract_apify_params.py` или в существующий тест
generator, если есть): реальный пример из prompts_candidates.py:66-68
(`Germany, Luxembourg, Netherlands` / `6-10, 10+`), отсутствие блока, пустой
locations, мусорный experience (`5+, senior` → `[]`), region-группировка
(`DACH` остаётся в locations — Apify отфильтрует, не наша забота).

Коммит: `feat: step 5.5.11.5a — extract_apify_params() parser`

### 11.5b — миграция 004 + schema.sql + create_search/get_search

- `db/migrations/004_searches_apify_params.sql`:
  ```sql
  ALTER TABLE searches ADD COLUMN apify_params JSONB;
  ```
  + шапка-комментарий в стиле 003 (зачем колонка, почему JSONB, почему в
  searches а не sessions).
- `db/schema.sql`: добавить `apify_params JSONB` в `CREATE TABLE searches`
  (после `original_boolean`), + комментарий.
- `db/client.py:create_search()` (строка 412): добавить параметр
  `apify_params: dict | None = None`, прокинуть в INSERT как `$5`. asyncpg +
  JSONB: передавать `json.dumps(apify_params)` (asyncpg по умолчанию НЕ
  сериализует dict в jsonb — проверить как делается для raw_profile_json в
  upsert_candidate; применить тот же приём).
- `db/client.py:get_search()` — уже `SELECT *`, вернёт колонку. Если JSONB
  читается строкой (как raw_profile_json по заметке step_11) — caller сделает
  `json.loads`. Проверить фактическое поведение тестом.

**Тесты** (в `tests/` рядом с CRUD-тестами searches): `create_search` с
`apify_params={"locations":["Germany"]}` → `get_search` → значение читается
обратно как dict (или строка, которую json.loads парсит — зафиксировать в
тесте фактическое поведение). `create_search` без apify_params → NULL/None.

Коммит: `feat: step 5.5.11.5b — searches.apify_params JSONB (migration 004)`

### 11.5c — протащить params через generate_boolean → handlers → searches

- `bot/pipelines.py:generate_boolean()` (строка 47): сменить возврат с `str`
  на `tuple[str, dict]` — `(extract_boolean(md), extract_apify_params(md))`.
  CV-stub возвращает `(stub_boolean, {"locations": [], "experience": []})`.
  Обновить докстринг и сигнатуру `-> tuple[str, dict]`.
- `bot/handlers.py:_generate_boolean_and_advance()` (строка 245): распаковать
  `boolean, apify_params = await pipelines.generate_boolean(...)`. Положить
  `apify_params` — но **в pending пока нет колонки**. Решение: хранить params
  в `sessions` не будем (лишняя миграция). Вместо этого: params нужны только
  на confirm → перегенерировать дёшево нельзя (это LLM-вызов). Поэтому
  **протащить через pending**: сериализовать params в `pending_boolean`? Нет —
  грязно. **Финальное решение: добавить params в JSONB прямо в момент confirm
  невозможно (markdown уже потерян).** → Хранить распарсенные params в памяти
  сессии нельзя (бот может рестартнуть).
  **Принятое решение (один путь):** класть `apify_params` в `sessions` через
  новую транзиентную колонку НЕ будем. Вместо этого на этапе
  `_generate_boolean_and_advance` сохранять params СРАЗУ, но `searches` строки
  ещё нет (она создаётся на confirm). → Значит params надо донести до confirm.
  Канал доставки = `sessions`. Добавляем в миграцию 004 ВТОРУЮ колонку
  `sessions.pending_apify_params JSONB` (транзиентная, как pending_boolean,
  чистится на confirm). На confirm переносим из `sessions.pending_apify_params`
  в `searches.apify_params`.

  > **ВАЖНО — развилка для обсуждения перед 11.5c (см. раздел ниже).** Этот
  > подэтап вскрыл, что для доставки params от generate до confirm нужна
  > транзиентная колонка в `sessions` (как `pending_boolean`). Это меняет
  > миграцию 004: добавляется `sessions.pending_apify_params JSONB`. Решить
  > ДО кода 11.5b (миграция пишется там).

- Показ юзеру: `replies.BOOLEAN_GENERATED` — добавить строку локаций.
  `_generate_boolean_and_advance` формирует `locations_line` из
  `apify_params["locations"]` (пусто → не показывать строку или показать
  «не заданы»). Обновить `.format(boolean=..., locations=...)`.
- На confirm (`handlers.py:289` WAITING_BOOLEAN_CONFIRM): читать
  `session["pending_apify_params"]`, передать в `create_search(...,
  apify_params=...)`, очистить `pending_apify_params=None` рядом с
  `pending_boolean=None`.

**Тесты** (`tests/test_handlers.py`): моки `generate_boolean` на строках
183-185, 210-212, 243-245 СЛОМАЮТСЯ (сейчас возвращают str) — обновить на
кортеж `(boolean, {"locations":[...], "experience":[...]})`. Добавить
проверку: после confirm `search["apify_params"]["locations"] == [...]`.

Коммит: `feat: step 5.5.11.5c — thread apify_params to searches + show to user`

### 11.5d — прочитать locations в pipeline и передать в discover

- `bot/pipelines.py:_run_vacancy_pipeline()` (строка 161): после
  `search = await db.get_search(search_id)` достать
  `apify_params = search["apify_params"]` (json.loads если строка),
  `locations = (apify_params or {}).get("locations") or None`. Пустой список
  → `None`.
- Строка 185: `discover_candidates(boolean=boolean, locations=locations)`.
  Учесть resume-ветку (строки 172-182): там Apify не зовётся, locations не
  нужны — править только else-ветку (строка 183+).
- Обновить устаревший докстринг `discover.py:29-31` («the bot does not parse
  locations out of the boolean — it passes None») — теперь парсит.

**Тесты** (`tests/test_pipelines_new_model.py`): мок `discover_candidates`
должен получить `locations=["Germany"]` когда search.apify_params содержит их;
`locations=None` когда NULL/пусто. Проверить что resume-ветка не падает на
NULL apify_params (старые searches).

Коммит: `feat: step 5.5.11.5d — pass locations from search into discover`

## Развилка, всплывшая при детализации (решить ДО 11.5b)

**Канал доставки params от generate до confirm.** params парсятся в
`_generate_boolean_and_advance`, а нужны на этапе confirm (где создаётся
`searches`). Между ними бот может рестартнуть → память не годится. Варианты:

- **(A) транзиентная колонка `sessions.pending_apify_params JSONB`** — точная
  аналогия `pending_boolean` (миграция 003). Чистится на confirm. Миграция 004
  добавляет ОБЕ колонки: `searches.apify_params` + `sessions.pending_apify_params`.
  `_COLUMNS["sessions"]` guard — добавить `pending_apify_params` (sessions
  обновляется через `**fields`).
- (B) перегенерировать params на confirm — нельзя, это повторный LLM-вызов.
- (C) хранить в `searches` сразу при generate — нельзя, нарушает инвариант
  «searches = committed query» (см. шапку миграции 003).

**Рекомендация: (A).** Зафиксировать перед написанием миграции 004.

## Команды для верификации (весь шаг)

```bash
# 1. Парсер
python -m pytest tests/test_extract_apify_params.py -q

# 2. БД CRUD
python -m pytest tests/ -k "search and apify_params" -q

# 3. Handlers + pipelines (моки обновлены)
python -m pytest tests/test_handlers.py tests/test_pipelines_new_model.py -q

# 4. Весь набор зелёный (было 117)
python -m pytest -q

# 5. Миграция применяется на чистой схеме (PG-коннект, см. промпт строки 154-158)
python -c "import asyncio, asyncpg, os; from dotenv import load_dotenv; load_dotenv(); asyncio.run(asyncpg.connect(host=os.environ['PG_HOST'], port=int(os.environ['PG_PORT']), user=os.environ['PG_USER'], password=os.environ['PG_PASSWORD'], database=os.environ['PG_DATABASE']))" && echo PG_OK

# 6. Ручной e2e (опционально, перед step_12): JD с Germany → в логе
#    "Locations: ['Germany']" в search summary from_apify_search.py:134
```

## Критерии готовности

- [ ] `extract_apify_params()` парсит реальный пример, мусор → пустые списки,
      experience валидируется по множеству, не падает на отсутствии блока
- [ ] Миграция 004 применяется; `searches.apify_params` + (если решение A)
      `sessions.pending_apify_params` есть в schema.sql
- [ ] `generate_boolean` возвращает `(boolean, params)`; моки в тестах обновлены
- [ ] После confirm `search["apify_params"]["locations"]` содержит страны из JD
- [ ] `_run_vacancy_pipeline` передаёт `locations` в `discover_candidates`;
      NULL/пустой → `None` (старые searches не падают)
- [ ] Юзер видит строку с локациями в `BOOLEAN_GENERATED`
- [ ] `python -m pytest -q` — всё зелёное (≥117 + новые)
- [ ] Устаревший докстринг `discover.py:29-31` обновлён
- [ ] `[x]` в PLAN.md строка 11.5, блок в progress.md
