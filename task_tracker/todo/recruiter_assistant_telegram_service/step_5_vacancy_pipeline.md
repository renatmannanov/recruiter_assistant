# Step 5: Интеграция с pipeline vacancy → candidates

> Статус: pending
> Зависит от: step_4 (bot scaffold с stub'ами)

## Цель

Заменить stub'ы для пайплайна `vacancy_to_candidates` на реальные вызовы `core/`. После этого `/refind_vacancy` end-to-end работает: текст/файл(ы) JD → boolean → подтверждение → discover → screening → **`.md` отчёт юзеру в Telegram**.

## Что делаем

### 5.1 Обёртка над boolean_generator

```python
# bot/pipelines.py
from core.boolean_generator import generator as bool_gen

async def generate_boolean_for_vacancy(vacancy_text: str, brief_text: str | None) -> tuple[str, str]:
    """
    Возвращает (boolean_string, full_markdown_with_reasoning).
    boolean_string — показываем юзеру и сохраняем.
    brief_text — опциональный (из 2-го файла или None).
    """
    ...
```

**Проблема:** текущий `generator.py` читает файл с диска. Нам нужно передавать текст из памяти.

**Решение:** добавить в `core/boolean_generator/generator.py` функцию `generate_boolean(vacancy_text: str, brief_text: str = None, target: str = "candidates") -> dict` — без файлового I/O. CLI оставить как есть (дёргает эту функцию после чтения файла). Это **не ломает** ручные прогоны.

Примечание: функция `generate_boolean_search()` уже существует (строки 87-149) — нужен thin wrapper для приёма текста вместо пути.

> Fallback если рефакторить страшно: писать текст во временный файл `data/sessions/<id>/vacancy.md`, дёргать CLI через subprocess. Грязно, но работает. Решение по стратегии рефакторинга — зафиксировано в начале работы (см. PLAN.md / диалог с Ренатом).

### 5.2 Обёртка над discover

Сейчас `core/candidate_screener/cli/discover.py` принимает `--config <path>`, `--vacancy`, читает boolean из `clients/<client>/<vacancy>/boolean.md`, дедупит через Notion.

Нужна функция:

```python
async def discover_candidates(boolean: str, user_id: int, session_id: int) -> dict:
    """
    Запускает Apify discover. Возвращает {
        "raw_apify_path": "data/sessions/<id>/raw_apify.json",  # сырой dump на диск
        "candidates": [...],   # parsed list
        "found_count": N,
        "cost_usd": 0.20
    }
    """
    ...
```

Рефактор `discover.py`: вынести бизнес-логику из CLI в функцию `discover(boolean: str, dedup_strategy: str = "none") -> dict`. CLI — тонкая обёртка.

**Dedup — SQLite-only для bot-флоу:**
1. Ядро `discover(boolean)` возвращает **сырой** результат Apify без dedup
2. Dedup делается **после** возврата, в `bot/pipelines.py` через SQLite:
   ```python
   raw = await core_discover(boolean)
   new_candidates = [c for c in raw["candidates"]
                     if not db.is_candidate_known(user_id, c["linkedin_url"])]
   ```
3. **Notion-dedup в `core/discover.py` остаётся для CLI-флоу** — через параметр `dedup_strategy="notion"` (default для CLI) или `"none"` (для бота). Бот никогда не вызывает Notion.

**Сырой Apify dump:** пишется файлом на диск (`data/sessions/<id>/raw_apify.json`), в БД — только путь `raw_apify_path`. БД остаётся компактной.

**Cost учёт:** функции source-слоя сейчас не возвращают `cost_usd`. Добавить расчёт cost внутри (Apify API даёт стоимость в response) — полезно для аналитики.

### 5.3 Обёртка над screening

Сейчас `cli/run_local.py` берёт JSON-файл с профилями, читает vacancy.md и brief.md, дёргает OpenAI, пишет результаты **в Notion**.

Нужна функция — **без Notion, результат в markdown**:

```python
async def screen_candidates(
    candidates: list[dict],     # raw Apify profiles
    vacancy_text: str,          # JD из session.input_text
    brief_text: str | None,     # опциональный brief
    user_id: int,
    session_id: int,
) -> dict:
    """
    Возвращает {
        "screening_json": [...],   # результаты по каждому кандидату
        "candidates": [...],       # с проставленными ai_status/ai_score/ai_comment
        "screened_count": N,
        "passed_count": M,
        "report_md": "...",        # markdown-отчёт (как сейчас jobs_results.md)
        "cost_usd": 0.30
    }
    """
    ...
```

Рефактор `run_local.py`: бизнес-логика → функция, CLI → обёртка. **Notion-sink из bot-флоу не вызывается** — вместо него генерится markdown-отчёт.

### 5.4 Вывод результата — markdown-отчёт (НЕ Notion)

В v1 **нет Notion**. Результат прогона — `.md` файл, как сейчас CLI кладёт report.

**Что делаем:**
1. После screening собрать markdown-отчёт (формат — как существующий `jobs_results.md` / report кандидатов: список кандидатов, AI Status/Score/Comment, ссылки на LinkedIn)
2. Записать в `data/sessions/<session_id>/report.md`
3. Путь сохранить в `sessions.report_path` и `runs.report_md` (дубль текста в БД для аналитики)
4. Бот отправляет файл `report.md` юзеру в Telegram вложением (`send_document`)

> Существующий markdown-генератор отчёта в `core/candidate_screener/` переиспользуем. Если он сейчас зашит в CLI или в Notion-sink — выносим в отдельную функцию `render_report_md(candidates, vacancy_text) -> str`. Notion-sink не трогаем (остаётся для CLI-ручных прогонов).

### 5.5 brief — приходит файлом, передаётся как есть

Brief приходит 2-м файлом (см. step_4 extractors), сохраняется в `session.brief_text`. Передаётся в boolean_generator и screening **как свободный текст** — не парсим структурированно, LLM разбирается сам (старая логика CLI это умеет).

### 5.6 Полный flow vacancy_to_candidates

```python
async def run_vacancy_pipeline(session_id: int):
    db = DB(...)
    session = db.get_session(session_id)
    run_id = db.create_run(session_id, session.user_id, "vacancy_to_candidates")
    start = time.time()
    try:
        # 1. Discover
        discover_result = await discover_candidates(
            boolean=session.boolean_text, user_id=session.user_id, session_id=session_id)
        db.update_run(run_id,
            raw_apify_path=discover_result["raw_apify_path"],
            found_count=discover_result["found_count"])

        # 2. Dedup против SQLite
        new_candidates = [c for c in discover_result["candidates"]
                          if not db.is_candidate_known(session.user_id, c["linkedin_url"])]

        # 3. Screening (генерит markdown-отчёт, без Notion)
        screening_result = await screen_candidates(
            candidates=new_candidates,
            vacancy_text=session.input_text,
            brief_text=session.brief_text,
            user_id=session.user_id, session_id=session_id)

        # 4. Сохранить кандидатов в SQLite
        db.insert_candidates(run_id, session.user_id, screening_result["candidates"])

        # 5. Записать отчёт на диск
        report_path = f"data/sessions/{session_id}/report.md"
        Path(report_path).parent.mkdir(parents=True, exist_ok=True)
        Path(report_path).write_text(screening_result["report_md"], encoding="utf-8")

        # 6. Завершить run + session
        db.update_run(run_id, screening_json=..., report_md=screening_result["report_md"])
        db.complete_run(run_id, found_count=..., screened_count=..., passed_count=...,
                        cost_usd=discover_result["cost_usd"] + screening_result["cost_usd"],
                        duration_sec=time.time() - start)
        db.complete_session(session_id, report_path=report_path)

        # 7. Отправить юзеру: текст-резюме + report.md файлом
        await tg_send_pipeline_done(session.user_id, session_id, report_path, ...)

    except Exception as e:
        db.fail_session(session_id, error_text=str(e))
        db.fail_run(run_id, error_text=str(e))
        await tg_send_pipeline_failed(session.user_id, session_id, str(e))
```

## Критерии готовности

- [ ] Рефакторинг `core/boolean_generator/generator.py`: функция `generate_boolean(text, brief, target)` без файлового I/O, CLI обёрнут вокруг неё
- [ ] Рефакторинг `core/candidate_screener/cli/discover.py`: бизнес-логика → `discover(boolean, dedup_strategy="none")` без обязательной зависимости от config.yaml
- [ ] Рефакторинг `core/candidate_screener/cli/run_local.py`: бизнес-логика → `screen_candidates(...)`, результат — markdown-отчёт (НЕ Notion)
- [ ] Функция `render_report_md(...)` генерит markdown-отчёт (формат как существующий report кандидатов)
- [ ] `from_apify_search.py`: `search_linkedin_profiles()` возвращает `cost_usd`
- [ ] `bot/pipelines.py` реализует `run_vacancy_pipeline(session_id)` end-to-end
- [ ] Сырой Apify dump пишется в `data/sessions/<id>/raw_apify.json`, в БД — путь
- [ ] Dedup через SQLite работает: повторный прогон с тем же boolean не создаёт дубли (тест: дважды подряд → второй раз 0 новых)
- [ ] Notion-dedup и Notion-sink **не вызываются** из bot-флоу
- [ ] Notion-функции в `core/` **не сломаны** — ручные CLI-прогоны через config.yaml работают как раньше
- [ ] Локальный e2e тест 1 (без brief): `/refind_vacancy` + реальная JD текстом → boolean → "ок" → реальный Apify (`--limit 3`) → `report.md` приходит файлом в TG
- [ ] Локальный e2e тест 2 (с brief): `/refind_vacancy` + vacancy.md + brief.md (2 файла) → boolean содержит location anchors → "ок" → прогон → отчёт релевантнее
- [ ] **Ручные прогоны через CLI всё ещё работают** (smoke test обоих пайплайнов после рефакторинга)
- [ ] cost_usd и duration_sec корректно посчитаны и записаны в run
