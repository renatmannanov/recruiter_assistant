# Шаг 5: PG-fixture для тестов

> Зависит от: step_4
> Статус: [x] done (2026-05-28)

## Задача

Переключить pytest fixture `db` с SQLite на Postgres. Тесты должны проходить
через реальный PG (тот же `recruiter_assistant_dev` инстанс на маке), но в
изолированной схеме или БД-namespace чтобы не конфликтовать с данными бота.

## Стратегия изоляции

Создаём отдельный PG schema namespace на каждый тестовый run (или на каждую
тест-сессию pytest):

- `CREATE SCHEMA test_<random>; SET search_path = test_<random>;`
- Применяем `schema.sql` в этом namespace
- В teardown — `DROP SCHEMA test_<random> CASCADE`

Это даёт изоляцию без отдельной БД на каждый тест (быстрее) и без
testcontainers.

## Конкретные действия

1. В `tests/conftest.py` (создать если нет) написать async-фикстуру:
   ```python
   import pytest
   import pytest_asyncio
   import uuid
   import asyncpg
   import os
   from pathlib import Path
   from db.client import DB

   pytest_plugins = ("pytest_asyncio",)

   @pytest_asyncio.fixture
   async def db():
       schema = f"test_{uuid.uuid4().hex[:8]}"
       # Подключаемся напрямую чтобы создать schema
       admin = await asyncpg.connect(dsn=os.environ.get("DATABASE_URL"))
       await admin.execute(f"CREATE SCHEMA {schema}")
       await admin.close()

       # Создаём пул, привязанный к схеме (init=set search_path)
       async def init_conn(conn):
           await conn.execute(f"SET search_path TO {schema}")
       pool = await asyncpg.create_pool(
           dsn=os.environ.get("DATABASE_URL"),
           min_size=1, max_size=3, init=init_conn,
       )
       d = DB(pool)
       await d.initialize_from_schema()
       yield d
       await d.close()

       admin = await asyncpg.connect(dsn=os.environ.get("DATABASE_URL"))
       await admin.execute(f"DROP SCHEMA {schema} CASCADE")
       await admin.close()
   ```
2. Все тесты, использующие `db` fixture, маркируем `@pytest.mark.asyncio` и
   делаем `async def test_...`.
3. `pytest.ini` или `pyproject.toml`: настроить `asyncio_mode = "auto"` чтобы
   не пришлось писать декоратор на каждый тест.
4. Файлы которые надо обновить:
   - `tests/test_db_client.py` — все sync → async, всю работу с db через `await`.
   - `tests/test_handlers.py` — handlers async, добавить awaits в asyncio.run.
   - `tests/test_pipelines_resume.py` — мок-патчи сохраняются, но `db.create_run`
     уже async — `await`.
   - `tests/test_auth.py`, `tests/test_state_machine.py`,
     `tests/test_extractors.py`, `tests/test_screen_runner.py`,
     `tests/test_apify_total_parse.py` — не используют db, не трогаем.
5. Удалить `data/recruiter_assistant.db` (SQLite-файл) — больше не нужен.

## Тесты

Все 90 существующих тестов должны проходить.

## Команды для верификации

```bash
# Все тесты зелёные
python -m pytest tests/ -q

# Конкретно db тесты
python -m pytest tests/test_db_client.py -v

# Pytest asyncio mode правильный
grep -E "asyncio_mode" pyproject.toml setup.cfg pytest.ini 2>/dev/null
```

## Критерии готовности

- [ ] `tests/conftest.py` существует, фикстура `db` создаёт PG-schema namespace
- [ ] `asyncio_mode = "auto"` настроен (в pytest.ini или pyproject.toml)
- [ ] Все тесты в `tests/test_db_client.py` async, проходят
- [ ] Все тесты в `tests/test_handlers.py` обновлены под async db, проходят
- [ ] Все тесты в `tests/test_pipelines_resume.py` обновлены, проходят
- [ ] `python -m pytest tests/ -q` → 90+ passed, 0 failed
- [ ] SQLite-файл `data/recruiter_assistant.db` удалён
