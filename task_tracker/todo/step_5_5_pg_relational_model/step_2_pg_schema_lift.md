# Шаг 2: Lift SQLite-схемы в PG-диалект

> Зависит от: step_1
> Статус: [ ] pending

## Задача

Переписать `db/schema.sql` и `db/migrations/001_initial.sql` под PG-диалект,
сохранив **те же таблицы и логику** что и в SQLite. Никаких новых таблиц,
никаких изменений колонок — только диалект.

Это локализует риск: на step_3 поменяем клиента, на step_4 — вызовы, и
любая регрессия будет видна сразу.

## Конкретные действия

1. Создать `db/schema_pg.sql` (новый файл) с теми же таблицами:
   `_migrations`, `users`, `sessions`, `runs`, `candidates_found`, `vacancies_found`.
2. Замены диалекта:
   - `INTEGER PRIMARY KEY AUTOINCREMENT` → `BIGSERIAL PRIMARY KEY`.
   - `TEXT NOT NULL DEFAULT (datetime('now'))` → `TIMESTAMPTZ NOT NULL DEFAULT now()`.
   - `INTEGER` → `BIGINT` для всех id'шников (telegram_user_id — BIGINT).
   - `REAL` → `DOUBLE PRECISION` (для cost_usd, duration_sec).
   - `CHECK (... IN (...))` — оставить как есть, PG это поддерживает (ENUM-тип
     откладываем до фазы 2).
   - Колонки `raw_apify_path`, `screening_json`, `report_md`, `raw_profile_json`,
     `raw_job_json` — оставить `TEXT` пока (фаза 2 переведёт raw_profile_json и
     raw_job_json на JSONB).
3. `PRAGMA foreign_keys = ON;` — убрать, в PG FK всегда форсятся.
4. Индексы `CREATE INDEX IF NOT EXISTS` — оставить как есть.
5. Удалить старый `db/schema.sql` и `db/migrations/001_initial.sql`. Переименовать
   `schema_pg.sql` → `schema.sql`, и `001_initial.sql` написать с тем же
   содержимым (без `_migrations` CREATE TABLE — он будет в schema.sql и применится
   при init).
6. Прогнать схему руками через psql или через `asyncpg`:
   ```bash
   python -c "
   import asyncio, asyncpg, os
   from dotenv import load_dotenv; load_dotenv()
   from pathlib import Path
   async def main():
       conn = await asyncpg.connect(host=os.environ['PG_HOST'], port=int(os.environ['PG_PORT']), user=os.environ['PG_USER'], password=os.environ['PG_PASSWORD'], database=os.environ['PG_DATABASE'])
       sql = Path('db/schema.sql').read_text(encoding='utf-8')
       await conn.execute(sql)
       rows = await conn.fetch(\"SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename\")
       print([r['tablename'] for r in rows])
       await conn.close()
   asyncio.run(main())
   "
   ```

## Тесты

- На этом шаге unit-тесты не запускаются (db/client.py ещё sqlite-based).
- Smoke-тест выше — единственный критерий.

## Команды для верификации

```bash
# Все ожидаемые таблицы должны быть в выводе
python ...  # см. блок выше

# Файлы существуют и не содержат sqlite-only синтаксиса
grep -i "AUTOINCREMENT\|PRAGMA\|datetime('now')" db/schema.sql db/migrations/001_initial.sql && echo "FAIL: SQLite-only syntax found" || echo "OK"
```

## Критерии готовности

- [ ] `db/schema.sql` переписан под PG-диалект
- [ ] `db/migrations/001_initial.sql` существует и содержит ту же схему минус `_migrations` таблица
- [ ] При выполнении `schema.sql` через `asyncpg` создаются все 6 таблиц без ошибок: `_migrations`, `users`, `sessions`, `runs`, `candidates_found`, `vacancies_found`
- [ ] Нет sqlite-специфичных конструкций в `db/*.sql` (AUTOINCREMENT, PRAGMA, datetime('now'))
- [ ] Файлы `data/recruiter_assistant.db` и WAL-shm/wal остаются на диске, но больше не используются (удалим в step_13)
