# Progress Log — step 5.5 (PG + relational model)

## Контекст для агента

### Состояние проекта на момент написания плана (2026-05-20)

- Бот работает end-to-end на SQLite (step_5 закрыт). 90 unit-тестов зелёные.
- Реальный прогон сделан: session 4 (Sonia ASR), 25 кандидатов из Apify, GO:6 / MAYBE:6 / SKIP:13.
- Resume-from-raw-apify уже зашит — повторный прогон не сжигает Apify-кредиты.
- В `replies.PIPELINE_DONE` уже есть total_found / go / maybe / skip breakdown.

### Где что лежит

- DB:
  - `db/client.py` — sync, sqlite3 stdlib, threading.Lock, WAL.
  - `db/schema.sql` — SQLite-диалект.
  - `db/migrations/001_initial.sql` — стартовая миграция.
- Bot:
  - `bot/main.py` — entry point, polling, создаёт `DB(...)` и кладёт в `application.bot_data["db"]`.
  - `bot/handlers.py` — sync вызовы `db.*` (большинство методов sync).
  - `bot/pipelines.py` — async `run_pipeline`, внутри db-вызовы sync (то есть бот сейчас блокирует event loop на db).
  - `bot/state_machine.py`, `bot/auth.py`, `bot/replies.py`, `bot/extractors.py` — без db-зависимостей.
- Core (НЕ трогаем в этом плане):
  - `core/boolean_generator/`, `core/candidate_screener/` — никаких db-зависимостей, работают через файлы.

### Что НЕ ломать

- `core/` пакет не трогаем — он не зависит от db, разработка ведётся изолированно.
- `cli/run_local.py` и другие CLI в `core/candidate_screener/cli/` — не зависят от bot/db. Не трогаем.
- Бот должен продолжать запускаться (`python -m bot.main`) и проходить TG e2e после каждой фазы.

### Важные ограничения

- Разработка: я (Ренат) на Windows, PG будет на Mac mini в локальной сети. Доступ
  с Windows может потребовать настройки `listen_addresses` + `pg_hba.conf` +
  возможно Tailscale/SSH-туннеля — обсуждаем в step_1.
- Данные SQLite — можно сносить (разработка, продакшена ещё нет).
- 05_refind репо не трогаем. Поверхность контакта: `05_refind/CLAUDE.md` секция
  "Связанные проекты" может потребовать обновления когда станет ясно про PG.
- Whitelist: 1-2 юзера в v1, реальной нагрузки нет. Connection pool можно делать
  минимальный (min_size=1, max_size=5).

### Решения зафиксированные перед написанием плана

- **PG-клиент:** asyncpg (native binary protocol, идиоматичный async).
- **PG-расположение:** Mac mini, новая БД рядом с существующей. Имена БД:
  `recruiter_assistant_dev` (локальная разработка) и `recruiter_assistant`
  (продакшен после step_8). В .env пишем `recruiter_assistant_dev`.
- **Тесты:** pytest-asyncio + asyncpg напрямую к PG-серверу. Без testcontainers,
  без docker-compose. Каждый тест создаёт схему в отдельной БД или schema-namespace
  и сносит её в teardown. См. step_5.
- **Миграция данных:** НЕ делаем. SQLite-БД сносим. Старт с пустого PG.
- **JSON-колонки:** PG `JSONB` для `raw_profile_json`, `screening_json`. Поля
  с относительно структурированным JSON хранятся как JSONB чтобы потом было
  можно делать `WHERE raw_profile_json->>'someField' = ?` без переноса.
- **ENUM-колонки:** для `ai_status` (pass/uncertain/fail), `vacancy.source`
  (manual/apify_job_search) используем native PG ENUM type. Если потом
  понадобится изменять список значений — отдельная мини-миграция.

## Learnings

### step_1 (2026-05-28)

- **PG уже стоял на Mac mini** (postgresql@16, PG 16.14, data dir
  `/opt/homebrew/var/postgresql@16`). Используется проектом rm_mini
  (БД `rm_mini_hub`, юзер `rm_mini`). Запускается не через `brew services`,
  а через свой launchd-агент `~/Library/LaunchAgents/com.rm_mini.postgres.plist`
  (`KeepAlive=true` + `RunAtLoad=true`).
- **Способ подключения:** Tailscale, MagicDNS hostname `rm-mini`
  (Tailscale IP `100.104.30.62`). `PG_HOST=rm-mini` в `.env` —
  не привязываемся к конкретному IP, MagicDNS резолвит.
- **listen_addresses** изменён с дефолтного `localhost` на
  `localhost,100.104.30.62` (явный Tailscale IP, не `*`).
  Параметр **требует restart**, по reload не подхватывается.
- **pg_hba.conf**: добавлена одна строка в конец —
  `host recruiter_assistant_dev recruiter_assistant 100.64.0.0/10 scram-sha-256`
  (CGNAT-диапазон Tailscale). Существующие правила не тронуты.
- **Бэкапы конфигов** на маке:
  `/opt/homebrew/var/postgresql@16/{postgresql,pg_hba}.conf.bak.20260528`
- **Гвоздь №1:** `pg_ctl restart` упал с `postmaster became multithreaded`
  без `LC_ALL`. launchd подхватил PG через 10 сек с правильным
  `LC_ALL=en_US.UTF-8` из своей plist — PG в итоге работает. Урок: если
  делать `pg_ctl start`/`restart` руками — экспортить
  `LC_ALL=en_US.UTF-8` перед командой.
- **Гвоздь №2:** в Python 3.14 системного интерпретатора `asyncpg==0.31.0`
  уже установлен. venv в проекте не используется. requirements.txt
  обновлён для фиксации.
- **Роль/БД:** `recruiter_assistant` / `recruiter_assistant_dev` (owner =
  роль), пароль 32 символа alphanumeric, лежит в `.env`.
- **Активные коннекции rm_mini пережили restart** — клиент переподключился
  автоматически.

### step_2 (2026-05-28)

- **Замены диалекта** ровно как в плане:
  - `INTEGER PRIMARY KEY AUTOINCREMENT` → `BIGSERIAL PRIMARY KEY`
  - `TEXT NOT NULL DEFAULT (datetime('now'))` → `TIMESTAMPTZ NOT NULL DEFAULT now()`
  - `INTEGER` → `BIGINT` (включая `telegram_user_id`, который **без** SERIAL —
    natural key из Telegram)
  - `REAL` → `DOUBLE PRECISION`
  - `PRAGMA foreign_keys = ON;` удалена (в PG FK всегда форсятся)
- **CHECK-constraints** оставлены текстовыми (как в SQLite), не ENUM — ENUM
  планируется в фазе 2 (step_7).
- **`raw_profile_json` / `raw_job_json`** оставлены TEXT — фаза 2 переведёт
  на JSONB.
- **`db/schema.sql`** содержит все 6 таблиц (с `_migrations`),
  **`db/migrations/001_initial.sql`** — те же 5 без `_migrations` (она
  создаётся в init через schema.sql).
- **Smoke-test:** schema применилась идемпотентно, все 6 таблиц видны через
  `pg_tables`, типы колонок подтверждены через `information_schema.columns`
  (`bigint`, `timestamp with time zone`, `double precision`).
- **Lint:** в `db/*.sql` нет AUTOINCREMENT / PRAGMA / datetime.
- **Тесты на этом шаге не запускаются** — `db/client.py` ещё sqlite-based,
  будет переписан на step_3.

### step_3 (2026-05-28)

- **Полностью переписан `db/client.py` на asyncpg.** Конструктор теперь
  принимает `asyncpg.Pool`, экземпляр строится через async фабрику
  `await DB.connect()`. Поддержан async context manager (`async with`).
- **DSN-builder**: `DATABASE_URL` имеет приоритет; иначе сборка из
  `PG_HOST/PG_PORT/PG_USER/PG_PASSWORD/PG_DATABASE`. Пароль/юзер URL-encoded
  через `urllib.parse.quote` — на случай спецсимволов.
- **Все методы async**, плейсхолдеры `?` → `$1...$N`. Сохранили публичный
  API (имена, параметры, возврат) — step_4 ждёт минимальных изменений.
- **`create_session` / `create_run`**: вместо `cur.lastrowid` (sqlite-only)
  используем `INSERT ... RETURNING id` — стандартный PG-приём.
- **`update_session` / `update_run`**: динамическая сборка SQL с
  нумерованными плейсхолдерами (`SET col = $1, ...` + WHERE `id = $(N+1)`).
- **`cleanup_stale_sessions`**: `datetime('now', '-N minutes')` SQLite →
  `now() - make_interval(mins => $1)` PG. Парсим status string
  asyncpg (`"UPDATE 3"`) для возврата rowcount.
- **`initialize_from_schema` / `apply_migrations`**: обёрнуты в
  `async with conn.transaction()`. asyncpg умеет multi-statement в
  `execute()` нативно — никакого `executescript` / split не нужно.
- **CLI** через `asyncio.run(_amain())`; `DB.connect` вызывается без аргументов,
  `async with await DB.connect() as db: ...`. `--db-path` аргумент удалён
  (теперь всё через env).
- **Smoke**: init → `_migrations` фиксирует `001_initial.sql`,
  `apply_migrations` → пусто, upsert/get юзера 123 → OK, очистка прошла.
  CLI `--init` и `--migrate` работают.
- **`bot/main.py` пока не запустится** — его вызовы `DB(path)` и sync
  методы остались старые. Это step_4.
- **Unit-тесты НЕ запускаем** — они на sqlite-API. Переключим fixture на
  step_5.
- **Не сделано (намеренно):** транзакций для bulk-insert candidates/vacancies
  пока нет — план оставил это на потом ("без транзакции в первой версии").

### step_4 (2026-05-28)

- **`bot/main.py` переписан под post_init/post_shutdown** —
  `Application.builder().post_init(_post_init).post_shutdown(_post_shutdown)`.
  PTB v21 запускает `_post_init` в event loop после старта event loop —
  единственное правильное место для async `DB.connect()`.
- **`_schema_ready` переписан под PG**: проверка через
  `information_schema.tables WHERE table_name='sessions'`. Старый код
  `db._conn.execute("SELECT ... FROM sqlite_master")` удалён.
- **`DB_PATH` больше не читается** в bot/main.py — DSN целиком из env через
  `DB.connect()`. Переменная всё ещё есть в `.env` (gitignored, legacy),
  можно удалить позже в step_13.
- **Все db.* вызовы async**: 11 awaits в handlers.py, 5 в pipelines.py.
  `_db(context)` остаётся sync — это просто accessor `bot_data["db"]`.
- **Smoke-test:** `python -m bot.main` → "recruiter_assistant bot starting" →
  "Application started" → начинаются `getUpdates` polls. БД подключилась,
  ошибок нет. Бот остановлен после проверки (был фоновый процесс, активно
  полил Telegram — не оставлять надолго).
- **Тесты пока в SQLite-формате** → падают на импорте/фикстурах. Чинится на
  step_5.

### step_5 (2026-05-28)

- **pytest.ini**: `asyncio_mode = auto` + `testpaths = tests`. Это позволяет
  писать `async def test_X(db)` без декоратора на каждый тест.
- **`tests/conftest.py`**: `db` фикстура создаёт уникальную PG-схему
  (`test_<uuid8>`), привязывает пул только к ней, применяет `schema.sql`,
  отдаёт `DB(pool)`. Teardown — `DROP SCHEMA ... CASCADE`. Полная изоляция
  без docker/testcontainers.
- **Тесты переписаны** на async/await:
  - `test_db_client.py`: 24 теста (один удалён — `test_wal_mode_enabled`,
    sqlite-only). 89 → 89 итого (со старых 90 минус WAL-тест).
  - `test_handlers.py`: 12 тестов, локальная `db` фикстура удалена
    (берётся из conftest), `asyncio.run(handlers.cmd_X)` → просто `await`.
  - `test_pipelines_resume.py`: 2 теста, аналогично.
- **Грабли №1 (важно!):** `asyncpg.create_pool(init=...)` запускает callback
  **только один раз при создании соединения**. После release asyncpg делает
  RESET сессии (включая search_path). Если использовать `init` для
  `SET search_path` — второй acquire вернёт дефолт `"$user", public` и
  insert'ы пойдут в **public**, не в тестовую схему. Это потенциально
  фатально (тесты могли бы писать в боевую БД бота, нарушая FK).
  **Правильно**: `server_settings={"search_path": schema}` —
  применяется на стартапе и переживает RESET.
- **Грабли №2 (мелкое):** `INSERT INTO _migrations ... ON CONFLICT` в
  `initialize_from_schema` теперь не падает на повторном `--init`. Тесты
  каждый раз делают fresh init — без conflict-handling сыпались бы дубли
  (но в нашей схеме per-test это маловероятно, оставили для устойчивости).
- **SQLite-артефакты удалены**: `data/recruiter_assistant.db{,.db-shm,.db-wal}`.
  `data/sessions/` сохранены (там реальные raw_apify.json от прошлых
  прогонов, нужны для resume).
- **Прогон**: 89 passed in 14s. Каждый db-тест делает CREATE/DROP SCHEMA —
  средняя стоимость теста ~150мс. Приемлемо.

### step_6 (2026-05-28)

- **E2E на PG прошёл успешно.** JD: "Senior Python Engineer, Germany,
  FastAPI, async, PostgreSQL. Remote ok." Ренат прошёл через
  `/start` → `/refind_vacancy` → JD → boolean → "ок" → отчёт.
- **Цифры session 28 / run 10:**
  - found_count: 25
  - screened_count: 25
  - passed_count: 8 (pass:2 + uncertain:6 в БД)
  - fail (skip): 17
  - cost_usd: $0.7442
  - duration_sec: 201.8 (3:22)
  - report_path: data/sessions/28/report.md
  - sessions.step = 'done', runs.status = 'done', error_text = NULL
- **Сравнение с историческим Sonia (session 4 на SQLite):**
  25 кандидатов, GO:6/MAYBE:6/SKIP:13, $0.80. Похожий профиль выдачи —
  пайплайн ведёт себя одинаково на PG и SQLite.
- **Найденный пользователем баг:** локация из JD ("Germany") НЕ
  учитывается в boolean — в выдаче кандидаты из всех стран. Записано
  в `task_tracker/backlog/step_5_backlog.md` под "Locations / experience
  / seniority" (уже существующий пункт, добавлен подтверждающий комментарий).
  Это **не блокер фазы 1** — функциональность пайплайна работает, баг
  про качество выдачи. Чинится в отдельном спринте после фазы 2.
- **Шум в БД:** users=3, sessions=28, runs=10, candidates_found=35 — следы
  от smoke-tests step_3/4 и тестовых TG-сессий. Не критично, но при
  переходе на фазу 2 разумно сделать `TRUNCATE` (без миграции данных).

---

## Фаза 1 закрыта ✅

Steps 1-6 готовы. Бот работает на Postgres end-to-end, тесты зелёные,
e2e через Telegram подтверждён. Следующее — фаза 2 (steps 7-13):
новая реляционная модель + команды бота.

### step_7 (2026-05-28)

- **TRUNCATE боевой БД** перед миграцией: `TRUNCATE users, sessions, runs,
  candidates_found, vacancies_found RESTART IDENTITY CASCADE`. Снесено
  3 user / 28 sessions / 10 runs / 35 candidates_found / 1 vacancies_found
  (всё тестовое от step_3..step_6). `_migrations` сохранена.
- **Миграция `db/migrations/002_relational_model.sql`** применена через
  `python -m db.client --migrate`. Состав:
  - ENUM-типы: `ai_status` (pass/uncertain/fail), `vacancy_source`
    (manual/apify_job_search)
  - Новые таблицы: `companies`, `vacancies`, `candidates`, `searches`,
    `candidate_screenings`
  - `vacancies.linkedin_url`: **partial UNIQUE** `WHERE
    source='apify_job_search'`. Manual-вакансии (linkedin_url=NULL) не
    конфликтуют. Симметрично `candidates.linkedin_url UNIQUE` —
    одна job-страница LinkedIn = одна глобальная строка.
  - `searches.original_boolean`: NULL когда юзер не правил boolean
    (не дублируем `boolean_text`).
  - `candidates.raw_profile_json`: JSONB (переезд с TEXT).
  - `sessions`: убраны `input_text`, `brief_text`, `boolean_text`,
    `boolean_text_original`; добавлены `vacancy_id`, `search_id` (FK).
  - DROP `candidates_found`, `vacancies_found` (с CASCADE, чтобы FK на runs
    не блокировали).
- **Верификация**: 9 таблиц в `public`, оба ENUM-типа, JSONB-колонка,
  partial UNIQUE-индекс — все на месте. `_migrations` содержит обе
  миграции.
- **Грабля для step_8/9 — расхождение тест-фикстура vs боевая схема:**
  `tests/conftest.py` зовёт `db.client.initialize_from_schema()`, который
  читает `db/schema.sql` (= **старая** v1-схема) и одновременно записывает
  все файлы миграций как "уже применённые". Тесты сейчас 89/89 зелёные
  **на старой схеме**, в то время как боевая БД уже на новой. До step_9
  (когда `db/client.py` начнёт писать в новую модель) надо выбрать один
  из:
    - **(а)** обновить `db/schema.sql` под актуальное состояние (= схема
      после 002), а 002 оставить как историческую миграцию;
    - **(б)** фикстура применяет `initialize_from_schema` (= только v1) +
      затем `apply_migrations` руками;
    - **(в)** комбинированно: `schema.sql` всегда = "что должно быть в
      свежей БД", миграции остаются как путь апгрейда.
  Решение зафиксируем в step_8.
- **Коммит**: `feat(db): step 5.5.7 — relational model migration` (далее).

### step_8 (2026-05-28)

- **Решение по фикстуре vs миграции (открытый вопрос из step_7) — вариант
  (а):** `db/schema.sql` обновлён до снимка актуального состояния
  (v1 + 002 склеены). Конвенция: при добавлении новой миграции NNN_xxx.sql
  одновременно обновлять `schema.sql`. Альтернативы (б)/(в) — фикстура
  применяет миграции — отвергнуты ради скорости тестов и простоты.
  В comment в `schema.sql` зафиксирована эта конвенция.
- **schema.sql v2 — реструктура**: использован `DO $$ ... EXCEPTION WHEN
  duplicate_object` для идемпотентного создания ENUM (CREATE TYPE не имеет
  IF NOT EXISTS в PG <16). Late-bind FK через `ALTER TABLE ADD CONSTRAINT`
  внутри `DO $$ ... EXCEPTION WHEN duplicate_object` — потому что
  `vacancies.discovered_in_run_id` ссылается на `runs`, а
  `sessions.search_id` на `searches`, и обе target-таблицы определены
  после ссылающихся.
- **CRUD-методы добавлены в `db/client.py`:** companies (3), vacancies (3),
  candidates (3 — `upsert_candidate` использует `clean_profile()` из
  `core/candidate_screener/core/profile_cleaner.py` чтобы вытащить
  name/headline/location/about из raw Apify-структуры), searches (3),
  candidate_screenings (4 + 2 предиката). Итого 18 новых async-методов.
- **`upsert_candidate(raw_profile: dict)`** — единая точка преобразования
  Apify-формата → таблица `candidates`. Реюзает `clean_profile()`,
  чтобы не дублировать парсинг nested-location и т.п. ON CONFLICT
  (linkedin_url) DO UPDATE — обновляет все поля + `last_seen_at = now()`.
- **`create_screening`** — использует трюк «no-op upsert returning id»:
  `ON CONFLICT (candidate, vacancy, run) DO UPDATE SET ai_status =
  candidate_screenings.ai_status RETURNING id`. UPDATE присваивает
  колонке её же значение — синтаксически "UPDATE случился", RETURNING
  возвращает id. **Важно**: при retry payload НЕ перезаписывается
  (проверено в `test_create_screening_unique_returns_existing_id`).
- **Два предиката дедупа:**
  - `is_candidate_known_to_user(user_id, linkedin_url)` — bool, для
    PIPELINE_DONE-сообщения "X из 25 уже видели".
  - `is_candidate_screened_for_vacancy(linkedin_url, vacancy_id)` — bool,
    для пропуска LLM в hot-path pipelines.py (на step_9).
  Оба через JOIN `candidates ↔ candidate_screenings`.
- **`_COLUMNS["sessions"]`** обновлён: -input_text -brief_text
  -boolean_text -boolean_text_original +vacancy_id +search_id.
- **Удалено** из `db/client.py`: `insert_candidates`, `insert_vacancies`,
  `is_candidate_known`, `is_vacancy_known` (старые таблицы DROP'нуты).
- **Тесты:**
  - Новый файл `tests/test_db_relational.py` — 16 тестов
    (companies, vacancies включая partial UNIQUE, candidates включая
    concurrent upsert, searches, screenings, оба предиката). Все зелёные
    с первого прогона.
  - `tests/test_db_client.py`: удалены 4 теста на удалённые методы,
    `test_update_session_bumps_updated_at` адаптирован (без `input_text`).
  - `tests/test_handlers.py`: `test_text_in_waiting_input_generates_boolean`
    помечен `pytest.mark.skip` (handler пишет в дропнутые колонки —
    переписать на step_9).
  - `tests/test_pipelines_resume.py`: оба теста (`test_resumes_from_*`,
    `test_calls_discover_*`) помечены `skip` — `_seed_session_with_input`
    использует `input_text/boolean_text*`. Переписать на step_9.
  - **Итог: 98 passed, 3 skipped, 0 failed** (было 89 на v1). Цель
    "90+ зелёных" перевыполнена.
- **Грабля для step_9 — handler/pipelines красные в проде:** после
  изменений в `db/client.py` бот **не запустится** на TG без переписи
  `bot/handlers.py` и `bot/pipelines.py` (они вызывают
  `db.insert_candidates`, `db.is_candidate_known`, и пишут в
  `sessions.input_text`). Бот сейчас не запущен (`/refind_vacancy`
  упадёт). Step_9 чинит это, переписывая handler/pipelines на новую
  модель и снимая `skip` с тестов.
- **Коммит**: `feat(db): step 5.5.8 — CRUD methods for new relational model`.

### step_9 (2026-05-28)

- **Решение по `pending_boolean` (развилка из step_7):** выбран вариант
  (а) — отдельная **миграция 003** `ALTER TABLE sessions ADD COLUMN
  pending_boolean TEXT`. Альтернатива (б) — создавать `searches`
  сразу — отвергнута: `searches` представляет коммитнутый запрос,
  не должна содержать черновики (особенно при `/cancel`). История
  миграций (`002`) **не переписывалась** — она уже закоммичена в
  `a326231`, ретроспективная правка опасна.
- **schema.sql v3** обновлён (sessions.pending_boolean добавлен в
  соответствии с конвенцией step_8 — schema.sql всегда = снимок
  актуального состояния).
- **`_COLUMNS["sessions"]`** в `db/client.py` пополнен `pending_boolean`.
- **`bot/handlers.py` переписан под новую модель:**
  - `_generate_boolean_and_advance(db, session, user_id, input_text,
    brief_text, say)` — добавлен параметр `user_id`. Создаёт
    `vacancies`-строку (`source='manual'`, name=`f"vacancy_{session_id}"`)
    **до** генерации boolean (vacancy_id потом сохраняется в session
    одним UPDATE'ом вместе с pending_boolean).
  - Ветка `WAITING_BOOLEAN_CONFIRM` создаёт `searches`-строку и проставляет
    `session.search_id`. `pending_boolean` обнуляется. Если юзер правил
    boolean — `searches.original_boolean` = LLM-вывод, иначе NULL
    (семантика подтверждена в step_7). Сравнение `pending != boolean`
    защищает от случая «юзер прислал тот же текст что и LLM» (тогда
    `original_boolean = NULL`, не дубль).
- **`bot/pipelines.py` переписан:**
  - `_run_vacancy_pipeline` читает `vacancy_id`/`search_id` из
    `session`, дёргает `db.get_vacancy` и `db.get_search` — boolean
    теперь берётся из `searches.boolean_text`, JD/brief — из
    `vacancies.jd_text/brief_text`. Если `vacancy_id` или `search_id`
    NULL — `RuntimeError` (защита от вызова до подтверждения).
  - `vacancy_name` в `screen_candidates(vacancy_name=...)` теперь берётся
    из `vacancy["name"]` (см. backlog — извлечение сводки из LLM
    отложено).
  - **Two-axis dedup:** для каждого профиля сначала
    `is_candidate_screened_for_vacancy(url, vacancy_id)` (skip без LLM
    если уже было); затем `is_candidate_known_to_user(user_id, url)`
    (счётчик "already_seen", но НЕ skip — другая вакансия = другой
    результат).
  - **Запись результата:** `_persist_screenings` — новая helper-функция.
    Для каждой пары `(profile, db_row)` (zip strict — гарантия что
    screen_candidates возвращает rows в порядке profiles):
    `upsert_candidate(profile)` → `create_screening(candidate_id,
    vacancy_id, run_id, user_id, ai_*)`. Глобальная база +
    join-таблица.
  - В `result` добавлены `already_seen` (cross-vacancy для user) и
    `skipped_same_vacancy` (per-vacancy dedup). Поле `already_seen`
    пока **не** показывается юзеру в `PIPELINE_DONE` — это пункт
    backlog'а (формулировку обсудить, выбрать на step_10/11).
- **Тесты:**
  - `tests/test_handlers.py`: skip-нутый `test_text_in_waiting_input_*`
    переписан как 3 новых теста (vacancy создаётся, confirm создаёт
    search, edit создаёт search с original_boolean).
  - `tests/test_pipelines_resume.py`: оба skip-нутых теста переписаны,
    `_seed_session_with_input` → `_seed_running_session` (новая модель).
  - **Новый файл `tests/test_pipelines_new_model.py` — 4 теста:**
    happy-path landing в новые таблицы; per-vacancy dedup пропускает
    LLM; per-user already_seen считается без skip'а скрининга;
    `search_id IS NULL` → RuntimeError.
  - **Итог: 107 passed, 0 skipped, 0 failed** (было 98 / 3 skip в step_8).
- **Smoke-старт бота:** `python -m bot.main` стартует чисто — БД
  подключается, polling запускается, `getUpdates` уходит к Telegram.
  Реальный TG e2e — на step_12.
- **Коммит**: `feat(bot): step 5.5.9 — pipelines/handlers on new relational model`.

### step_12 e2e — частично (2026-06-26)

**Скип step_10 и step_11 — пошли сразу в e2e на новой модели**, чтобы
убедиться что pipeline после большой переписи step_9 не сломан до
того, как добавлять команды поверх. Дедуп полноценно тестируется
только когда есть `/replay_search` (step_10), поэтому e2e на этом
шаге — частичный.

**Грабли пойманные:**

- **PG на Mac mini слетел `listen_addresses`.** Конфиг
  `postgresql.conf` корректный (`localhost,100.104.30.62`), но
  процесс был стартован раньше — слушал только localhost. `psql -c
  'SHOW listen_addresses'` показывал правильное значение, но `lsof
  -i :5432` — только `::1` / `127.0.0.1`. Step_1 предупреждал: эта
  настройка требует **restart**, не reload. Восстановили через
  `launchctl kickstart -k gui/$(id -u)/com.rm_mini.postgres` (см.
  step_1 — корректный путь без `LC_ALL`-гвоздя). `rm_mini`
  переподключился сам.
- **JobQueue extra отсутствовал**: `python-telegram-bot>=21.0` без
  `[job-queue]` → `context.job_queue is None` → `AttributeError` в
  `on_document` при media-group дебаунсе. Юзер прислал 2 файла
  (vacancy+brief одним свайпом) → бот молчал, в логе traceback.
  Установили `python-telegram-bot[job-queue]>=21.0`, обновили
  `requirements.txt`. Был **давний** баг: в step_5/6 e2e юзер
  посылал JD текстом, on_document не дёргался.

**Что прошло:**

- Round 1 (vacancy_2, with brief): 25/25 candidates, 1 pass + 4
  uncertain + 20 fail, $1.04, 6:04. Все связи FK на месте.
- Round 2 (vacancy_4, with brief, другой boolean): 25/25, 1 pass +
  24 fail, $0.61, 3:13. **Resume сработал из stale
  `data/sessions/4/raw_apify.json`** от 2026-05-20 — скринили
  старых кандидатов, не новых. См. backlog "resume-from-disk
  путается". Это **не баг pipeline**, а грабля артефактов.

**Что подтверждено:**
- Бот работает end-to-end на новой модели (vacancy → search →
  run → candidates → screenings).
- Vacancy/Search/Run/Candidates/Screenings создаются и связаны FK.
- Brief (второй файл) корректно сохраняется в `vacancies.brief_text`.
- Cancelled-сессии не блокируют новые (тестировал переход cancel
  → новый /refind_vacancy).
- Resume-from-disk работает (хоть и подсунул старые данные).
- `vacancies.linkedin_url` partial UNIQUE не сработал (все
  вакансии `source='manual'`, linkedin_url IS NULL — норм).
- `_COLUMNS["sessions"]` guard работает — все update_session с
  vacancy_id/search_id/pending_boolean прошли без ошибок.

**Что НЕ подтверждено (нужен step_10/11):**
- Реальный дедуп между вакансиями: 50 unique candidates, 0
  пересечений — Apify в раундах принёс разных людей.
- `already_seen` счётчик в PIPELINE_DONE (собираем но не
  показываем).
- `/replay_search`, `/rescreen`, `/candidate` — этих команд нет.

**Решение:** step_12 объявлен пройденным в части "pipeline жив".
Полный дедуп-тест — после step_10 (`/replay_search` сделает
бесплатный повтор с теми же данными). Идём в step_10.

**Cost:** $1.65 на два прогона.

**Backlog добавлен (в `task_tracker/backlog/step_5_backlog.md`):**
- resume-from-disk путается на старых `data/sessions/N/raw_apify.json`
- `sessions.pending_boolean` не очищается при `/cancel`

### step_10 (2026-06-26, новое окно)

**Решения, принятые с Ренатом перед стартом:**
- `/replay_search` **вынесена в backlog** — сначала закрываем базовые
  read-only команды + locations-фикс, гоняем e2e, реплеи потом. step_10 =
  ровно 3 команды.
- Добавлен **step_11.5** (locations из JD в Apify-запрос) — баг качества
  выдачи, подтверждён на step_6/12.
- Resume-from-disk ключ остаётся в backlog. Перед e2e чистим
  `data/sessions/*` руками (locations-фикс требует свежего Apify).
- already_seen формулировка: «Уже видели на других вакансиях: X».

**Сделано:**
- `db.list_recent_runs_by_user(user_id, limit=10)` — новый метод (вместо
  `db._query_all` в хендлере, как предлагал устаревший step_10.md).
  Остальные методы (`list_vacancies_by_user`, `list_searches_by_vacancy`,
  `list_screenings_by_vacancy`, `get_vacancy`) уже были из step_8.
- `bot/handlers.py`: `cmd_vacancies`, `cmd_vacancy`, `cmd_runs`.
  Access-control: чужая вакансия → `VACANCY_NOT_FOUND` (same-as-404),
  `/runs` фильтрует по `user_id` в SQL.
- **Fix pending_boolean при cancel** (backlog): `cmd_cancel` и
  `_start_session` (cancel предыдущей) теперь шлют `pending_boolean=None`.
- **already_seen в PIPELINE_DONE**: хендлер пробрасывает
  `result["already_seen"]`, шаблон показывает строку всегда (0 если нет
  повторов). Поле уже считалось в pipelines.py с step_9.
- `bot/main.py`: 3 CommandHandler'а зарегистрированы.
- WELCOME обновлён (vacancies/vacancy/runs).

**Тесты:**
- Новый `tests/test_handlers_listing.py` — 11 тестов (empty/list/card/
  not-found/usage/access-denied/own-only/limit-10). Переиспользуют
  Telegram-моки из test_handlers.py, второй whitelisted-юзер (999000)
  для проверки изоляции.
- `tests/test_handlers.py`: +1 тест `test_cancel_clears_pending_boolean`.
- **Итог: 117 passed, 0 skipped** (было 107).
- Smoke-старт бота чистый (БД подключилась, polling пошёл).
- **Коммит**: `feat(bot): step 5.5.10 — listing commands`.

### step_11.5 (2026-06-30, новое окно)

Баг: JD с "Germany" → кандидаты из всех стран. Locations терялись между
LLM-выводом и Apify. **Низ цепочки уже был готов** (`discover_candidates`
принимал `locations`, `from_apify_search` пробрасывал в Apify) — не хватало
парсинга + проброса середины.

**Решения с Ренатом перед стартом:**
- Парсим locations + experience, сохраняем оба в JSONB, но в Apify прокидываем
  **только locations** (experience — на будущий шаг).
- Хранение в `searches`, JSONB-колонка, **миграция 004** (не 005 — промпт
  ошибался: step_11 ушёл в backlog вместе со своей миграцией 004, 003 была
  последней применённой).
- Показываем локации юзеру в `BOOLEAN_GENERATED`.
- Редактирование params юзером — НЕ в этом шаге.
- JSONB = очищенные списки (experience валидируется по множеству).

**Всплывшая развилка (решена → вариант A):** params парсятся при генерации
boolean, а нужны на confirm (где создаётся `searches`). Между ними бот может
рестартнуть → память не годится, markdown потерян. Решение — транзиентная
колонка `sessions.pending_apify_params` (точное зеркало `pending_boolean` из
миграции 003). Чистится на confirm. **Поэтому миграция 004 добавила ДВЕ
колонки**: `searches.apify_params` + `sessions.pending_apify_params`.

**Сделано (4 коммита):**
- **11.5a** (`bd51c18`): `extract_apify_params()` в `generator.py` рядом с
  `extract_boolean()` + 10 тестов. Защитный: нет блока / мусор / пусто →
  пустые списки, никогда не падает.
- **11.5b** (`d143ae7`): миграция 004 + `schema.sql` + `create_search`
  (kwarg `apify_params`, `$::jsonb` как в `upsert_candidate`) + guard
  `_COLUMNS["sessions"]`.
- **11.5c** (`53939a0`): `generate_boolean()` теперь возвращает
  `(boolean, params)`; handler кладёт params в `pending_apify_params`,
  переносит в `searches.apify_params` на confirm; строка «📍 Локации» в
  `BOOLEAN_GENERATED`.
- **11.5d** (`0f75874`): `_run_vacancy_pipeline` читает `apify_params`,
  передаёт `locations` в `discover_candidates`. NULL/пустой → `None`.

**Грабли:**
- **`\s` в regex жрёт `\n`.** Первая версия `extract_apify_params` на
  строке `- locations: ` (пустое значение) матчила значение СЛЕДУЮЩЕЙ строки,
  потому что `\s*` после `:` проглатывал перевод строки. Фикс: `[^\S\n]*`
  (только горизонтальные пробелы). Тест `test_empty_locations_value` это
  поймал.
- **asyncpg + JSONB:** не сериализует dict автоматически и не кастит str в
  jsonb. На запись — `json.dumps(...)` + `::jsonb` в SQL. На чтение — возвращает
  **str**, нужен `json.loads` (паттерн уже был в `test_db_relational.py:133`).
  `update_session` (generic `**fields`) научили кастить known JSONB-колонки
  через `_JSONB_SESSION_COLUMNS`.
- **Params привязаны к JD, не к boolean.** Если юзер редактирует boolean на
  confirm — params остаются (они из `## Apify params`, не из boolean-строки).

**Тесты:**
- Новый `tests/test_extract_apify_params.py` — 10 тестов.
- `test_db_relational.py` +3 (apify_params round-trip, NULL default,
  pending_apify_params на sessions).
- `test_handlers.py`: моки `generate_boolean` обновлены на кортеж + проверки
  draft→committed handoff и очистки на confirm.
- `test_pipelines_new_model.py` +3 (locations→discover, NULL→None, []→None).
- **Итог: 133 passed** (было 117 + 16 новых).
- **Миграция 004 применена на боевой PG** (`python -m db.client --migrate`),
  обе колонки подтверждены через `information_schema.columns`.

**Не сделано (осознанно, в backlog/будущий шаг):** experience в Apify (лежит в
JSONB готовый), редактирование params юзером (`WAITING_PARAMS_CONFIRM`),
exclude_titles/titles/seniority. Ручной TG e2e с реальным Apify — на step_12.
