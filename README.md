# recruiter_assistant

AI-ассистент рекрутёра: скрининг кандидатов по вакансии и поиск открытых вакансий
по резюме. Доступен через Telegram-бота.

Изначально внутренний сервис `05_refind/services/recruiter_assistant/`, вынесен
в отдельный репозиторий как переиспользуемый инструмент.

## Что умеет

Два пайплайна:

- **vacancy → candidates** — по вакансии (JD) генерирует boolean-запрос,
  ищет кандидатов в LinkedIn (Apify) и скринит их через LLM.
- **cv → jobs** — по резюме (CV) генерирует boolean-запрос, ищет открытые
  вакансии и оценивает их соответствие кандидату.

Результат прогона — `.md` отчёт.

## Структура

```
recruiter_assistant/
├── core/           # бизнес-логика пайплайнов (можно дёргать вручную через CLI)
│   ├── boolean_generator/      # генерация LinkedIn boolean из JD/CV (OpenAI)
│   ├── candidate_screener/     # discover (Apify) + screening (OpenAI)
│   ├── utils/env.py            # единый поиск .env
│   ├── PIPELINE_vacancy_to_candidates.md
│   └── PIPELINE_cv_to_jobs.md
├── bot/            # Telegram-обёртка (в разработке)
├── db/             # SQLite-слой: schema.sql, migrations/, client.py
├── config/         # whitelist.json (gitignored)
├── data/           # БД и артефакты прогонов (gitignored)
├── tests/          # юнит-тесты
├── .env.example
└── requirements.txt
```

Граница: `core/` — бизнес-логика, `bot/` + `db/` — обвязка для Telegram-сервиса.

## Установка

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux
pip install -r requirements.txt
cp .env.example .env            # заполнить ключами
```

## Ручной запуск пайплайнов (CLI)

Запускать из корня репо, чтобы пакет `core` был на пути.

**Генерация boolean из вакансии:**

```bash
python -m core.boolean_generator.generator path/to/vacancy.md --brief path/to/brief.md
```

**CV → jobs (поиск вакансий по резюме):**

```bash
python -m core.candidate_screener.cli.run_jobs --candidate <name> \
  --locations "Germany" --experience senior --count 5 --dry-run
```

Подробности пайплайнов — в [core/PIPELINE_vacancy_to_candidates.md](core/PIPELINE_vacancy_to_candidates.md)
и [core/PIPELINE_cv_to_jobs.md](core/PIPELINE_cv_to_jobs.md).

## База данных

SQLite хранит состояние сессий и результаты прогонов (пользователи, сессии,
runs, найденные кандидаты/вакансии). Тяжёлые артефакты (входные файлы, отчёты,
сырые Apify-дампы) лежат файлами на диске в `data/`, в БД — только пути.

Файл БД: `data/recruiter_assistant.db` (gitignored, путь через `DB_PATH`).
Открывается в режиме **WAL** — конкурентные чтения + один писатель без
`database is locked` (бот async, несколько юзеров параллельно).

```bash
python -m db.client --init      # создать БД из db/schema.sql
python -m db.client --migrate   # применить недостающие миграции из db/migrations/
```

Схема — `db/schema.sql`. Миграции — `db/migrations/NNN_*.sql`, отслеживаются
через таблицу `_migrations`. Без alembic, без ORM — только `sqlite3` stdlib.

## Telegram-бот

В разработке. План — `task_tracker/todo/recruiter_assistant_telegram_service/PLAN.md`.

```bash
# python -m bot.main   # заглушка, появится на step_4
```
