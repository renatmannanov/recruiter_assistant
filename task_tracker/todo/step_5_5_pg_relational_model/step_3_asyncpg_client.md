# Шаг 3: Переписать db/client.py на asyncpg

> Зависит от: step_2
> Статус: [x] done (2026-05-28)

## Задача

Полностью переписать `db/client.py` с `sqlite3` на `asyncpg`. Все методы
становятся `async`. Сохраняем тот же публичный API (имена методов,
параметры, возвращаемые типы) — это критично для шага 4 (handlers и pipelines
должны изменяться минимально).

## Конкретные действия

1. Удалить `import sqlite3`, `import threading`, `_DB_DIR`, `_SCHEMA_PATH`,
   `_MIGRATIONS_DIR`, `_row_to_dict` (asyncpg.Record похож на dict),
   `_TERMINAL_STEPS` (остаётся, нужен для cleanup_stale_sessions).
2. Класс `DB` теперь принимает параметры подключения **из env** (через
   фабричный async метод `DB.connect(dsn=None)` или `DB.from_env()`):
   ```python
   class DB:
       def __init__(self, pool: asyncpg.Pool):
           self._pool = pool

       @classmethod
       async def connect(cls, dsn: str | None = None, *, min_size: int = 1, max_size: int = 5) -> "DB":
           dsn = dsn or os.environ["DATABASE_URL"]  # или собираем из PG_*
           pool = await asyncpg.create_pool(dsn=dsn, min_size=min_size, max_size=max_size)
           return cls(pool)

       async def close(self):
           await self._pool.close()
   ```
3. Все методы становятся async:
   - `async def get_user(...)`, `async def upsert_user(...)`,
   - `async def create_session(...)`, `async def get_session(...)`,
     `async def get_active_session(...)`, `async def update_session(...)`,
     `async def complete_session(...)`, `async def fail_session(...)`,
     `async def cleanup_stale_sessions(...)`,
   - `async def create_run(...)`, `async def get_run(...)`,
     `async def update_run(...)`, `async def complete_run(...)`,
     `async def fail_run(...)`,
   - `async def insert_candidates(...)`, `async def insert_vacancies(...)`,
     `async def is_candidate_known(...)`, `async def is_vacancy_known(...)`.
4. `_guard_columns` — оставить как был (валидация на стороне Python, не SQL).
5. Все SQL-запросы — заменить `?` на `$1, $2, ...` (PG-стиль).
6. `executemany` для bulk-insert (candidates/vacancies) — заменить на
   `await conn.executemany(sql, rows)` или просто цикл `executemany` через
   `asyncpg.Connection.executemany`. Без транзакции в первой версии — добавим
   когда понадобится.
7. `initialize_from_schema` и `apply_migrations` — переписать с использованием
   `await conn.execute(sql)` для целого скрипта. asyncpg умеет multiple
   statements в `execute()`, но без `;` в конце последнего statement он
   капризничает — проверить, при необходимости вызывать через `executescript`
   (его нет в asyncpg — придётся сплитить по `;` или прогонять через psql
   subprocess; решение зафиксировать в коде).
8. CLI `python -m db.client --init / --migrate` — оставить, но через
   `asyncio.run(...)` обернуть. Удалить `db.close()` после `_main` — заменить
   на async-context manager.
9. **DATABASE_URL** vs **PG_***:
   - Поддержать оба: если `DATABASE_URL` есть — использовать его, иначе
     собрать из `PG_HOST/PG_PORT/PG_USER/PG_PASSWORD/PG_DATABASE`.
   - Сборку DSN вынести в `_build_dsn()` в `db/client.py`.

## Тесты

Тесты пока **не** трогаем — они на этом шаге будут падать (sync API → async),
это ожидаемо. На step_5 переключим fixture.

Smoke-тест вручную через однострочник:
```python
python -c "
import asyncio, os
from dotenv import load_dotenv; load_dotenv()
from db.client import DB
async def main():
    db = await DB.connect()
    await db.initialize_from_schema()
    await db.upsert_user(123, 'Test')
    u = await db.get_user(123)
    assert u and u['telegram_user_id'] == 123, u
    print('OK', u)
    await db.close()
asyncio.run(main())
"
```

## Команды для верификации

```bash
# Файл не использует sqlite
grep -E "import sqlite3|threading\.Lock" db/client.py && echo "FAIL" || echo "OK"

# CLI --init работает
python -m db.client --init

# CLI --migrate работает (на пустой БД должен сказать 'No pending migrations')
python -m db.client --migrate

# Smoke сверху отрабатывает
```

## Критерии готовности

- [ ] `db/client.py` импортирует только `asyncpg`, `asyncio`, `os`, `pathlib`
- [ ] Все методы `DB` — async
- [ ] `DB.connect(dsn=None)` создаёт пул из env (DATABASE_URL или PG_* набор)
- [ ] `db/client.py` CLI команды `--init` и `--migrate` работают через asyncio
- [ ] Smoke-тест выше отрабатывает чисто (создаёт юзера, читает обратно)
- [ ] На этом шаге unit-тесты НЕ запускаем (они в SQLite-формате, починим на step_5)
- [ ] Бот пока запускаться не должен (импорты не починены) — это ожидаемо
