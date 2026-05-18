# Step 2: Создание нового репозитория

> Статус: Фаза A — done. Фаза B (обновление 05_refind) — pending.
> Зависит от: step_1 (имя и решения)

## Цель

Физически создать новый репо, перенести **только код**, проверить что ручные прогоны работают из нового места.

## Действия

### 2.1 Создать структуру

```
recruiter_assistant/
├── core/
├── bot/                       # пустая на этом шаге
├── db/                        # пустая
├── data/                      # пустая, в gitignore
│   └── .gitkeep
├── config/
├── .gitignore
├── .env.example
├── README.md
└── requirements.txt
```

### 2.2 Скопировать КОД в core/

Из `05_refind/services/recruiter_assistant/`:
- `boolean_generator/` → `core/boolean_generator/`
- `candidate_screener/` → `core/candidate_screener/`
- `PIPELINE_*.md` → `core/`

**НЕ копировать:** `clients/`, `candidates/`, `test_results/` — остаются в 05_refind (см. step_1.3).

### 2.3 Поправить импорты в core/

После переноса в `core/` нужно проверить и исправить:

**a) Absolute imports на пакеты `boolean_generator` / `candidate_screener`:**

```bash
cd recruiter_assistant
grep -rn "^from candidate_screener\|^from boolean_generator\|^import candidate_screener\|^import boolean_generator" core/
```

Заменить на `from core.candidate_screener.X import Y`. Особое внимание:
- `core/boolean_generator/generator.py` ~строка 253: `from candidate_screener.core.cv_parser import parse_cv` (lazy import внутри `main()`)
- `core/candidate_screener/cli/run_local.py`: относительные импорты — должны работать после переноса

**b) `load_dotenv(parents[N])` — путь к `.env`:**

```bash
grep -rn "load_dotenv\|parents\[" core/
```

**Что делаем:** убрать `load_dotenv` из библиотечных модулей (всё что глубже top-level CLI), читать `os.environ.get` напрямую. dotenv грузится **только в entry points**:
- `core/boolean_generator/generator.py` (CLI entry)
- `core/candidate_screener/cli/*.py` (CLI entries)
- `bot/main.py` (новый entry для бота)

Ввести единый helper `core/utils/env.py`:

```python
# core/utils/env.py
from pathlib import Path
from dotenv import load_dotenv

_ROOT_MARKERS = (".git", "pyproject.toml", "requirements.txt")
_MAX_PARENTS = 6

def load_project_env():
    """Find .env at project root by walking up from this file."""
    here = Path(__file__).resolve()
    for i, parent in enumerate(here.parents):
        if i > _MAX_PARENTS:
            break
        env = parent / ".env"
        if env.exists():
            load_dotenv(env)
            return env
        if any((parent / marker).exists() for marker in _ROOT_MARKERS):
            return None
    return None
```

В каждом entry-point: `from core.utils.env import load_project_env; load_project_env()`.

### 2.4 Проверить ручные прогоны

Smoke test — оба пайплайна работают из нового места. Так как `clients/` и `candidates/` остались в 05_refind, путь к ним указывается явно:

**Vacancy → candidates:**
```bash
cd recruiter_assistant
python -m core.boolean_generator.generator \
  c:/Users/renat/projects/05_refind/services/recruiter_assistant/clients/sonia/asr/vacancy.md \
  --brief c:/Users/renat/projects/05_refind/services/recruiter_assistant/clients/sonia/asr/brief.md
```

**CV → jobs:**
```bash
python -m core.candidate_screener.cli.run_jobs \
  --candidate test_python --locations "Germany" --experience senior --count 5 --dry-run
```

> Если `run_jobs --candidate` жёстко ищет папку `candidates/` в корне репо — на step_6 рефактор примет путь к CV напрямую. На этом шаге достаточно проверить boolean_generator и discover с явными путями.

### 2.5 .gitignore

```
# Data and secrets
data/
.env
.env.production
*.db
*.db-shm
*.db-wal

# Whitelist with real telegram_user_id — НИКОГДА в git
config/whitelist.json

# Python
__pycache__/
*.pyc
.venv/
.pytest_cache/

# IDE
.vscode/
.idea/
```

(Папка `data/.gitkeep` коммитится — чтобы директория существовала; содержимое `data/` игнорируется.)

### 2.6 .env.example

```
# Telegram
TELEGRAM_BOT_TOKEN=                    # @BotFather token

# OpenAI (для boolean_generator + screening)
OPEN_AI_KEY=sk-...

# Apify (для discover + run_jobs)
APIFY_AI_TOKEN=apify_api_...

# Models (опционально, есть дефолты в коде)
OPENAI_MODEL=gpt-4o
BOOLEAN_MODEL=gpt-4o
SCREENING_MODEL=gpt-4o

# Database
DB_PATH=./data/recruiter_assistant.db
WHITELIST_PATH=./config/whitelist.json

# Circuit breaker (см. step_8)
MAX_COST_PER_RUN=5.0

# NOTE: Notion НЕ используется в v1 (результат отдаётся .md файлом).
# NOTE: Apollo НЕ используется в recruiter_assistant (только в 05_refind/scripts/).
```

### 2.6a config/whitelist.example.json

Создать `config/whitelist.example.json` (коммитится; реальный `whitelist.json` — нет):

```jsonc
{
  "users": [
    {
      "telegram_user_id": "<INT — telegram user id, см. /start у @userinfobot>",
      "display_name": "<friendly name>"
    }
  ]
}
```

Whitelist в v1 — просто список разрешённых `telegram_user_id`. Notion-полей нет (Notion ушёл в v2), почты нет.

### 2.7 requirements.txt

Собрать из существующих зависимостей `05_refind/services/recruiter_assistant/` + добавить:
- `python-telegram-bot` (для бота)
- (sqlite3 в stdlib, ничего не нужно)

**НЕ добавлять:** `claude-agent-sdk` (LLM-агента в v1 нет), `notion-client` (Notion в v1 нет).

### 2.8 README.md

Минимально:
- Что это за проект
- Структура (core/, bot/, db/)
- Как запустить ручной прогон
- Как запустить бота (заглушка на потом)

### 2.9 Git init + первый коммит

```bash
cd recruiter_assistant
git init
git add .
git commit -m "feat: initial migration from 05_refind/services/recruiter_assistant"
gh repo create recruiter_assistant --private --source=. --remote=origin --push
```

## Критерии готовности

**Фаза A — новый репо (НЕ трогаем 05_refind):**
- [x] Новый репо создан, структура соответствует PLAN.md
- [x] **Только код** скопирован в `core/` (boolean_generator, candidate_screener, PIPELINE_*.md). `clients/`, `candidates/`, `test_results/` НЕ копировались
- [x] Audit imports: `grep -rn "^from candidate_screener\|^from boolean_generator" core/` — нет absolute imports на пакеты
- [x] `core/utils/env.py` создан с `load_project_env()`
- [x] `load_dotenv` убран из библиотечных модулей, остался только в entry-point CLI
- [x] Импорты работают: `python -m core.boolean_generator.generator ...` запускается
- [x] Smoke test: boolean_generator запускается из нового репо с явным путём к vacancy.md в 05_refind
- [x] `.gitignore` исключает `data/`, `.env`, `*.db`, `config/whitelist.json`
- [x] `.env.example` создан (без Notion/agent-переменных)
- [x] `config/whitelist.example.json` создан (только telegram_user_id + display_name)
- [x] `config/whitelist.json` НЕ создан в репо
- [ ] `requirements.txt` собран — `pip install` в чистом venv ещё не проверялся (зависимости стоят в системном Python, smoke test косвенно подтвердил; явная проверка venv — на step_7)
- [x] README с инструкциями по ручному запуску
- [x] Первый коммит запушен на GitHub (`9628acf` → origin/main, https://github.com/renatmannanov/recruiter_assistant), проверено через `git ls-tree origin/main`: 60 файлов, секретов нет

**Фаза B — лёгкое обновление 05_refind (05_refind/services/ НЕ трогаем):**
- [ ] `05_refind/CLAUDE.md` обновлён — добавлена секция "Связанные проекты"
- [ ] Auto-memory скопирована в новый репо согласно step_1.5 (из 05_refind не удаляется)
- [ ] Smoke test 05_refind: `enrich_contacts.py`, `discover_people.py` работают как раньше
