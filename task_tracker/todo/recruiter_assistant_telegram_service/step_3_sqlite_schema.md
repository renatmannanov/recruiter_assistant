# Step 3: SQLite-схема и DB-клиент

> Статус: done
> Зависит от: step_2 (новый репо существует)

## Цель

Создать SQLite-схему, миграции, Python-клиент с CRUD-функциями. На этом шаге **бот ещё не пишется**, только хранилище.

## Изменения против старой версии плана

- ❌ Убраны `candidates_database_id` / `vacancies_database_id` из `users` — Notion в v1 нет
- ❌ Убраны `notion_page_id` / `notion_page_url` — Notion в v1 нет
- ❌ Убрана таблица `agent_invocations` — LLM-агента в v1 нет
- ✏️ `raw_apify_json` → `raw_apify_path`: сырой Apify dump хранится **файлом на диске** (`data/sessions/<id>/raw_apify.json`), в БД только путь. БД остаётся компактной
- ✏️ Добавлен `report_path` в `sessions` — путь к сгенерированному `.md` отчёту на диске

## Схема

### users

```sql
CREATE TABLE users (
  telegram_user_id INTEGER PRIMARY KEY,
  display_name TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_users_created ON users(created_at);
```

### sessions

```sql
CREATE TABLE sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(telegram_user_id),
  pipeline_type TEXT NOT NULL CHECK (pipeline_type IN ('vacancy_to_candidates', 'cv_to_jobs')),
  step TEXT NOT NULL CHECK (step IN ('waiting_input', 'waiting_boolean_confirm', 'running', 'done', 'error', 'cancelled')),
  input_text TEXT,                           -- сам JD или CV
  brief_text TEXT,                           -- опциональный brief (если прислан 2-м файлом), NULL если нет
  boolean_text TEXT,                         -- финальный (после правки) boolean
  boolean_text_original TEXT,                -- оригинальный сгенерированный (если правили)
  report_path TEXT,                          -- путь к .md отчёту на диске (data/sessions/<id>/report.md)
  error_text TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_sessions_user ON sessions(user_id);
CREATE INDEX idx_sessions_user_step ON sessions(user_id, step);
CREATE INDEX idx_sessions_created ON sessions(created_at);
```

**Примечание:** state `waiting_brief` убран — brief приходит сразу 1-2 файлами вместе с vacancy/cv (см. step_4, step_5).

### runs

```sql
CREATE TABLE runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id INTEGER NOT NULL REFERENCES sessions(id),
  user_id INTEGER NOT NULL REFERENCES users(telegram_user_id),  -- денормализация
  pipeline_type TEXT NOT NULL CHECK (pipeline_type IN ('vacancy_to_candidates', 'cv_to_jobs')),
  status TEXT NOT NULL CHECK (status IN ('running', 'done', 'failed')),
  raw_apify_path TEXT,                       -- путь к сырому Apify dump на диске
  screening_json TEXT,                       -- результаты screening (компактно, ~10KB — ок в БД)
  report_md TEXT,                            -- финальный markdown-отчёт (дубль файла, для быстрого доступа)
  found_count INTEGER,
  screened_count INTEGER,
  passed_count INTEGER,
  cost_usd REAL,
  duration_sec REAL,
  error_text TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_runs_session ON runs(session_id);
CREATE INDEX idx_runs_user ON runs(user_id);
CREATE INDEX idx_runs_user_pipeline ON runs(user_id, pipeline_type);
CREATE INDEX idx_runs_created ON runs(created_at);
```

> `report_md` в БД — компактный (markdown-отчёт обычно <50KB), удобно достать SQL'ом для аналитики. Сам файл также лежит на диске (`sessions.report_path`) — его бот отправляет в Telegram. `raw_apify_path` — только путь, тяжёлый JSON на диске.

### candidates_found (результаты pipeline `vacancy_to_candidates`)

```sql
CREATE TABLE candidates_found (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL REFERENCES runs(id),
  user_id INTEGER NOT NULL REFERENCES users(telegram_user_id),  -- денормализация
  linkedin_url TEXT NOT NULL,
  name TEXT,
  ai_status TEXT CHECK (ai_status IN ('pass', 'fail', 'uncertain', NULL)),
  ai_score INTEGER,
  ai_comment TEXT,
  raw_profile_json TEXT,                     -- профиль из Apify (компактный — ок в БД)
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_candidates_run ON candidates_found(run_id);
CREATE INDEX idx_candidates_user ON candidates_found(user_id);
CREATE INDEX idx_candidates_user_linkedin ON candidates_found(user_id, linkedin_url);  -- для dedup
CREATE INDEX idx_candidates_user_status ON candidates_found(user_id, ai_status);
```

### vacancies_found (результаты pipeline `cv_to_jobs`)

```sql
CREATE TABLE vacancies_found (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL REFERENCES runs(id),
  user_id INTEGER NOT NULL REFERENCES users(telegram_user_id),  -- денормализация
  linkedin_url TEXT NOT NULL,
  title TEXT,
  company TEXT,
  location TEXT,
  ai_score INTEGER,
  ai_recommendation TEXT,
  raw_job_json TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_vacancies_run ON vacancies_found(run_id);
CREATE INDEX idx_vacancies_user ON vacancies_found(user_id);
CREATE INDEX idx_vacancies_user_linkedin ON vacancies_found(user_id, linkedin_url);
```

## Связи (визуально)

```
users (PK telegram_user_id)
  │
  └── sessions (FK user_id)
        │
        └── runs (FK session_id, денорм user_id)
              │
              ├── candidates_found (FK run_id, денорм user_id)
              └── vacancies_found (FK run_id, денорм user_id)
```

## Полезные запросы (документация в README)

```sql
-- Все мои завершённые сессии
SELECT * FROM sessions WHERE user_id = ? AND step = 'done' ORDER BY created_at DESC;

-- Все кандидаты которые прошли скрининг для меня (за всё время)
SELECT * FROM candidates_found WHERE user_id = ? AND ai_status = 'pass' ORDER BY created_at DESC;

-- Кандидаты по конкретной сессии
SELECT cf.* FROM candidates_found cf
JOIN runs r ON cf.run_id = r.id
WHERE r.session_id = ?;

-- Dedup: уже искали этого LinkedIn у меня?
SELECT id, ai_status, created_at FROM candidates_found
WHERE user_id = ? AND linkedin_url = ?
ORDER BY created_at DESC LIMIT 1;

-- Аналитика: сколько $ потратил за месяц
SELECT SUM(cost_usd) FROM runs
WHERE user_id = ? AND created_at >= datetime('now', '-30 days');
```

## Миграции

Простой механизм без alembic:

```
db/
├── schema.sql                  # текущая полная схема (для новых установок)
├── migrations/
│   ├── 001_initial.sql
│   └── ...
└── client.py
```

`client.py` при инициализации:
1. Если БД не существует — применяет `schema.sql` целиком
2. Если существует — проверяет таблицу `_migrations` (id, name, applied_at), применяет недостающие

## DB-клиент (db/client.py)

### Технические требования

**WAL-режим** (обязательно): при открытии БД `PRAGMA journal_mode=WAL;` — иначе concurrent writes (бот async + параллельные юзеры) дадут `database is locked`.

**Thread/asyncio safety:** `sqlite3.connect(path, check_same_thread=False)` + `threading.Lock` вокруг всех write-операций. Проще на v1.

**CLI-интерфейс:** `python -m db.client --init` инициализирует БД.

### API

```python
class DB:
    def __init__(self, path: str):
        # PRAGMA journal_mode=WAL; check_same_thread=False + threading.Lock
        ...

    # users
    def get_user(self, telegram_user_id: int) -> dict | None
    def upsert_user(self, telegram_user_id: int, display_name: str = None)

    # sessions
    def create_session(self, user_id: int, pipeline_type: str) -> int
    def get_session(self, session_id: int) -> dict
    def get_active_session(self, user_id: int, pipeline_type: str = None) -> dict | None
        # Последняя незавершённая (step NOT IN ('done','error','cancelled'))
    def update_session(self, session_id: int, **fields)
    def complete_session(self, session_id: int, report_path: str)
    def fail_session(self, session_id: int, error_text: str)
    def cleanup_stale_sessions(self, older_than_minutes: int = 30) -> int
        # step='running' старше N минут → 'error', error_text='restarted_or_stalled'

    # runs
    def create_run(self, session_id: int, user_id: int, pipeline_type: str) -> int
    def update_run(self, run_id: int, **fields)
    def complete_run(self, run_id: int, found_count, screened_count, passed_count, cost_usd, duration_sec)
    def fail_run(self, run_id: int, error_text: str)

    # candidates / vacancies
    def insert_candidates(self, run_id: int, user_id: int, candidates: list[dict])
    def insert_vacancies(self, run_id: int, user_id: int, vacancies: list[dict])
    def is_candidate_known(self, user_id: int, linkedin_url: str) -> bool
    def is_vacancy_known(self, user_id: int, linkedin_url: str) -> bool
```

Никакого ORM — только sqlite3 stdlib + dict-based rows.

### CLI

```python
# db/client.py
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--migrate", action="store_true")
    parser.add_argument("--db-path", default=os.environ.get("DB_PATH", "./data/recruiter_assistant.db"))
    args = parser.parse_args()
    if args.init:
        DB(args.db_path).initialize_from_schema()
    elif args.migrate:
        DB(args.db_path).apply_migrations()
```

## Критерии готовности

- [x] `db/schema.sql` создан, открывается через `executescript` без ошибок (проверено для schema.sql и 001_initial.sql)
- [x] Схема **не содержит** Notion-полей (`*_database_id`, `notion_page_*`) и таблицы `agent_invocations`
- [x] `db/client.py` реализован с API выше (+ guardrail на `**fields` колонки)
- [x] При открытии БД выставляется `PRAGMA journal_mode=WAL`, проверено: `PRAGMA journal_mode` → `wal`
- [x] DB-клиент корректен при параллельных вызовах из asyncio (тест `test_concurrent_inserts_via_asyncio_gather`: 10 `insert_candidates` через `asyncio.gather` + `asyncio.to_thread`)
- [x] `python -m db.client --init` создаёт БД из пустого `data/` за один вызов
- [x] `cleanup_stale_sessions(older_than_minutes=30)` помечает зависшие сессии как error (тест `test_cleanup_stale_sessions`)
- [x] `get_active_session(user_id, pipeline_type='vacancy_to_candidates')` фильтрует по типу (тест `test_get_active_session_filters_by_pipeline`)
- [x] Юнит-тесты: 21 тест в `tests/test_db_client.py` — user/session/run/candidates, dedup, cleanup, guardrail, thread-safety. Все зелёные
- [x] `data/.gitkeep` есть и tracked, `data/*.db` в `.gitignore` (проверено `git check-ignore`)
- [x] README обновлён: секция "База данных" — init/migrate, WAL, где лежит файл

## Заметки по реализации

- `001_initial.sql` — копия `schema.sql` (идентичный DDL, все `IF NOT EXISTS`). Fresh install через `schema.sql` и через миграцию дают одинаковый результат. `initialize_from_schema()` сразу помечает все миграции применёнными → последующий `--migrate` no-op.
- CHECK на `ai_status`: вместо `IN ('pass','fail','uncertain', NULL)` из плана написано `... IN (...) OR ai_status IS NULL` — корректнее (в SQLite `x IN (...,NULL)` для несовпадения даёт NULL, что в CHECK «проходит» случайно). Поведение то же — NULL разрешён.
- `update_session`/`update_run` принимают `**fields` → добавлен allow-list колонок (`_guard_columns`): неизвестное имя → `ValueError`, а не битый SQL.
