# Шаг 9: bot/pipelines.py — переключить на новую модель

> Зависит от: step_8
> Статус: [ ] pending

## Задача

Адаптировать `bot/pipelines.py` под новую модель: vacancy → search → run →
candidate_screenings (через upsert_candidate в candidates). Старые
`db.insert_candidates` / `db.is_candidate_known` / `session.input_text` —
больше нет.

`bot/handlers.py` тоже трогаем — текст JD теперь надо положить в новую
vacancy (создаваемую при `/refind_vacancy`), а не в `session.input_text`.

## Конкретные действия

### `bot/handlers.py`

`_generate_boolean_and_advance`:
- Раньше: записывал input_text/brief_text/boolean_text_original в session.
- Теперь:
  1. Создать vacancy через `db.create_vacancy(name=f"vacancy_{session_id}", jd_text=input_text, brief_text=brief_text, source='manual', created_by_user_id=user_id)` → получить vacancy_id.
  2. Сгенерить boolean (как раньше).
  3. Записать `db.update_session(session_id, vacancy_id=vacancy_id)`.
  4. Boolean — в локальную переменную чтобы дальше создать search, **но
     отправить юзеру**. Сам boolean пока в БД не лежит — он попадёт в
     `searches` после подтверждения юзером.
  5. Поскольку handler перешёл из `WAITING_INPUT` в `WAITING_BOOLEAN_CONFIRM`,
     и нам нужно как-то донести `boolean_text` до следующего шага — храним
     в `application.bot_data` мапу `_pending_boolean[user_id] = boolean` или
     добавляем поле в БД. **Решение:** поле в БД, временная колонка
     `sessions.pending_boolean TEXT` (миграция 003) или вернуть
     `boolean_text` обратно в sessions как `pending_boolean`. См. дискуссию
     ниже.

**Развилка с pending_boolean — фиксируем выбор:**

Возвращаем колонку `sessions.pending_boolean TEXT` (можно не миграцию 003,
а добавить в 002 миграцию заранее, обновив step_7 — этот шаг это уточняет).
Цель: handler сохраняет boolean в session до подтверждения, при `ок` мы
создаём `searches` со значением, после `ок` колонка очищается.

Альтернативу (in-memory dict) отклоняем: при рестарте бота юзер потеряет
текущую сессию посреди подтверждения.

**Корректирующая правка к step_7:** добавить в миграцию 002
`ALTER TABLE sessions ADD COLUMN pending_boolean TEXT;` и добавить
`pending_boolean` в `_COLUMNS["sessions"]` в step_8.

После выбора boolean (ветка `WAITING_BOOLEAN_CONFIRM` в `on_text`):
1. Создать `searches`:
   ```python
   search_id = await db.create_search(
       vacancy_id=session["vacancy_id"],
       boolean_text=boolean,
       original_boolean=session["pending_boolean"],
       created_by_user_id=user_id,
   )
   ```
2. `await db.update_session(session_id, search_id=search_id, pending_boolean=None, step='running')`.

### `bot/pipelines.py`

`_run_vacancy_pipeline`:
1. `session = await db.get_session(session_id)` — session содержит
   `vacancy_id`, `search_id`, **но не** boolean. Boolean берём через
   `await db.get_search(session["search_id"])` → `boolean_text`.
2. Vacancy для screening: `vacancy = await db.get_vacancy(session["vacancy_id"])`
   → `jd_text` для prompt, `brief_text` опциональный.
3. Discover (или resume) — без изменений.
4. **Dedup** — был `db.is_candidate_known(user_id, url)`. Теперь:
   `await db.is_candidate_known_to_user(user_id, url)`. Логика идентична.
5. **Запись результата** — был `db.insert_candidates(run_id, user_id, db_rows)`.
   Теперь для каждого результата:
   - `cand_id = await db.upsert_candidate(raw_profile)` — глобальная база
   - `await db.create_screening(candidate_id=cand_id, vacancy_id=session["vacancy_id"], run_id=run_id, user_id=user_id, ai_status=..., ai_score=..., ai_comment=...)`

### Обновить `_compact_result`

Не меняем. Сохранение `screening_json` в `runs` — для аналитики, остаётся.

## Тесты

- `tests/test_pipelines_resume.py` — обновить моки: убрать `db.insert_candidates`,
  добавить `db.upsert_candidate` и `db.create_screening`.
- Новый тест `tests/test_pipelines_new_model.py`:
  ```python
  async def test_run_creates_vacancy_search_candidates_screenings(db, mocked_apify_openai): ...
  async def test_dedup_via_screenings_join(db): ...
  ```

## Команды для верификации

```bash
python -m pytest tests/ -q
python -m bot.main &  # smoke startup
```

## Критерии готовности

- [ ] `bot/handlers.py:_generate_boolean_and_advance` создаёт vacancy, сохраняет boolean в `pending_boolean`
- [ ] `bot/handlers.py` на confirm создаёт `searches` и заполняет `sessions.search_id`
- [ ] `bot/pipelines.py:_run_vacancy_pipeline` использует `upsert_candidate` + `create_screening` вместо `insert_candidates`
- [ ] Dedup через `is_candidate_known_to_user`
- [ ] `tests/test_pipelines_resume.py` обновлён и проходит
- [ ] `tests/test_pipelines_new_model.py` создан, минимум 2 теста, оба зелёные
- [ ] `python -m pytest tests/ -q` зелёные
- [ ] Бот запускается без ошибок
