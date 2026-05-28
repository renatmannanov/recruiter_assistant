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

---
