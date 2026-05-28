# Шаг 11: Команды бота /candidate, /rescreen, /replay_search

> Зависит от: step_10
> Статус: [ ] pending

## Задача

Добавить команды для работы с кандидатами:
- `/candidate <linkedin_url или id>` — карточка кандидата с историей скринингов
- `/rescreen <run_id> <new_vacancy_id>` — прогнать кандидатов из прошлого run на новой вакансии (без Apify)
- `/replay_search <search_id>` — повторить тот же boolean (новый Apify run)

Это ключевые фичи новой модели — позволяют переиспользовать данные.

## Конкретные действия

### `bot/replies.py`

```python
CANDIDATE_NOT_FOUND = "Кандидат '{key}' не найден или ты его не видел."

CANDIDATE_CARD = (
    "Кандидат #{id}: {name}\n"
    "LinkedIn: {linkedin_url}\n"
    "Headline: {headline}\n"
    "Location: {location}\n\n"
    "Скринингов по разным вакансиям: {count}\n"
    "{screenings_block}"
)

CANDIDATE_SCREENING_LINE = (
    "  vacancy #{vacancy_id} — {ai_status} ({ai_score}/10) — {created_at}"
)

RESCREEN_USAGE = "Использование: /rescreen <run_id> <new_vacancy_id>"
RESCREEN_RUN_NOT_FOUND = "Run #{run_id} не найден или это не твой run."
RESCREEN_VACANCY_NOT_FOUND = "Вакансия #{vacancy_id} не найдена."
RESCREEN_NO_CANDIDATES = "В run #{run_id} нет кандидатов для повторного прогона."
RESCREEN_STARTED = (
    "Запускаю rescreen: {count} кандидатов из run #{run_id} → "
    "vacancy #{vacancy_id}. Apify не вызывается, только OpenAI."
)

REPLAY_SEARCH_USAGE = "Использование: /replay_search <search_id>"
REPLAY_SEARCH_NOT_FOUND = "Search #{search_id} не найден или ты его не создавал."
REPLAY_SEARCH_STARTED = (
    "Запускаю replay search #{search_id} (boolean от vacancy #{vacancy_id}). "
    "Apify вызывается заново."
)
```

### `bot/handlers.py`

```python
async def cmd_candidate(update, context):
    args = (update.effective_message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await _reply(update, "Использование: /candidate <linkedin_url или id>"); return
    key = args[1].strip()
    db = _db(context)
    user_id = update.effective_user.id

    # Либо linkedin_url, либо int id
    cand = None
    if key.isdigit():
        cand = await db.get_candidate(int(key))
    elif key.startswith("http"):
        cand = await db.get_candidate_by_url(key)
    if cand is None:
        await _reply(update, replies.CANDIDATE_NOT_FOUND.format(key=key)); return

    # Авторизация: юзер видел этого кандидата?
    if not await db.is_candidate_known_to_user(user_id, cand["linkedin_url"]):
        await _reply(update, replies.CANDIDATE_NOT_FOUND.format(key=key)); return

    screenings = await db.list_screenings_by_candidate(cand["id"])
    # Только то, что видел этот юзер
    mine = [s for s in screenings if s["user_id"] == user_id]
    lines = [replies.CANDIDATE_SCREENING_LINE.format(**s) for s in mine]
    await _reply(update, replies.CANDIDATE_CARD.format(
        id=cand["id"], name=cand["name"], linkedin_url=cand["linkedin_url"],
        headline=cand["headline"], location=cand["location"],
        count=len(mine), screenings_block="\n".join(lines) or "  (нет)",
    ))


async def cmd_rescreen(update, context):
    """Прогнать кандидатов из прошлого run на новой вакансии — без Apify."""
    args = (update.effective_message.text or "").split()
    if len(args) != 3 or not args[1].isdigit() or not args[2].isdigit():
        await _reply(update, replies.RESCREEN_USAGE); return
    run_id, vacancy_id = int(args[1]), int(args[2])
    db = _db(context)
    user_id = update.effective_user.id

    run = await db.get_run(run_id)
    if run is None or run["user_id"] != user_id:
        await _reply(update, replies.RESCREEN_RUN_NOT_FOUND.format(run_id=run_id)); return

    vacancy = await db.get_vacancy(vacancy_id)
    if vacancy is None or vacancy["created_by_user_id"] != user_id:
        await _reply(update, replies.RESCREEN_VACANCY_NOT_FOUND.format(vacancy_id=vacancy_id)); return

    # Берём кандидатов из старого run через screenings
    old_screenings = await db.list_screenings_by_run(run_id)
    if not old_screenings:
        await _reply(update, replies.RESCREEN_NO_CANDIDATES.format(run_id=run_id)); return

    candidate_ids = [s["candidate_id"] for s in old_screenings]

    await _reply(update, replies.RESCREEN_STARTED.format(
        count=len(candidate_ids), run_id=run_id, vacancy_id=vacancy_id,
    ))

    # Запустить screening через core/screen_runner с raw_profile_json из БД
    # Подробности — в bot/pipelines.py:run_rescreen_pipeline(...) (новая функция)
    asyncio.create_task(_run_rescreen_task(
        context, user_id=user_id, candidate_ids=candidate_ids,
        vacancy_id=vacancy_id,
    ))


async def _run_rescreen_task(context, *, user_id, candidate_ids, vacancy_id):
    # Создаём session + run для нового screening'а
    db = _db(context)
    session_id = await db.create_session(user_id, "vacancy_to_candidates")
    await db.update_session(session_id, vacancy_id=vacancy_id, step="running")
    run_id = await db.create_run(session_id, user_id, "vacancy_to_candidates")
    try:
        # См. новую функцию pipelines.run_rescreen(...)
        result = await pipelines.run_rescreen(
            session_id=session_id, run_id=run_id, db=db,
            candidate_ids=candidate_ids, vacancy_id=vacancy_id, user_id=user_id,
        )
        await db.complete_run(run_id,
            found_count=result["found"], screened_count=result["screened"],
            passed_count=result["passed"], cost_usd=result["cost_usd"],
            duration_sec=result["duration_sec"],
        )
        await db.complete_session(session_id, result["report_path"])
        # Отправка отчёта (как обычно)
    except Exception as e:
        await db.fail_run(run_id, str(e))
        await db.fail_session(session_id, str(e))


async def cmd_replay_search(update, context):
    """Повторить тот же boolean — новый Apify прогон."""
    args = (update.effective_message.text or "").split()
    if len(args) != 2 or not args[1].isdigit():
        await _reply(update, replies.REPLAY_SEARCH_USAGE); return
    search_id = int(args[1])
    db = _db(context)
    user_id = update.effective_user.id

    search = await db.get_search(search_id)
    if search is None or search["created_by_user_id"] != user_id:
        await _reply(update, replies.REPLAY_SEARCH_NOT_FOUND.format(search_id=search_id)); return

    await _reply(update, replies.REPLAY_SEARCH_STARTED.format(
        search_id=search_id, vacancy_id=search["vacancy_id"],
    ))

    # Создаём новую session, привязанную к той же vacancy и search
    session_id = await db.create_session(user_id, "vacancy_to_candidates")
    await db.update_session(session_id, vacancy_id=search["vacancy_id"],
                             search_id=search_id, step="running")
    run_id = await db.create_run(session_id, user_id, "vacancy_to_candidates")

    # Запустить штатный _run_vacancy_pipeline — он подхватит boolean из search
    asyncio.create_task(_run_pipeline_task(
        context, session_id=session_id, chat_id=update.effective_chat.id,
        pipeline_type="vacancy_to_candidates",
    ))
```

### `bot/pipelines.py`

Добавить `run_rescreen(session_id, run_id, db, candidate_ids, vacancy_id, user_id)`:

```python
async def run_rescreen(*, session_id, run_id, db, candidate_ids, vacancy_id, user_id):
    """Прогон существующих кандидатов на новой вакансии. Без Apify."""
    started_at = time.monotonic()
    vacancy = await db.get_vacancy(vacancy_id)

    # Собрать raw profiles из БД
    profiles = []
    for cid in candidate_ids:
        cand = await db.get_candidate(cid)
        if cand and cand["raw_profile_json"]:
            profiles.append(cand["raw_profile_json"])  # JSONB → dict в asyncpg

    openai_client = _new_openai_client()
    screening = await asyncio.to_thread(
        screen_candidates, client=openai_client,
        profiles=profiles, vacancy_text=vacancy["jd_text"] or "",
        brief_text=vacancy["brief_text"], vacancy_name=f"rescreen_v{vacancy_id}",
    )

    # Создать screenings (НЕ upsert_candidate — они уже в БД)
    for cid, result in zip(candidate_ids, screening["results"]):
        await db.create_screening(
            candidate_id=cid, vacancy_id=vacancy_id, run_id=run_id,
            user_id=user_id, ai_status=_ai_status(result["recommendation"]),
            ai_score=result["score"], ai_comment=result["evaluation"],
        )

    # Записать report.md
    sess_dir = _session_dir("./data", session_id)
    report_path = sess_dir / "report.md"
    report_path.write_text(screening["report_md"], encoding="utf-8")

    return {
        "found": len(profiles), "screened": screening["screened_count"],
        "passed": screening["passed_count"],
        "go": screening["go_count"], "maybe": screening["maybe_count"],
        "skip": screening["skip_count"],
        "report_path": str(report_path),
        "cost_usd": screening["cost_usd"],
        "duration_sec": time.monotonic() - started_at,
    }
```

### `bot/main.py`

Зарегистрировать `cmd_candidate`, `cmd_rescreen`, `cmd_replay_search`.

## Тесты

`tests/test_handlers_advanced.py`:

```python
async def test_candidate_card_shows_only_my_screenings(db, whitelisted): ...
async def test_candidate_not_found_when_other_user_saw(db, whitelisted): ...
async def test_rescreen_runs_without_apify(db, whitelisted, monkeypatch): ...
async def test_rescreen_access_denied_for_other_user(db, whitelisted): ...
async def test_replay_search_creates_new_session_same_boolean(db, whitelisted, monkeypatch): ...
```

## Команды для верификации

```bash
python -m pytest tests/test_handlers_advanced.py -v
python -m pytest tests/ -q
```

## Критерии готовности

- [ ] `cmd_candidate`, `cmd_rescreen`, `cmd_replay_search` существуют и зарегистрированы
- [ ] `bot/pipelines.py:run_rescreen` реализован
- [ ] Доступ к чужим данным запрещён (тесты test_*_access_denied_*)
- [ ] `tests/test_handlers_advanced.py` — все 5 тестов зелёные
- [ ] `python -m pytest tests/ -q` зелёные
