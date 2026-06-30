# Step 5.5: Postgres + реляционная модель данных

> Статус: pending
> Дата: 2026-05-20
> Тип: рефакторинг + фича
> Связано:
> - Родительский план: `task_tracker/todo/recruiter_assistant_telegram_service/PLAN.md`
> - Бэклог из step_5: `task_tracker/backlog/step_5_backlog.md`

## Цель

Перевести БД recruiter_assistant с SQLite на Postgres и спроектировать новую
реляционную модель: глобальный справочник кандидатов (один человек = одна
строка), вакансии как сущности с историей boolean'ов, переиспользование
прошлых кандидатов между вакансиями. Делим работу на 2 фазы: сначала lift на
PG без изменений в логике, потом новая модель — чтобы локализовать риск.

## Фазы

- **Фаза 1 (steps 1–6):** lift текущей SQLite-схемы на Postgres. Никаких
  изменений в бизнес-логике или таблицах кроме диалекта. Цель — убедиться,
  что инфраструктура PG работает.
- **Фаза 2 (steps 7–13):** новая реляционная модель (companies / vacancies /
  candidates / searches / candidate_screenings), команды бота для работы с
  накопленными данными.

## Шаги

| #  | Файл                                              | Фаза | Статус |
|----|---------------------------------------------------|------|--------|
| 1  | step_1_pg_setup_on_mac.md                         | 1    | [x]    |
| 2  | step_2_pg_schema_lift.md                          | 1    | [x]    |
| 3  | step_3_asyncpg_client.md                          | 1    | [x]    |
| 4  | step_4_async_callers_bot.md                       | 1    | [x]    |
| 5  | step_5_pg_test_fixture.md                         | 1    | [x]    |
| 6  | step_6_phase1_e2e.md                              | 1    | [x]    |
| 7  | step_7_relational_schema.md                       | 2    | [x]    |
| 8  | step_8_client_crud_new_tables.md                  | 2    | [x]    |
| 9  | step_9_pipelines_to_new_model.md                  | 2    | [x]    |
| 10 | step_10_bot_commands_vacancies_runs.md            | 2    | [x]    |
| 11 | ~~step_11~~ → backlog/step_11_candidate_rescreen.md | 2  | [~]    |
| 11.5 | step_11_5_locations_in_apify.md                 | 2    | [x]    |
| 12 | step_12_phase2_e2e.md                             | 2    | [ ]    |
| 13 | step_13_completion.md                             | 2    | [ ]    |

> **Решения 2026-06-26 (новое окно):**
> - `/replay_search` вынесена в `task_tracker/backlog/step_5_backlog.md`.
>   step_10 = 3 команды (`/vacancies`, `/vacancy <id>`, `/runs`) — **done**.
> - **step_11 (`/candidate` + `/rescreen`) перенесён в backlog**
>   (`task_tracker/backlog/step_11_candidate_rescreen.md`) — решение Рената
>   «сначала базовые кейсы + locations, погонять, потом вернуться». Файл
>   содержит все решения и тех-находки (JSONB читается как строка, db_rows
>   готовы, confirm через новый шаг state-машины + миграция 004).
> - Добавлен step_11.5: locations из JD в Apify-запрос (баг качества выдачи,
>   подтверждён на step_6/12 e2e).
> - Resume-from-disk ключ остаётся в бэклоге — перед e2e чистим
>   `data/sessions/*` руками.
>
> **Текущий остаток фазы 2:** step_11.5 → step_12 (e2e) → step_13
> (completion). step_11 закрывается уже из backlog, после e2e.

## Критерии готовности всего плана

- [ ] Бот работает на Postgres end-to-end (`/refind_vacancy` → boolean → discover → screen → report.md)
- [ ] Все тесты зелёные через PG-fixture (минимум 90, плюс новые)
- [ ] Новые таблицы: companies, vacancies, candidates, searches, candidate_screenings — заполняются корректно
- [ ] Один LinkedIn-профиль = одна строка в `candidates` (даже после нескольких прогонов)
- [ ] Каждая `vacancy` хранит историю `searches` (boolean'ов)
- [x] Команда `/vacancies` отдаёт список вакансий пользователя (step_10)
- [~] Команда `/candidate <linkedin_url>` — **вынесена в backlog** (step_11 → backlog, 2026-06-26)
- [~] Команда `/rescreen <run_id> <new_vacancy_id>` — **вынесена в backlog** (step_11 → backlog, 2026-06-26)
- [~] Команда `/replay_search <search_id>` — **вынесена в backlog** (2026-06-26)
- [x] `replies.PIPELINE_DONE` показывает "X уже видели на других вакансиях" (step_10)
- [x] Locations из JD прокидываются в Apify-запрос (step_11.5, 2026-06-30)
- [ ] SQLite-зависимости полностью удалены (нет import sqlite3 в коде)
- [ ] `db/migrations/` содержит обе миграции (001_initial_pg, 002_relational_model)
- [ ] Memory нового репо обновлена (новая схема, PG-инфра)

## Бэклог из этого плана (на v2/после)

- Дедуп вакансий по хэшу JD при `/refind_vacancy` (сейчас всегда новая)
- Companies ↔ candidates (опыт работы из raw_profile_json)
- Полнотекстовый поиск по JD/CV через PG FTS
- Локальная dev-БД через docker-compose как альтернатива маку
- CLI-команды для каждого этапа (вынесено в `task_tracker/backlog/step_5_backlog.md`)
- Notion-sink как опциональный выход
