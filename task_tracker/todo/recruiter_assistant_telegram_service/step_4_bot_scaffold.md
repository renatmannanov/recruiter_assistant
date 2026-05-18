# Step 4: Bot scaffold + state machine

> Статус: done
> Зависит от: step_3 (DB готова). step_0 RESOLVED — hub в архитектуре не участвует.

## Предусловия

- [x] **Dev Telegram bot создан** — `@rm_mini_recruiter_assistant_bot`, токен в `.env` как `TELEGRAM_BOT_TOKEN`. Dev-бот для локальной разработки (production создаётся на step_8).
- [x] Telegram user ID Рената (основной аккаунт) = **423915315**, вписан в `config/whitelist.json` локально.
- [ ] (Опционально) Тестовый Telegram user ID для второго аккаунта — для теста изоляции в step_9, на этом шаге не нужен.

## Цель

Создать скелет бота с state machine, заглушками для пайплайнов. Локально запускается в polling-режиме, реагирует на команды, ведёт state в SQLite. Реальные пайплайны подключаются в step_5/step_6.

## Архитектура: чистая state-машина (без LLM-агента)

**Решение:** весь флоу обрабатывается детерминированным Python-кодом. Никакого LLM на уровне роутинга сообщений. Сообщение не вписалось в state-машину → бот отвечает «Не понял. Команды: /help».

LLM-агент-помощник — **в бэклоге v2** (вернём если по логам увидим что юзеры часто пишут не по сценарию).

### Как обрабатываются сообщения

| Сообщение / ситуация | Обработка |
|---|---|
| Команды `/refind_vacancy`, `/refind_candidate`, `/cancel`, `/help`, `/start`, `/status` | handlers.py |
| Текст / .txt / .md (1-2 файла) в state `waiting_input` | extractors.py + pipelines.py |
| `"ок"`, `"ok"`, `"да"`, `"go"`, `"approve"`, 👍 в state `waiting_boolean_confirm` | код: confirm boolean |
| Любой другой текст в `waiting_boolean_confirm` | код: трактуем как отредактированный boolean |
| Сообщение в state `running` | код: «идёт прогон, подождите» |
| Текст без активной сессии | код: «Не понял. Начни через /refind_vacancy или /refind_candidate» |
| Любая команда не из списка | код: «Неизвестная команда. /help» |
| Текст в state `done`/`error`/`cancelled` | код: «Сессия завершена, начни новую» |

### Преимущества чистой state-машины на v1

- **Дёшево:** ноль LLM-вызовов на роутинг
- **Быстро:** код отвечает мгновенно
- **Предсказуемо:** весь флоу детерминированный, debugging тривиальный
- **Меньше кода:** нет `agent.py`, `agent_tools.py`, `tracking.py` — на v1 не пишем

## Структура файлов

```
bot/
├── __init__.py
├── main.py              # entry point, запуск polling
├── handlers.py          # обработчики команд и текста
├── state_machine.py     # StateMachine class, transitions, side effects
├── extractors.py        # text / .txt / .md → str (1-2 файла)
├── pipelines.py         # обёртки над boolean_generator, discover, screening, run_jobs
├── auth.py              # whitelist check
└── replies.py           # шаблоны ответов в TG
```

(Нет `agent.py` / `agent_tools.py` / `tracking.py` — LLM-агент в v1 не делаем. Нет `notion_writer.py` — Notion в v1 нет, вывод = .md файл.)

## State machine

### States

```python
class SessionStep(Enum):
    WAITING_INPUT = "waiting_input"                    # ждём текст/файл(ы) с JD или CV
    WAITING_BOOLEAN_CONFIRM = "waiting_boolean_confirm"  # boolean показан, ждём 'ок' или новый текст
    RUNNING = "running"                                # пайплайн выполняется (фон)
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"
```

**Нет `WAITING_BRIEF`.** Brief приходит сразу: юзер шлёт 1 файл (vacancy/cv) или 2 файла (vacancy/cv + brief). См. extractors ниже.

### Transitions

```
[no session]
  /refind_vacancy or /refind_candidate → create session, step=WAITING_INPUT
  /cancel → ничего

WAITING_INPUT
  текст / 1 файл → extract → input_text → generate boolean → step=WAITING_BOOLEAN_CONFIRM
  2 файла → extract оба → input_text + brief_text → generate boolean (с brief) → step=WAITING_BOOLEAN_CONFIRM
  /cancel → step=CANCELLED
  /refind_* → cancel old session, create new

WAITING_BOOLEAN_CONFIRM
  "ок" / "ok" / "да" / "go" / 👍 → boolean_text=original → step=RUNNING, kick off pipeline
  любой другой текст → boolean_text=user_text → step=RUNNING, kick off pipeline
  /cancel → step=CANCELLED
  /refind_* → cancel old, create new

RUNNING
  любое сообщение → "идёт прогон, подождите"
  /cancel → попытаться остановить, step=CANCELLED

DONE / ERROR / CANCELLED
  любое сообщение → "сессия завершена, начни новую через /refind_vacancy или /refind_candidate"
```

### Где живёт фоновый пайплайн (RUNNING)

Пайплайн занимает 30-90 сек для vacancy→candidates, до 3 мин для cv→jobs. Бот не должен блокироваться.

**Решение:** `asyncio.create_task(run_pipeline(session_id))`. python-telegram-bot работает на asyncio. Бот продолжает обрабатывать другие сообщения. Когда пайплайн завершается — отправляет результат (+ .md файл) в TG.

## extractors.py — приём 1-2 файлов

```python
# bot/extractors.py
# Поддерживаем: текст сообщения, .txt, .md
# 1 файл → (input_text, None)
# 2 файла → (input_text, brief_text)
#   определение какой из них brief: по имени файла (содержит 'brief') или по порядку (2-й = brief)
# .pdf, .docx → отвергаем с понятным сообщением

ALLOWED_EXTENSIONS = {".txt", ".md"}
MAX_FILE_SIZE = 1_000_000  # 1 MB

def extract_input(messages_or_files) -> tuple[str, str | None]:
    """Возвращает (input_text, brief_text|None)."""
    ...
```

Логика определения brief среди двух файлов:
1. Если имя одного файла содержит `brief` (case-insensitive) — он brief, второй — vacancy/cv
2. Иначе — первый присланный = vacancy/cv, второй = brief

## Authentication (auth.py)

**КРИТИЧНО:** `config/whitelist.json` НЕ коммитится в git. В репо только `whitelist.example.json` с плейсхолдерами.

Whitelist в v1 — простой список:
```jsonc
// config/whitelist.example.json (коммитится)
{
  "users": [
    { "telegram_user_id": "<TELEGRAM_USER_ID_INT>", "display_name": "<friendly name>" }
  ]
}
```

```python
# bot/auth.py
def is_authorized(telegram_user_id: int) -> bool: ...
def get_user_config(telegram_user_id: int) -> dict | None: ...
```

При первом сообщении от whitelisted юзера, если его нет в `users` SQLite — создаём запись.

Не-whitelisted: "Доступ закрыт. Этот бот работает только по whitelist'у."

## Replies (replies.py)

```python
WELCOME = "Привет! Я recruiter assistant. Команды:\n/refind_vacancy — найти кандидатов под вакансию\n/refind_candidate — найти вакансии под CV\n/cancel — отменить текущую сессию"

ASK_FOR_VACANCY_INPUT = """Окей, ищем кандидатов под вакансию. Пришли описание вакансии — текстом, .txt или .md файлом.

Опционально: прикрепи вторым файлом brief (visa/locations/salary/remote) — назови файл со словом 'brief' или пришли его вторым."""

ASK_FOR_CV_INPUT = """Окей, ищем вакансии под кандидата. Пришли CV — текстом, .txt или .md файлом.

Опционально: вторым файлом brief с предпочтениями кандидата."""

BOOLEAN_GENERATED = """Сгенерил boolean:

```
{boolean}
```

Если ОК — ответь 'ок'. Если нужно поправить — пришли исправленный вариант."""

PIPELINE_STARTED = "Запускаю поиск... обычно 1-2 минуты, для CV→jobs до 3 минут."

PIPELINE_DONE = """✅ Готово. Сессия #{session_id}

Найдено: {found}, прошли скрининг: {screened}, прошли: {passed}

Отчёт — в файле ниже."""
# + бот отправляет report.md вложением

PIPELINE_FAILED = "❌ Ошибка прогона. Сессия #{session_id}\n{error_text}\n\nНачни новую через /refind_vacancy или /refind_candidate"

UNAUTHORIZED = "Доступ закрыт. Этот бот работает только по whitelist'у."

NOT_UNDERSTOOD = "Не понял. Используй /help для списка команд."
```

## Заглушки пайплайнов

```python
# bot/pipelines.py
async def generate_boolean(input_text: str, brief_text: str | None, pipeline_type: str) -> str:
    # Stub: фейковый boolean для проверки flow
    return f'("Senior Engineer" OR "Lead") AND (Python) — STUB for {pipeline_type}'

async def run_pipeline(session_id: int, pipeline_type: str) -> dict:
    # Stub: ждёт 5 секунд, возвращает фейковые метрики + путь к фейковому .md
    await asyncio.sleep(5)
    return {"found": 10, "screened": 5, "passed": 2, "report_path": "data/sessions/stub/report.md"}
```

В step_5 и step_6 заменим на реальные обёртки.

## Команды (TG)

- `/start` — приветствие
- `/help` — то же
- `/refind_vacancy` — старт сессии vacancy_to_candidates
- `/refind_candidate` — старт сессии cv_to_jobs
- `/cancel` — отмена текущей сессии
- `/status` — показать что в работе

## Локальный запуск

```bash
cd recruiter_assistant
python -m bot.main
```

`.env`:
```
TELEGRAM_BOT_TOKEN=...
DB_PATH=./data/recruiter_assistant.db
WHITELIST_PATH=./config/whitelist.json
OPENAI_MODEL=gpt-4o
BOOLEAN_MODEL=gpt-4o
SCREENING_MODEL=gpt-4o
OPEN_AI_KEY=sk-...
APIFY_AI_TOKEN=apify_api_...
```

## Критерии готовности

- [x] `bot/` структура создана: `__init__.py`, `main.py`, `handlers.py`, `state_machine.py`, `extractors.py`, `pipelines.py`, `auth.py`, `replies.py` (без agent.py / agent_tools.py / tracking.py / notion_writer.py)
- [x] State machine реализована с тестами на переходы (нет состояния WAITING_BRIEF) — `test_state_machine.py`, тест `test_no_waiting_brief_state`
- [x] Auth работает (whitelisted пускается, не-whitelisted получает отказ) — `test_auth.py` + `test_handlers.py::test_unauthorized_user_blocked`
- [x] Router в handlers.py: роутит по таблице "как обрабатываются сообщения"
- [x] На непонятном сообщении бот отвечает осмысленно (`NOT_UNDERSTOOD` / `UNKNOWN_COMMAND` / `NO_SESSION`) — без LLM
- [x] Локально через polling: `/refind_vacancy` → текст → stub-boolean → "ок" → "идёт прогон" → "готово" + stub .md файл — проверено Ренатом (лог в чате)
- [x] То же для `/refind_candidate` — проверено Ренатом
- [x] Тест с 2 файлами / .txt-.md / .pdf-reject — extractors покрыты `test_extractors.py` (19 тестов); .pdf-reject и .md проверены Ренатом в живом чате
- [x] `/cancel` отменяет сессию — `test_handlers.py::test_cancel_active_session`
- [x] Файл .txt и .md обрабатываются — проверено Ренатом + `test_extractors.py`
- [x] Файл .pdf отвергается с понятным сообщением — проверено Ренатом + `test_extractors.py`
- [x] Сессия и run появляются в SQLite — проверено по реальной БД после прогонов Рената (sessions #1-3, runs #1-2)
- [x] Async-пайплайн не блокирует обработку других сообщений — `test_handlers.py::test_status_responds_while_pipeline_running` (/status отвечает <0.3с пока пайплайн спит 1с)

## Заметки по реализации

- `python-telegram-bot` 22.5. Пайплайн запускается через `asyncio.create_task` — бот не блокируется.
- **Media-group:** 2 файла приходят как 2 отдельных update с общим `media_group_id`. Собираются с debounce 1.5с через `job_queue.run_once` — иначе обработали бы по одному.
- `bot/main.py` авто-инициализирует схему БД при первом запуске (`_schema_ready`) — отдельный `db.client --init` для бота не нужен.
- `on_text`/`_process_files` используют общий хелпер `_generate_boolean_and_advance(say=...)` — `say` это async-callable, работает и для текста (reply), и для media-group (send_message).
- Юнит-тесты хендлеров — на мок-объектах Telegram (`FakeUpdate`/`FakeContext`), без сети.
