# Шаг 10: Команды бота /vacancies, /vacancy, /runs

> Зависит от: step_9
> Статус: [x] done (2026-06-26)
> Обновлено: 2026-06-26 (новое окно) — см. решения ниже

## Задача

Дать read-доступ к накопленным в новой реляционной модели данным +
закрыть два хвоста, которые удобно тронуть «по пути».

**Три команды (read-only):**
- `/vacancies` — список вакансий пользователя
- `/vacancy <id>` — карточка одной вакансии: JD, история searches, runs, статистика
- `/runs` — последние runs пользователя

**Плюс на этом же шаге (тронуть один раз):**
- `replies.PIPELINE_DONE` показывает `already_seen` («X из 25 уже видели на
  других вакансиях») — поле уже считается в `pipelines.py`, надо пробросить.
- Fix бага: `sessions.pending_boolean` не очищается при `/cancel` и при
  cancel предыдущей сессии в `_start_session` (см. backlog). 2 строки.

## Решения (зафиксированы 2026-06-26)

- **`/replay_search` НЕ делаем здесь** — вынесена в
  `task_tracker/backlog/step_5_backlog.md`. step_10 = ровно 3 команды.
- **Access-control:** `/vacancy <id>` и `/runs` показывают только данные
  владельца. Чужая вакансия → `VACANCY_NOT_FOUND` (same-as-404).
  `/runs` фильтрует по `user_id` на уровне SQL.
- **`cmd_runs` НЕ дёргает `db._query_all` напрямую** (инкапсуляция) —
  добавляем метод `db.list_recent_runs_by_user(user_id, limit=10)`.
- **already_seen формулировка:** «X из 25 уже видели на других вакансиях».

## Конкретные действия

### `db/client.py`

Добавить метод (рядом с `get_run` / `complete_run`):

```python
async def list_recent_runs_by_user(
    self, user_id: int, limit: int = 10
) -> list[dict]:
    return await self._query_all(
        "SELECT id, session_id, pipeline_type, status, "
        "found_count, passed_count, created_at "
        "FROM runs WHERE user_id = $1 "
        "ORDER BY created_at DESC, id DESC LIMIT $2",
        user_id, limit,
    )
```

Уже есть (проверено): `list_vacancies_by_user`, `get_vacancy`,
`list_searches_by_vacancy`, `list_screenings_by_vacancy`.

### `bot/replies.py`

Добавить шаблоны:

```python
VACANCIES_EMPTY = "У тебя пока нет вакансий. Начни через /refind_vacancy."
VACANCIES_LIST_HEADER = "Твои вакансии:"
VACANCIES_LIST_ITEM = "#{id} {name} ({source}) — {created_at}"

VACANCY_NOT_FOUND = "Вакансия #{id} не найдена."
VACANCY_CARD = (
    "Вакансия #{id}: {name}\n"
    "Источник: {source}\n"
    "Создана: {created_at}\n\n"
    "Searches (boolean'ы): {searches_count}\n"
    "Runs: {runs_count}\n"
    "Скринингов: {screenings_count}\n"
    "  GO: {go}\n"
    "  MAYBE: {maybe}\n"
    "  SKIP: {skip}\n\n"
    "JD:\n{jd_preview}"
)
VACANCY_USAGE = "Использование: /vacancy <id>"

RUNS_EMPTY = "У тебя пока нет прогонов."
RUNS_LIST_HEADER = "Последние прогоны:"
RUNS_LIST_ITEM = (
    "#{id} session #{session_id} ({pipeline_type}) — "
    "{status}, found {found}, passed {passed} — {created_at}"
)
```

Обновить `PIPELINE_DONE` — добавить строку про already_seen. Хендлер всегда
передаёт `already_seen` (0 если повторов нет — строку показываем всегда,
формулировка «X из N»):

```python
PIPELINE_DONE = (
    "✅ Готово. Сессия #{session_id}\n\n"
    "Всего найдено в Apify: {total_found}\n"
    "Взяли в работу: {found} кандидатов\n"
    "Прошли скрининг: {screened}\n"
    "GO: {go}\n"
    "MAYBE: {maybe}\n"
    "SKIP: {skip}\n"
    "Уже видели на других вакансиях: {already_seen}\n\n"
    "Подробный отчёт в файле ниже."
)
```

Обновить `WELCOME` — добавить `/vacancies`, `/vacancy <id>`, `/runs`.

### `bot/handlers.py`

- `cmd_vacancies(update, context)` — `_ensure_user`, `list_vacancies_by_user`,
  пусто → `VACANCIES_EMPTY`, иначе header + items.
- `cmd_vacancy(update, context)` — парсинг `/vacancy <id>` (strip `#`,
  `isdigit`), `get_vacancy`, access-check `created_by_user_id == user_id`
  (иначе `VACANCY_NOT_FOUND`). Статистика: `list_searches_by_vacancy`,
  `list_screenings_by_vacancy` → go/maybe/skip по `ai_status`
  (pass/uncertain/fail), `runs_count = len({s["run_id"]})`,
  `jd_preview` = первые 300 символов.
- `cmd_runs(update, context)` — `_ensure_user`,
  `list_recent_runs_by_user(user_id)`, пусто → `RUNS_EMPTY`.
- `_run_pipeline_task` — добавить `already_seen=result.get("already_seen", 0)`
  в `PIPELINE_DONE.format(...)`.
- `cmd_cancel` + `_start_session` (ветка cancel активной) — добавить
  `pending_boolean=None` в `update_session(...)`.

### `bot/main.py`

Зарегистрировать `CommandHandler`'ы: `vacancies`, `vacancy`, `runs`
(до общего `filters.COMMAND → cmd_unknown`).

## Тесты

`tests/test_handlers_listing.py`:

```python
async def test_vacancies_empty(...)
async def test_vacancies_lists_only_my(...)
async def test_vacancy_card_shows_stats(...)
async def test_vacancy_not_found(...)
async def test_vacancy_access_denied_for_other_user(...)
async def test_runs_empty(...)
async def test_runs_shows_last_10(...)
```

Плюс к существующим: тест что `cmd_cancel` обнуляет `pending_boolean`.

## Команды для верификации

```bash
python -m pytest tests/test_handlers_listing.py -v
python -m pytest tests/ -q
```

## Критерии готовности

- [ ] `cmd_vacancies`, `cmd_vacancy`, `cmd_runs` существуют в handlers.py
- [ ] `db.list_recent_runs_by_user` добавлен; `_query_all` в хендлере НЕ используется
- [ ] Зарегистрированы в main.py
- [ ] `replies.py` содержит все шаблоны; WELCOME упоминает новые команды
- [ ] `PIPELINE_DONE` показывает already_seen
- [ ] `pending_boolean` обнуляется при `/cancel` и при cancel предыдущей сессии
- [ ] Доступ к чужой вакансии запрещён (test_vacancy_access_denied_for_other_user)
- [ ] Все тесты зелёные (было 107)
