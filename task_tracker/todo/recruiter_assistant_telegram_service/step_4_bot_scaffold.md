# Step 4: Bot scaffold + state machine

> Статус: pending
> Зависит от: step_3 (DB готова). step_0 RESOLVED — hub в архитектуре не участвует.

## Предусловия

- [ ] **Dev Telegram bot создан** через [@BotFather](https://t.me/BotFather): `/newbot` → имя → username → токен в `.env` как `TELEGRAM_BOT_TOKEN`. Это **dev-бот** для локальной разработки, отдельный от production (production создаётся на step_8).
- [ ] Telegram user ID Рената (основной аккаунт) = **423915315**, вписан в `config/whitelist.json` локально.
- [ ] (Опционально) Тестовый Telegram user ID для второго аккаунта (для теста изоляции в step_9).

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

- [ ] `bot/` структура создана (без agent.py / agent_tools.py / tracking.py / notion_writer.py)
- [ ] State machine реализована с тестами на переходы (нет состояния WAITING_BRIEF)
- [ ] Auth работает (whitelisted пускается, не-whitelisted получает отказ)
- [ ] Router в handlers.py: правильно роутит по таблице "как обрабатываются сообщения"
- [ ] На непонятном сообщении бот отвечает `NOT_UNDERSTOOD` (без LLM)
- [ ] Локально через polling: `/refind_vacancy` → "пришли вакансию" → отправил текст → получил stub-boolean → "ок" → "идёт прогон" → через 5 сек "готово" + stub .md файл
- [ ] То же для `/refind_candidate`
- [ ] Тест с 2 файлами: отправил vacancy.md + brief.md → оба извлеклись, boolean генерится с учётом brief (на этом шаге stub)
- [ ] `/cancel` отменяет сессию
- [ ] Файл .txt и .md обрабатываются (extractors.py)
- [ ] Файл .pdf отвергается с понятным сообщением
- [ ] Сессия и run появляются в SQLite
- [ ] Async-пайплайн не блокирует обработку других сообщений (тест: запустить пайплайн, прислать /status — ответ сразу)
