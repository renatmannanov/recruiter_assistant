# Шаг 7: Реляционная схема — миграция 002

> Зависит от: step_6
> Статус: [ ] pending

## Задача

Спроектировать и написать миграцию `db/migrations/002_relational_model.sql`
с новой реляционной моделью данных. Не трогаем код приложения на этом шаге
— только SQL.

## Конкретные действия

### Новые ENUM-типы

```sql
CREATE TYPE ai_status AS ENUM ('pass', 'uncertain', 'fail');
CREATE TYPE vacancy_source AS ENUM ('manual', 'apify_job_search');
```

### Новые таблицы

```sql
CREATE TABLE companies (
  id          BIGSERIAL PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE,
  notes       TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE vacancies (
  id                    BIGSERIAL PRIMARY KEY,
  company_id            BIGINT REFERENCES companies(id),
  name                  TEXT,                    -- короткое имя для UI ("Sonia ASR")
  jd_text               TEXT,                    -- для source=manual
  brief_text            TEXT,                    -- опциональный brief
  linkedin_url          TEXT,                    -- для source=apify_job_search
  source                vacancy_source NOT NULL,
  title                 TEXT,                    -- для apify-source: parsed title
  location              TEXT,
  seniority             TEXT,
  created_by_user_id    BIGINT REFERENCES users(telegram_user_id),
  discovered_in_run_id  BIGINT REFERENCES runs(id),
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_vacancies_company         ON vacancies(company_id);
CREATE INDEX idx_vacancies_created_by      ON vacancies(created_by_user_id);
CREATE INDEX idx_vacancies_source          ON vacancies(source);

CREATE TABLE candidates (
  id                BIGSERIAL PRIMARY KEY,
  linkedin_url      TEXT NOT NULL UNIQUE,
  name              TEXT,
  headline          TEXT,
  location          TEXT,
  about             TEXT,
  raw_profile_json  JSONB,
  first_seen_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  notes             TEXT
);

CREATE INDEX idx_candidates_last_seen ON candidates(last_seen_at DESC);

CREATE TABLE searches (
  id                  BIGSERIAL PRIMARY KEY,
  vacancy_id          BIGINT NOT NULL REFERENCES vacancies(id),
  boolean_text        TEXT NOT NULL,
  original_boolean    TEXT,
  created_by_user_id  BIGINT NOT NULL REFERENCES users(telegram_user_id),
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_searches_vacancy ON searches(vacancy_id);

CREATE TABLE candidate_screenings (
  id              BIGSERIAL PRIMARY KEY,
  candidate_id    BIGINT NOT NULL REFERENCES candidates(id),
  vacancy_id      BIGINT NOT NULL REFERENCES vacancies(id),
  run_id          BIGINT NOT NULL REFERENCES runs(id),
  user_id         BIGINT NOT NULL REFERENCES users(telegram_user_id),
  ai_status       ai_status,
  ai_score        INTEGER,
  ai_comment      TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (candidate_id, vacancy_id, run_id)
);

CREATE INDEX idx_screenings_candidate ON candidate_screenings(candidate_id);
CREATE INDEX idx_screenings_vacancy   ON candidate_screenings(vacancy_id);
CREATE INDEX idx_screenings_run       ON candidate_screenings(run_id);
CREATE INDEX idx_screenings_user      ON candidate_screenings(user_id);
```

### Изменения существующих таблиц

```sql
-- sessions: убрать денормализованные поля, добавить FK
ALTER TABLE sessions DROP COLUMN input_text;
ALTER TABLE sessions DROP COLUMN brief_text;
ALTER TABLE sessions DROP COLUMN boolean_text;
ALTER TABLE sessions DROP COLUMN boolean_text_original;
ALTER TABLE sessions ADD COLUMN vacancy_id BIGINT REFERENCES vacancies(id);
ALTER TABLE sessions ADD COLUMN search_id  BIGINT REFERENCES searches(id);

CREATE INDEX idx_sessions_vacancy ON sessions(vacancy_id);

-- candidates_found: больше не нужна, всё переезжает в candidate_screenings
DROP TABLE IF EXISTS candidates_found CASCADE;

-- vacancies_found: тоже не нужна, jobs тоже будут переезжать в vacancies
-- (с source='apify_job_search') и в отдельную таблицу job_screenings на step_6
-- (cv_to_jobs). На step_5.5 — просто DROP.
DROP TABLE IF EXISTS vacancies_found CASCADE;
```

### Обновить колонку-аллоулист в client.py (на step_8)

`_COLUMNS["sessions"]` теряет 4 поля, получает 2 новых. Список руками
синхронизировать с миграцией.

## Тесты

На этом шаге кода нет — только SQL миграция. Проверка применения:

```bash
# Применить миграцию
python -m db.client --migrate

# Проверить через PG
python -c "
import asyncio, os, asyncpg
from dotenv import load_dotenv; load_dotenv()
async def main():
    conn = await asyncpg.connect(host=os.environ['PG_HOST'], port=int(os.environ['PG_PORT']), user=os.environ['PG_USER'], password=os.environ['PG_PASSWORD'], database=os.environ['PG_DATABASE'])
    rows = await conn.fetch(\"SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename\")
    print([r['tablename'] for r in rows])
    await conn.close()
asyncio.run(main())
"
```

Ожидается: `_migrations`, `candidates`, `candidate_screenings`, `companies`,
`runs`, `searches`, `sessions`, `users`, `vacancies`.

## Команды для верификации

См. блок выше.

## Критерии готовности

- [ ] `db/migrations/002_relational_model.sql` создана и применяется без ошибок
- [ ] В PG присутствуют все 9 таблиц (включая `_migrations`)
- [ ] `candidates_found` и `vacancies_found` отсутствуют
- [ ] `sessions` не имеет колонок `input_text`, `brief_text`, `boolean_text*`,
  но имеет `vacancy_id`, `search_id`
- [ ] ENUM-типы `ai_status` и `vacancy_source` созданы
- [ ] Unit-тесты ВРЕМЕННО красные (db.client.py ещё знает старые таблицы) —
  это починим на step_8
