# PLAN: Recruiter Assistant как самостоятельный Telegram-сервис

> Статус: pending
> Создано: 2026-05-05
> Обновлено: 2026-05-18 (v1 упрощён: без Notion, без LLM-агента, хостинг на Mac mini, вывод = .md файл)
> Связано:
> - Ответ от 00_anna: `hub_response_to_proposal.md` (в этой же папке)
> - История согласования: `_archived/step_0_hub_architecture_alignment_RESOLVED.md`

---

## Цель

Вынести `services/recruiter_assistant/` из `05_refind` в **отдельный репозиторий** `recruiter_assistant`, обернуть в Telegram-бот (свой polling, свой state-machine, свой launchd-агент), задеплоить на **Mac mini** в `~/projects/recruiter_assistant/`. Поддержать оба пайплайна (vacancy→candidates и cv→jobs) с интерактивным подтверждением boolean.

**Hub НЕ участвует** в архитектуре нашего бота. Сервис полностью изолирован, координация — только при общих ресурсах через владельца.

## Принципы v1 — максимально просто

v1 = «тот же пайплайн что работает сейчас, просто доступен удалённо через Telegram». Ноль изменений в LLM-части, минимум нового кода. Что это означает:

- **Без Notion.** Результат прогона — `.md` файл (как сейчас CLI кладёт в `jobs_results.md` / report). Бот пересылает этот файл юзеру в Telegram.
- **Без LLM-агента-помощника.** Бот = чистая детерминированная state-machine. Не понял сообщение → «не понял, вот /help».
- **Без отдельного шага brief.** Юзер шлёт 1 файл (vacancy/cv) или 2 файла (vacancy/cv + brief). Это ровно как `--brief` в текущем CLI.
- **LLM остаётся на OpenAI gpt-4o** (boolean_generator + screening) — не трогаем.
- **Хостинг — Mac mini** (уже настроен, не спит). launchd вместо systemd.
- **Хранение:** SQLite — состояние и связи (сессии, runs, найденные кандидаты/вакансии); файлы на диске — артефакты (входные vacancy/brief, выходной report.md).

## Что НЕ делаем (бэклог на v2)

- **Notion-вывод** — карточки кандидатов/вакансий в Notion DB с фильтрами (v1 отдаёт .md файл)
- **LLM-агент-помощник** — Claude на «странных» сообщениях, самообучение через `agent_invocations` (v1 без агента)
- **Локальная модель для screening** на Mac mini + API fallback — снижение OpenAI-расходов
- PDF/DOCX парсинг (только текст / `.txt` / `.md`)
- Cross-matching кандидатов из старых runs против новых вакансий (и наоборот)
- Почта для онбординга юзеров (v1 — whitelist руками)
- Регистрация в `~/claude-hub/shared/bots_registry.json` (v1 — сервис самостоятелен)

---

## Архитектура (краткое резюме)

### Репозиторий

Новый отдельный репо `recruiter_assistant` (код скопирован из `05_refind/services/recruiter_assistant/`, оригинал там остаётся):

```
recruiter_assistant/
├── core/                      # бизнес-логика, ТОЛЬКО КОД (из 05_refind/services/recruiter_assistant/)
│   ├── boolean_generator/     # без изменений
│   ├── candidate_screener/    # без изменений
│   ├── utils/env.py           # НОВОЕ: единый поиск .env
│   ├── PIPELINE_vacancy_to_candidates.md
│   └── PIPELINE_cv_to_jobs.md
├── bot/                       # НОВОЕ: телеграм-обёртка
│   ├── main.py                # entry point, polling
│   ├── handlers.py            # обработчики команд
│   ├── state_machine.py       # переходы waiting_input → waiting_boolean → running → done
│   ├── extractors.py          # text / .txt / .md → str
│   ├── pipelines.py           # обёртки над boolean_generator, discover, screening, run_jobs
│   ├── auth.py                # whitelist check
│   └── replies.py             # шаблоны ответов
├── db/                        # НОВОЕ
│   ├── schema.sql
│   ├── migrations/
│   └── client.py              # SQLite-обёртка
├── data/                      # НОВОЕ, gitignored
│   ├── recruiter_assistant.db
│   └── sessions/<id>/         # артефакты прогона: vacancy.md, brief.md, report.md
├── config/
│   └── whitelist.json         # просто список telegram_user_id (gitignored)
├── README.md
├── .env.example
├── .gitignore
└── requirements.txt
```

**ВАЖНО — стратегия копии:** код пайплайнов **копируется** в новый репо, `05_refind/services/recruiter_assistant/` остаётся нетронутым (ничего не удаляем — ручные прогоны Рената там продолжают работать). Папки `clients/`, `candidates/`, `test_results/` (данные клиентов) в новый репо НЕ копируются — боту они не нужны. Дальше две копии живут независимо; вся разработка — только в новом репо. Recruiter_assistant становится переиспользуемым инструментом.

**Принцип `core/`:** весь существующий код пайплайнов изолирован в `core/`. Бот импортирует из него (`from core.boolean_generator...`). Чистая граница между **бизнес-логикой** (core, можно дёргать вручную как сейчас) и **обвязкой** (bot, db, config).

### Деплой — Mac mini

- Локально (разработка): `c:\Users\renat\projects\recruiter_assistant\`
- Боевой хостинг: **Mac mini** (уже настроен, не уходит в сон), путь `~/projects/recruiter_assistant/`
- Telegram polling: бот сам ходит к серверам Telegram (исходящие соединения) — белый IP и проброс портов **не нужны**, Mac mini за домашним роутером работает нормально
- Автозапуск через **launchd** (`~/Library/LaunchAgents/work.refind.recruiter-assistant-bot.plist`) — macOS-аналог systemd
- Деплой через `git pull`, рабочие данные (`data/`) в `.gitignore`

### Поток сценария

```
[user] /refind_vacancy + текст или 1-2 файла (vacancy[, brief])
  ↓ (бот: extractors.py)
[bot] извлекает текст(ы) → boolean_generator
  ↓
[bot → user TG] "Boolean: ...   reply 'ок' или новый текст"
  ↓
[user] "ок" | новый boolean
  ↓ (бот: state_machine.py обновляет session)
[bot] discover (Apify) + screening (OpenAI) → пишет report.md
  ↓
[bot → user TG] "Готово. Сессия #N." + .md файл вложением
```

State хранится в SQLite (`sessions.step`). Бот подключается к Telegram через polling (`python-telegram-bot`), роутит сообщения через детерминированную state-machine.

**Brief — без отдельного шага.** Юзер шлёт 1 файл → vacancy/cv. 2 файла → vacancy/cv + brief (по имени файла или по порядку). Если текстом — только vacancy/cv. Это эквивалент `--brief` в текущем CLI.

### SQLite-схема (укрупнённо)

```sql
users (telegram_user_id PK, display_name, created_at)
sessions (id PK, user_id FK, pipeline_type, step, input_text, brief_text, boolean_text, boolean_text_original, report_path, error_text, created_at, updated_at)
runs (id PK, session_id FK, user_id [денорм], pipeline_type, status, screening_json, report_md, raw_apify_path, found_count, screened_count, passed_count, cost_usd, duration_sec, error_text, created_at)
candidates_found (id PK, run_id FK, user_id [денорм], linkedin_url, name, ai_status, ai_score, ai_comment, raw_profile_json, created_at)
vacancies_found (id PK, run_id FK, user_id [денорм], linkedin_url, title, company, location, ai_score, ai_recommendation, raw_job_json, created_at)
```

**Изменения против старой схемы:** убраны `candidates_database_id`/`vacancies_database_id` (Notion ушёл), `notion_page_id`/`notion_page_url` (Notion ушёл), таблица `agent_invocations` (LLM-агента нет). `raw_apify_json` хранится файлом на диске (`raw_apify_path` — путь), не TEXT-колонкой.

Полная схема — в `step_3_sqlite_schema.md`.

### Архитектура обработки сообщений — чистая state-машина

**Весь флоу = детерминированный код (state-машина в Python).** Никакого LLM на уровне роутинга сообщений. Стандартные шаги (команды, входной текст/файлы, "ок", отредактированный boolean) обрабатываются кодом.

Сообщение не вписалось в state-машину → бот отвечает «Не понял. Команды: /help». Без LLM.

LLM-агент-помощник — в бэклог v2 (вернём если по логам увидим что юзеры часто пишут не по сценарию).

### Модели

- boolean_generator: OpenAI **gpt-4o** (как сейчас, не трогаем)
- screening: OpenAI **gpt-4o** (как сейчас)

Всё через env-переменные (`OPENAI_MODEL`, `BOOLEAN_MODEL`, `SCREENING_MODEL`) — менять без правки кода.

**v2:** screening на локальную модель Mac mini + API fallback. boolean можно на Claude. Это отдельный план следующей итерацией.

---

## Шаги

### Шаг 0: Согласование архитектуры с hub — RESOLVED
- [x] Согласование завершено 2026-05-07. Hub полностью отделяется. См. `_archived/step_0_hub_architecture_alignment_RESOLVED.md` и `hub_response_to_proposal.md`.

### Шаг 1: Подготовка к выносу — определение границ
- [x] step_1_scope_and_naming.md — Фаза A (новый репо) + Фаза B (`05_refind/CLAUDE.md` + auto-memory) done

### Шаг 2: Создание нового репозитория
- [x] step_2_create_new_repo.md — Фаза A done: git init, код скопирован в core/, импорты починены, load_dotenv вынесен в entry points, smoke test пройден, запушено на GitHub. Фаза B done: 05_refind/CLAUDE.md обновлён, smoke test 05_refind пройден

### Шаг 3: SQLite-схема
- [x] step_3_sqlite_schema.md — схема (без Notion-полей, без agent_invocations), миграции, `db/client.py` с CRUD, WAL, thread-safety, cleanup_stale_sessions, `--init`/`--migrate` CLI, 21 юнит-тест

### Шаг 4: Bot scaffold + state machine
- [x] step_4_bot_scaffold.md — структура `bot/` (7 модулей), state machine (без WAITING_BRIEF), заглушки пайплайнов, polling. 82 юнит-теста, живой polling-тест пройден

### Шаг 5: Интеграция с пайплайнами (vacancy → candidates)
- [x] step_5_vacancy_pipeline.md — выделены `core/.../core/discover.py` (pure Apify search) и `core/.../core/screen_runner.py` (pure screening loop), `cli/run_local.py` использует `screen_candidates`. `bot/pipelines.py` подменены заглушки: `generate_boolean` зовёт OpenAI через `generate_boolean_search`+`extract_boolean`, `run_pipeline` выполняет discover → SQLite dedup → screen → report.md, файлы в `data/sessions/<id>/`. handlers передают `run_id` + `db` в `run_pipeline`, `complete_run` получает реальные `cost_usd`/`duration_sec`. 82 юнит-теста зелёные. Открытые темы (Apify cost real, Apify params, vacancy_name) — в `task_tracker/backlog/step_5_backlog.md`. **E2E с реальным Apify ещё не запущен.**

### Шаг 6: Интеграция с пайплайнами (cv → jobs)
- [ ] step_6_cv_pipeline.md — extractors для CV, рефакторинг `cv_parser.parse_cv()` для приёма текста, обёртка над `boolean_generator --target jobs`, обёртка над `run_jobs`, отдача report.md в TG

### Шаг 7: Финализация репо перед деплоем
- [ ] step_7_finalize_repo.md — `requirements.txt`, `.env.example`, `README.md` с инструкциями локального запуска

### Шаг 8: Деплой на Mac mini
- [ ] step_8_deploy.md — git push, clone на Mac mini, venv, launchd-агент, hard-limits на провайдерах + circuit breaker, graceful shutdown с cleanup, ручная проверка через TG

### Шаг 9: End-to-end тест
- [ ] step_9_e2e_test.md — оба пайплайна с двух TG-аккаунтов (Renat основной + тестовый), проверка изоляции (юзер A не видит данные юзера B)

### Шаг 10: Завершение плана
- [ ] step_10_completion.md — чеклист, перенос в done/, обновление CLAUDE.md обоих репо

---

## Критерии готовности всего плана

- [ ] `recruiter_assistant` живёт в отдельном репо, ручные прогоны работают
- [ ] SQLite-схема создана, миграции работают
- [ ] Bot принимает текст / .txt / .md (1-2 файла), генерит boolean, ждёт подтверждения, запускает прогон
- [ ] Оба пайплайна работают через бота end-to-end
- [ ] Результат прогона приходит юзеру `.md` файлом в Telegram
- [ ] Сервис задеплоен на Mac mini, работает через launchd
- [ ] Тест на двух юзерах: каждый видит только свои данные
- [ ] `05_refind/CLAUDE.md` обновлён: добавлена секция "Связанные проекты" со ссылкой на новый репо

---

## Бэклог (на v2)

**Вывод результатов:**
- Notion-вывод — карточки кандидатов/вакансий в Notion DB с полем `session_id` для фильтрации
- Notion views с фильтрами через API

**LLM-агент-помощник:**
- Claude-агент на «странных» сообщениях (вопросы про результаты, нестандартный ввод)
- Таблица `agent_invocations`, sentiment-классификация, `/refind_patterns_report`
- Самообучение: промоушн часто-встречающихся паттернов в state-машину

**Модели (снижение OpenAI расходов):**
- Локальная модель на Mac mini для screening (массовая задача, выгодно) + API fallback если не справляется
- Миграция boolean_generator на Claude
- Полный отказ от OpenAI

**Обработка ввода:**
- PDF/DOCX парсинг (pypdf для CV, python-docx для JD)
- Brief как структурированный парс (visa, locations, salary, remote)

**Алгоритмика:**
- Cross-matching: AI-скоринг кандидата против вакансии из других runs

**Инфраструктура:**
- Почта для онбординга новых юзеров (вместо ручного whitelist)
- Веб-интерфейс
- Аналитика по runs (cost, duration, success rate)
- Партиционирование БД / миграция артефактов в отдельный storage
- Интеграция с whitelist hub'а, регистрация в `bots_registry.json`
- Миграция SQLite → общий Postgres на Mac mini. В v1 SQLite оптимален
  (whitelist-юзеры, редкие записи, конкурентность решена WAL). Смысл появится
  когда придут аналитика по многим юзерам, веб-интерфейс, рост числа юзеров
  или cross-matching с тяжёлыми JOIN'ами. `db/client.py` спроектирован так,
  что замена локализована в одном модуле.
