# Шаг 8: db/client.py — CRUD методы для новой модели

> Зависит от: step_7
> Статус: [ ] pending

## Задача

Расширить `db/client.py` методами для работы с companies / vacancies /
candidates / searches / candidate_screenings. Адаптировать существующие
методы для sessions (без полей input_text/brief_text/boolean_text*).
Удалить методы `insert_candidates` / `insert_vacancies` /
`is_candidate_known` / `is_vacancy_known` — их заменяют новые через JOIN.

## Конкретные действия

### Companies

```python
async def get_or_create_company(self, name: str) -> int  # returns id
async def get_company(self, company_id: int) -> dict | None
async def list_companies(self) -> list[dict]
```

### Vacancies

```python
async def create_vacancy(self, *, name, jd_text=None, brief_text=None,
                          source, company_id=None, linkedin_url=None,
                          title=None, location=None, seniority=None,
                          created_by_user_id=None,
                          discovered_in_run_id=None) -> int

async def get_vacancy(self, vacancy_id: int) -> dict | None

async def list_vacancies_by_user(self, user_id: int,
                                  source: str | None = None) -> list[dict]
# source filter: None (все) | 'manual' | 'apify_job_search'
```

### Candidates (глобальный справочник)

```python
async def upsert_candidate(self, raw_profile: dict) -> int
# - извлекает linkedin_url, name, headline, location, about из raw_profile
# - INSERT ... ON CONFLICT (linkedin_url) DO UPDATE
#   SET raw_profile_json = EXCLUDED.raw_profile_json,
#       last_seen_at = now(), updated_at = now()
# - возвращает id

async def get_candidate(self, candidate_id: int) -> dict | None
async def get_candidate_by_url(self, linkedin_url: str) -> dict | None
```

### Searches

```python
async def create_search(self, *, vacancy_id, boolean_text,
                         original_boolean=None,
                         created_by_user_id) -> int

async def get_search(self, search_id: int) -> dict | None
async def list_searches_by_vacancy(self, vacancy_id: int) -> list[dict]
```

### Candidate screenings

```python
async def create_screening(self, *, candidate_id, vacancy_id, run_id,
                            user_id, ai_status, ai_score,
                            ai_comment) -> int
# INSERT ... ON CONFLICT (candidate_id, vacancy_id, run_id) DO NOTHING
# (на случай retry; вернёт id существующей)

async def list_screenings_by_candidate(self, candidate_id: int) -> list[dict]
async def list_screenings_by_vacancy(self, vacancy_id: int) -> list[dict]
async def list_screenings_by_run(self, run_id: int) -> list[dict]

async def is_candidate_known_to_user(self, user_id: int,
                                      linkedin_url: str) -> bool
# JOIN на candidates + candidate_screenings:
# SELECT 1 FROM candidates c
# JOIN candidate_screenings s ON s.candidate_id = c.id
# WHERE c.linkedin_url = $1 AND s.user_id = $2 LIMIT 1
```

### Sessions (адаптация)

- Из `_COLUMNS["sessions"]` убрать: `input_text`, `brief_text`, `boolean_text`,
  `boolean_text_original`.
- Добавить: `vacancy_id`, `search_id`.
- Метод `create_session(user_id, pipeline_type)` остаётся без изменений —
  vacancy_id/search_id заполнятся позже через update_session.

### Удалить

- `insert_candidates`, `insert_vacancies`, `is_candidate_known`, `is_vacancy_known`
  — они работают с `candidates_found`/`vacancies_found`, которые DROP'нуты.

### Не трогать

- `get_user`, `upsert_user`, `create_session`, `get_session`,
  `get_active_session`, `update_session`, `complete_session`, `fail_session`,
  `cleanup_stale_sessions`,
- `create_run`, `get_run`, `update_run`, `complete_run`, `fail_run`,
- `initialize_from_schema`, `apply_migrations`, `_guard_columns`, и т.д.

## Тесты

Создать `tests/test_db_relational.py`:

```python
async def test_upsert_candidate_returns_same_id_for_same_url(db): ...
async def test_create_vacancy_with_company(db): ...
async def test_create_search_link_to_vacancy(db): ...
async def test_screening_unique_constraint(db): ...
async def test_is_candidate_known_to_user(db): ...
async def test_list_vacancies_by_user_filter_source(db): ...
```

Обновить `tests/test_db_client.py` — удалить тесты на insert_candidates /
is_candidate_known / insert_vacancies (раз методы удалены).

## Команды для верификации

```bash
python -m pytest tests/test_db_relational.py -v
python -m pytest tests/test_db_client.py -v
python -m pytest tests/ -q  # всё в сумме
```

## Критерии готовности

- [ ] В `db/client.py` присутствуют все новые методы списком выше
- [ ] Методы `insert_candidates`, `insert_vacancies`, `is_candidate_known`,
  `is_vacancy_known` удалены
- [ ] `_COLUMNS["sessions"]` обновлён (без 4 старых полей, с 2 новыми)
- [ ] `tests/test_db_relational.py` существует, минимум 6 тестов, все зелёные
- [ ] `tests/test_db_client.py` обновлён (удалены тесты на удалённые методы)
- [ ] `python -m pytest tests/ -q` → 90+ passed, 0 failed
