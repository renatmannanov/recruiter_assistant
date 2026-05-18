# Step 6: Интеграция с pipeline cv → jobs

> Статус: pending
> Зависит от: step_5 (паттерн обёрток обкатан на vacancy)

## Цель

То же что step_5, но для пайплайна `cv_to_jobs`. После — `/refind_candidate` end-to-end работает: CV → boolean → подтверждение → run_jobs → **`.md` отчёт юзеру в Telegram**.

## Что делаем

### 6.1 Обёртка над boolean_generator (target=jobs)

```python
async def generate_boolean_for_cv(cv_text: str, brief_text: str | None) -> tuple[str, str]:
    """
    target='jobs' — генерит boolean для поиска вакансий.
    brief_text — опциональный (предпочтения кандидата), из 2-го файла.
    """
    ...
```

Использует ту же функцию `generate_boolean()` из step_5, с `target="jobs"`. Промпт `prompts_jobs.py` импортируется в `generator.py` (строки 37-40), используется при `target="jobs"`.

Brief в cv→jobs описывает **что хочет кандидат** (preferences, не requirements вакансии). Например: "Только EU remote, не американские стартапы, Python+ML обязательно".

### 6.1a Рефакторинг `cv_parser.parse_cv()` — принимать текст, не путь

**Текущее состояние:** `core/candidate_screener/core/cv_parser.py:36` делает `Path(cv_path).read_text(...)` — принимает только путь.

**Проблема:** в боте `cv_text` приходит строкой из Telegram, файла на диске нет.

**Что делаем:** добавить параметр `cv_text`:

```python
def parse_cv(
    cv_path: str | Path | None = None,
    *,
    cv_text: str | None = None,
    client: ...,
    model: ...
) -> dict:
    if cv_text is None:
        if cv_path is None:
            raise ValueError("Either cv_path or cv_text must be provided")
        cv_text = Path(cv_path).read_text(encoding="utf-8").strip()
    # ... дальше как сейчас
```

CLI и старые места вызова продолжают работать (передают `cv_path`). Бот передаёт `cv_text=...`.

Smoke test: `python -m core.candidate_screener.cli.run_jobs --candidate test_python ...` (файловый CV) — работает как раньше.

### 6.2 Обёртка над run_jobs

Сейчас `core/candidate_screener/cli/run_jobs.py` — оркестратор: парсит CV → Apify LinkedIn Jobs Scraper → screen каждой вакансии → архивирует в `candidates/<name>/runs/<timestamp>/`.

Нужна функция — **результат markdown, без Notion**:

```python
async def run_jobs(
    boolean: str,
    cv_text: str,
    user_id: int,
    session_id: int,
    locations: list[str] = None,    # None → auto-detect из CV
    experience: str = None,         # None → auto-detect из CV
    count: int = 10
) -> dict:
    """
    Возвращает {
        "raw_apify_path": "data/sessions/<id>/raw_apify.json",
        "screening_json": [...],
        "vacancies": [...],
        "report_md": "...",        # markdown-отчёт (как существующий jobs_results.md)
        "found_count": N,
        "screened_count": N,
        "passed_count": M,
        "cost_usd": ...
    }
    """
    ...
```

> Архивацию в `candidates/<name>/runs/<timestamp>/` оставляем для CLI-флоу. В bot-флоу артефакты идут в `data/sessions/<id>/` — отчёт `report.md` бот отправляет в TG.

### 6.3 Auto-detect locations и experience

`run_jobs.py` сейчас: locations из CLI `--locations` или из CV; experience из CLI или из CV (`cv_parser.derive_seniority`).

В TG-флоу CLI-флагов нет. **Решение: всегда auto-detect** из CV. Если юзер хочет другие локации — редактирует boolean в `WAITING_BOOLEAN_CONFIRM` (туда зашиты location keywords).

Fallback если auto-detect не сработал: `locations=["Germany", "Netherlands"]`, `experience="senior"`. Логируем warning в `run.error_text` или отдельное поле.

### 6.4 Вывод результата — markdown-отчёт (НЕ Notion)

В v1 **нет Notion**. Результат `cv_to_jobs` — `.md` файл, как сейчас CLI кладёт `jobs_results.md` (вот этот файл и так уже существует).

**Что делаем:**
1. `run_jobs(...)` возвращает `report_md` — переиспользуем существующий markdown-генератор `jobs_results.md`
2. Записать в `data/sessions/<session_id>/report.md`
3. Путь → `sessions.report_path`, текст → `runs.report_md`
4. Бот отправляет файл юзеру в Telegram вложением

> Так как `jobs_results.md` уже генерится в текущем CLI — здесь работы меньше чем в step_5: markdown-генератор для вакансий уже есть, нужно только убедиться что он вынесен в функцию (не зашит намертво в CLI-оркестратор).

### 6.5 Полный flow cv_to_jobs

Аналогично step_5.6, но:
- `discover_candidates` → `run_jobs`
- Сохраняем в `vacancies_found` вместо `candidates_found` (`db.insert_vacancies`)
- dedup через `db.is_vacancy_known(user_id, linkedin_url)`
- отчёт `report.md` → в TG файлом

## Критерии готовности

- [ ] Рефакторинг `cv_parser.parse_cv()`: принимает `cv_text` (kwarg-only) дополнительно к `cv_path`
- [ ] Smoke test: `python -m core.candidate_screener.cli.run_jobs --candidate test_python ...` с файловым CV работает как раньше
- [ ] Рефакторинг `cli/run_jobs.py`: бизнес-логика → функция `run_jobs(boolean, cv_text, ...)`, результат — markdown (НЕ Notion)
- [ ] markdown-генератор `jobs_results.md` вынесен в функцию, переиспользуется
- [ ] Auto-detect locations + experience из CV работает
- [ ] Fallback на дефолты если CV не парсится (`locations=["Germany","Netherlands"]`, `experience="senior"`, warning логируется)
- [ ] `bot/pipelines.py` реализует `run_cv_pipeline(session_id)` end-to-end
- [ ] Dedup vacancies против SQLite (по linkedin_url вакансии)
- [ ] Сырой Apify dump → `data/sessions/<id>/raw_apify.json`, в БД путь
- [ ] Локальный e2e тест: `/refind_candidate` + реальный CV → boolean (с правкой) → "ок" → реальный Apify → `report.md` приходит файлом в TG
- [ ] Ручные прогоны через CLI работают после рефакторинга (smoke test обоих пайплайнов)
