# Шаг 4: Адаптировать bot/* под async DB

> Зависит от: step_3
> Статус: [x] done (2026-05-28)

## Задача

Переключить `bot/main.py`, `bot/handlers.py`, `bot/pipelines.py` на async
`db.*` методы. Везде где раньше был sync-вызов — добавить `await`.

## Конкретные действия

### `bot/main.py`

1. Заменить `DB(path)` на `await DB.connect()`.
2. Создание DB переносим в async setup-фазу (после `Application.builder()`).
   Python-telegram-bot 21 поддерживает `post_init` async callback:
   ```python
   async def _post_init(app):
       db = await DB.connect()
       await db.initialize_from_schema()  # если БД пустая
       await db.apply_migrations()
       app.bot_data["db"] = db

   async def _post_shutdown(app):
       db = app.bot_data.get("db")
       if db:
           await db.close()

   app = ApplicationBuilder().token(...).post_init(_post_init).post_shutdown(_post_shutdown).build()
   ```
3. cleanup_stale_sessions при старте — внутри `_post_init`, после init.

### `bot/handlers.py`

Каждое место с `_db(context).xxx(...)` — добавить `await`:
- `_ensure_user` — `await`
- `cmd_start`, `cmd_refind_*`, `cmd_cancel`, `cmd_status`, `cmd_unknown` — async уже, добавить awaits
- `on_text`, `on_document`, `_flush_media_group`, `_process_files` — async, добавить awaits
- `_generate_boolean_and_advance` — async, добавить awaits
- `_run_pipeline_task` — async, добавить awaits для `db.create_run`,
  `db.complete_run`, `db.fail_run`, `db.complete_session`, `db.fail_session`.

### `bot/pipelines.py`

В `_run_vacancy_pipeline`:
- `db.get_session(session_id)` → `await db.get_session(session_id)`
- `db.is_candidate_known(...)` → `await db.is_candidate_known(...)`
- `db.insert_candidates(...)` → `await db.insert_candidates(...)`
- `db.update_run(...)` → `await db.update_run(...)`

### `bot/auth.py`

Не зависит от db — не трогаем.

## Тесты

- Юнит-тесты пока в SQLite-формате, починим на step_5 (сейчас могут падать —
  ОК).
- Smoke-тест через запуск бота:
  ```bash
  python -m bot.main
  # ожидаем "Application started" в логе
  ```

## Команды для верификации

```bash
# Бот стартует без ошибок
python -m bot.main 2>&1 | head -10
# должно содержать "recruiter_assistant bot starting" + "Application started"

# Нет осталась-sync-вызовов
grep -E "^\s+[^a-z]*(?:db|self)\._?[a-z]+\(" bot/handlers.py bot/pipelines.py | grep -v "await " | grep -E "(db|self)\.(get_|create_|update_|complete_|fail_|insert_|is_|upsert_|cleanup_)"
# вывод должен быть пустым
```

## Критерии готовности

- [ ] `bot/main.py` использует `await DB.connect()` через `post_init` callback
- [ ] Во всех handlers'ах любой вызов db-метода обёрнут в `await`
- [ ] Во всех pipelines'ах любой вызов db-метода обёрнут в `await`
- [ ] `python -m bot.main` стартует без ошибок до строки "Application started"
- [ ] Юнит-тесты пока не трогаем — фикстура переключится на step_5
