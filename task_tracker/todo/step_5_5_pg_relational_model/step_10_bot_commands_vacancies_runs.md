# Шаг 10: Команды бота /vacancies, /vacancy, /runs

> Зависит от: step_9
> Статус: [ ] pending

## Задача

Добавить три новые команды бота для работы с накопленными данными:
- `/vacancies` — список вакансий пользователя
- `/vacancy <id>` — карточка одной вакансии: JD, история searches, runs, статистика
- `/runs` — последние runs пользователя

## Конкретные действия

### `bot/replies.py`

Добавить шаблоны:

```python
VACANCIES_EMPTY = "У тебя пока нет вакансий. Начни через /refind_vacancy."

VACANCIES_LIST_ITEM = "#{id} {name} ({source}) — {created_at}"
VACANCIES_LIST_HEADER = "Твои вакансии:"

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

RUNS_EMPTY = "У тебя пока нет прогонов."
RUNS_LIST_HEADER = "Последние прогоны:"
RUNS_LIST_ITEM = (
    "#{id} session #{session_id} ({pipeline_type}) — "
    "{status}, found {found}, passed {passed} — {created_at}"
)
```

### `bot/handlers.py`

```python
async def cmd_vacancies(update, context):
    if not await _ensure_user(...): return
    user_id = update.effective_user.id
    vacancies = await _db(context).list_vacancies_by_user(user_id)
    if not vacancies:
        await _reply(update, replies.VACANCIES_EMPTY); return
    lines = [replies.VACANCIES_LIST_HEADER]
    for v in vacancies:
        lines.append(replies.VACANCIES_LIST_ITEM.format(
            id=v["id"], name=v["name"] or "(no name)",
            source=v["source"], created_at=v["created_at"],
        ))
    await _reply(update, "\n".join(lines))


async def cmd_vacancy(update, context):
    # parse /vacancy <id>
    args = (update.effective_message.text or "").split(maxsplit=1)
    if len(args) < 2 or not args[1].strip().lstrip("#").isdigit():
        await _reply(update, "Использование: /vacancy <id>"); return
    vid = int(args[1].strip().lstrip("#"))
    db = _db(context)
    v = await db.get_vacancy(vid)
    if v is None or v["created_by_user_id"] != update.effective_user.id:
        await _reply(update, replies.VACANCY_NOT_FOUND.format(id=vid)); return
    # Статистика
    searches = await db.list_searches_by_vacancy(vid)
    screenings = await db.list_screenings_by_vacancy(vid)
    go = sum(1 for s in screenings if s["ai_status"] == "pass")
    maybe = sum(1 for s in screenings if s["ai_status"] == "uncertain")
    skip = sum(1 for s in screenings if s["ai_status"] == "fail")
    # Количество runs — через searches → sessions → runs (или прямой запрос).
    # Простой запрос: COUNT(DISTINCT run_id) FROM candidate_screenings WHERE vacancy_id=$1
    runs_count = len({s["run_id"] for s in screenings})
    jd_preview = (v["jd_text"] or "")[:300] + ("..." if len(v["jd_text"] or "") > 300 else "")
    await _reply(update, replies.VACANCY_CARD.format(
        id=v["id"], name=v["name"], source=v["source"],
        created_at=v["created_at"], searches_count=len(searches),
        runs_count=runs_count, screenings_count=len(screenings),
        go=go, maybe=maybe, skip=skip, jd_preview=jd_preview,
    ))


async def cmd_runs(update, context):
    # Последние N (например 10) runs пользователя
    db = _db(context)
    user_id = update.effective_user.id
    rows = await db._query_all(
        "SELECT id, session_id, pipeline_type, status, found_count, passed_count, created_at "
        "FROM runs WHERE user_id = $1 ORDER BY created_at DESC LIMIT 10",
        (user_id,)
    )
    if not rows:
        await _reply(update, replies.RUNS_EMPTY); return
    lines = [replies.RUNS_LIST_HEADER]
    for r in rows:
        lines.append(replies.RUNS_LIST_ITEM.format(
            id=r["id"], session_id=r["session_id"], pipeline_type=r["pipeline_type"],
            status=r["status"], found=r["found_count"] or 0,
            passed=r["passed_count"] or 0, created_at=r["created_at"],
        ))
    await _reply(update, "\n".join(lines))
```

### `bot/main.py`

Зарегистрировать новые `CommandHandler`'ы.

### Обновить WELCOME

Добавить в `replies.WELCOME` строки про новые команды.

## Тесты

`tests/test_handlers_listing.py`:

```python
async def test_vacancies_empty(db, whitelisted): ...
async def test_vacancies_lists_only_my(db, whitelisted): ...
async def test_vacancy_card_shows_stats(db, whitelisted): ...
async def test_vacancy_not_found(db, whitelisted): ...
async def test_vacancy_access_denied_for_other_user(db, whitelisted): ...
async def test_runs_empty(db, whitelisted): ...
async def test_runs_shows_last_10(db, whitelisted): ...
```

## Команды для верификации

```bash
python -m pytest tests/test_handlers_listing.py -v
python -m pytest tests/ -q
```

## Критерии готовности

- [ ] `cmd_vacancies`, `cmd_vacancy`, `cmd_runs` существуют в handlers.py
- [ ] Зарегистрированы в main.py
- [ ] `replies.py` содержит все шаблоны
- [ ] `tests/test_handlers_listing.py` — все 7 тестов зелёные
- [ ] WELCOME упоминает новые команды
- [ ] Доступ к чужой вакансии запрещён (test_vacancy_access_denied_for_other_user)
