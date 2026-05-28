# Промпт для нового окна — step 5.5 (PG + реляционная модель)

Скопируй текст ниже в новое окно Claude Code, открытое в проекте
`c:\Users\renat\projects\recruiter_assistant\`.

---

## ПРОМПТ (копировать целиком)

Работаем над проектом recruiter_assistant — отдельный репозиторий.
Локально: c:\Users\renat\projects\recruiter_assistant\
GitHub: https://github.com/renatmannanov/recruiter_assistant

Прочитай в этом порядке:
1. README.md проекта (CLAUDE.md в репо нет — основной контекст в README)
2. Memory нового репо: C:\Users\renat\.claude\projects\c--Users-renat-projects-recruiter_assistant\memory\MEMORY.md
   и файлы на которые он ссылается
3. task_tracker/todo/step_5_5_pg_relational_model/PLAN.md
4. task_tracker/todo/step_5_5_pg_relational_model/progress.md
   ⚠️ Там зафиксированы все решения по step_5.5 — читай внимательно
5. task_tracker/todo/step_5_5_pg_relational_model/step_1_pg_setup_on_mac.md
   (первый шаг плана)
6. db/client.py — текущий SQLite-клиент, который мы переписываем
7. db/schema.sql — текущая SQLite схема

Контекст где мы остановились:

- **Step 5 закрыт.** Бот работает end-to-end на SQLite. 90 unit-тестов
  зелёные. Реальный прогон сделан (session 4, Sonia ASR, 25 кандидатов,
  GO:6/MAYBE:6/SKIP:13, $0.80).
- **Что есть нового против step_4:**
  - `core/candidate_screener/core/discover.py` — pure Apify search
  - `core/candidate_screener/core/screen_runner.py` — pure screening loop
  - Resume-from-raw_apify.json: если `data/sessions/<id>/raw_apify.json` уже
    есть — Apify не вызывается заново
  - `replies.PIPELINE_DONE` показывает total_found / GO / MAYBE / SKIP
  - Тесты: 90/90 (`python -m pytest tests/ -q`)
- **Step 5.5 написан как план**, не выполнен. 13 шагов в
  `task_tracker/todo/step_5_5_pg_relational_model/`. Делится на 2 фазы:
  - Фаза 1 (steps 1–6): lift SQLite → Postgres без изменений в логике
  - Фаза 2 (steps 7–13): новая реляционная модель + команды бота

Задача нового окна — **исполнить план step_5.5 по шагам**, начиная с step_1.

Ключевые решения (уже зафиксированы в `progress.md`, не переоткрываем):
- PG-клиент: **asyncpg**
- PG на Mac mini, новая БД `recruiter_assistant_dev`. Доступ с Windows через
  сеть (LAN или Tailscale — решаем в step_1)
- Тесты: PG-schema namespace per fixture (без testcontainers/docker)
- Миграция данных SQLite → PG: **не делаем**, SQLite-БД сносим
- JSONB для raw_profile_json / screening_json
- Native PG ENUM для ai_status и vacancy_source
- `pending_boolean` колонка в sessions для хранения boolean до подтверждения

Поведение:
- **Step_1 требует ручных действий Рената на Mac mini** (установка PG,
  создание БД, настройка pg_hba.conf). Подготовь команды и инструкции,
  дождись пока Ренат выполнит на маке, потом проверь подключение с Windows.
- После каждого step'а — отметь [x] в PLAN.md и обнови progress.md (если
  узнал что-то новое).
- Каждый step — отдельный коммит ("feat(db): step 5.5.N — <название>").
- Если упрёшься в развилку которой нет в плане — спроси, не решай молча.
- Тесты на каждой фазе: 90+ зелёных. Не двигаемся дальше с красными.
- Если в процессе обнаружишь что план кривой — обсуди со мной, обнови план,
  потом продолжай.

Начни с подтверждения понимания:
- Что прочитал
- Какой step выполняешь первым
- Какие подготовительные команды нужны от меня на маке (для step_1)

Дождись подтверждения перед началом изменений в коде.

---

## Что важно при копировании в новое окно

1. **Открой новое окно Claude Code в `c:\Users\renat\projects\recruiter_assistant\`**, не в 05_refind. Это другой репо со своей memory.
2. **Промпт самодостаточен** — указывает что и в каком порядке читать.
3. **Не упускай шаг 2** (memory нового репо) — там критичные правила,
   которые сэкономят кучу времени (boolean_v2, discover_pipeline, output_format).
4. **Step_1 требует тебя физически у Mac mini.** Без этого новое окно
   зависнет на ожидании. Готовь руки.
