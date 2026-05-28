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
| 6  | step_6_phase1_e2e.md                              | 1    | [ ]    |
| 7  | step_7_relational_schema.md                       | 2    | [ ]    |
| 8  | step_8_client_crud_new_tables.md                  | 2    | [ ]    |
| 9  | step_9_pipelines_to_new_model.md                  | 2    | [ ]    |
| 10 | step_10_bot_commands_vacancies_runs.md            | 2    | [ ]    |
| 11 | step_11_bot_commands_candidate_rescreen.md        | 2    | [ ]    |
| 12 | step_12_phase2_e2e.md                             | 2    | [ ]    |
| 13 | step_13_completion.md                             | 2    | [ ]    |

## Критерии готовности всего плана

- [ ] Бот работает на Postgres end-to-end (`/refind_vacancy` → boolean → discover → screen → report.md)
- [ ] Все тесты зелёные через PG-fixture (минимум 90, плюс новые)
- [ ] Новые таблицы: companies, vacancies, candidates, searches, candidate_screenings — заполняются корректно
- [ ] Один LinkedIn-профиль = одна строка в `candidates` (даже после нескольких прогонов)
- [ ] Каждая `vacancy` хранит историю `searches` (boolean'ов)
- [ ] Команда `/vacancies` отдаёт список вакансий пользователя
- [ ] Команда `/candidate <linkedin_url>` показывает историю скринингов человека по разным вакансиям
- [ ] Команда `/rescreen <run_id> <new_vacancy_id>` гонит существующих кандидатов на новой вакансии без Apify
- [ ] Команда `/replay_search <search_id>` запускает Apify-прогон с тем же boolean'ом
- [ ] `replies.PIPELINE_DONE` показывает "X из 25 кандидатов уже видели по другим вакансиям"
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
