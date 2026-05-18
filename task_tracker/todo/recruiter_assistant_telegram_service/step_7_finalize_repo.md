# Step 7: Финализация репо перед деплоем

> Статус: pending
> Зависит от: step_4-step_6 (бот работает локально end-to-end)

## Цель

Привести проект в состояние "готов к деплою на Mac mini". Финальная проверка: все файлы на месте, документация написана, секреты не в git.

## Что делаем

### 7.1 requirements.txt — финальный аудит

```bash
cd recruiter_assistant
.venv/bin/pip freeze > /tmp/installed.txt
# Сравнить с requirements.txt
```

Минимальный набор (зафиксировать версии):
- `python-telegram-bot>=21,<22`
- `openai>=1.0`
- `apify-client>=1.0`
- `python-dotenv>=1.0`

**НЕ должно быть:** `claude-agent-sdk` (LLM-агента в v1 нет), `notion-client` (Notion в v1 нет).

### 7.2 .env.example — финальная проверка

```
TELEGRAM_BOT_TOKEN=
OPEN_AI_KEY=sk-...
APIFY_AI_TOKEN=apify_api_...

OPENAI_MODEL=gpt-4o
BOOLEAN_MODEL=gpt-4o
SCREENING_MODEL=gpt-4o

DB_PATH=./data/recruiter_assistant.db
WHITELIST_PATH=./config/whitelist.json
MAX_COST_PER_RUN=5.0    # circuit breaker, см. step_8
```

(Без Notion-токена, без agent-переменных.)

### 7.3 README.md — инструкции локального запуска

Структура README:
1. Что это (одна строка)
2. Архитектура (одна схема: core/ + bot/ + db/)
3. Локальный запуск:
   - clone repo
   - venv + `pip install -r requirements.txt`
   - cp .env.example → .env, заполнить токены
   - cp config/whitelist.example.json → whitelist.json, вписать свой telegram_user_id
   - `python -m db.client --init`
   - `python -m bot.main`
4. Ручные прогоны через CLI (для отладки):
   - vacancy → candidates: `python -m core.boolean_generator.generator ...`
   - cv → jobs: `python -m core.candidate_screener.cli.run_jobs ...`
5. Ссылки на детали:
   - `docs/DEPLOY_MACMINI.md` — деплой на Mac mini (создаётся на step_8)
   - `task_tracker/` — текущие задачи

### 7.4 Финальный smoke test локально

Прогнать оба пайплайна end-to-end через локального dev-бота:
1. `/refind_vacancy` + реальная JD → boolean → "ок" → `report.md` приходит файлом в TG
2. `/refind_vacancy` + vacancy.md + brief.md (2 файла) → boolean с brief → "ок" → отчёт
3. `/refind_candidate` + реальное CV → boolean → правка → "ок" → `report.md` в TG
4. `/cancel` отменяет сессию
5. Не-whitelisted юзер получает отказ
6. `/status` показывает текущую сессию
7. SQLite-проверка через CLI: `sqlite3 data/recruiter_assistant.db "SELECT * FROM sessions"`

### 7.5 Git состояние перед деплоем

- [ ] Все изменения закоммичены
- [ ] `.env` НЕ в git (`git status` чистый)
- [ ] `config/whitelist.json` НЕ в git
- [ ] `data/` НЕ в git
- [ ] Запушено в origin: `git push origin main`

## Критерии готовности

- [ ] requirements.txt с зафиксированными версиями (без claude-agent-sdk, без notion-client)
- [ ] .env.example полный (без Notion/agent-переменных)
- [ ] README.md с инструкциями локального запуска
- [ ] Локальный smoke test обоих пайплайнов прошёл (результат — .md файл в TG)
- [ ] Git чистый, .env / whitelist.json / data/ не в репо
- [ ] Push на GitHub успешен
