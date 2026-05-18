# Step 8: Деплой на Mac mini

> Статус: pending
> Зависит от: step_7 (репо финализирован, push на GitHub)

## Цель

Задеплоить проект на **Mac mini** (уже настроен, не уходит в сон), путь `~/projects/recruiter_assistant/`. Автозапуск через **launchd** (macOS-аналог systemd). Проверить что бот отвечает через TG.

## Почему Mac mini, а не VPS

- Mac mini уже куплен и настроен — $0 аренды
- Следующая итерация (v2) — локальная модель для screening, её тянет только Mac mini (M-чип, унифицированная память). Деплоить дважды (VPS → потом Mac mini) — лишняя работа
- Telegram-бот в **polling-режиме** ходит к серверам Telegram сам (исходящие соединения) — белый IP и проброс портов **не нужны**. Mac mini за домашним роутером работает нормально
- Риск — аптайм (домашний свет/интернет). Для v1 (пользователь = Ренат + тестовый аккаунт) не критично

## Предусловия

- [ ] Mac mini доступен по ssh с машины Рената, постоянно включён, не уходит в сон
- [ ] Python 3.11+ установлен на Mac mini (`python3 --version`)
- [ ] Git установлен, доступ к GitHub-репо настроен (ssh-ключ или gh auth)

## Действия

### 8.1 Настройка Mac mini — не спать

Убедиться что Mac mini не уходит в сон (иначе бот офлайн):

```bash
# Проверить текущие настройки
pmset -g

# Запретить сон системы (требует sudo)
sudo pmset -a sleep 0
sudo pmset -a disksleep 0
# displaysleep можно оставить — экран гаснет, система работает
```

Дополнительно: System Settings → Energy → снять «Put hard disks to sleep», включить «Start up automatically after a power failure» (на случай отключения света).

### 8.2 Клонировать репо

```bash
ssh macmini "mkdir -p ~/projects && cd ~/projects && git clone <repo_url> recruiter_assistant"
```

Финальный путь: `~/projects/recruiter_assistant/`.

### 8.3 Создать venv

```bash
ssh macmini "cd ~/projects/recruiter_assistant && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
```

### 8.4 Создать .env

Скопировать секреты с локальной машины (никогда не коммитим в git).

```bash
scp .env.production macmini:~/projects/recruiter_assistant/.env
ssh macmini "chmod 600 ~/projects/recruiter_assistant/.env"
```

`.env` на Mac mini содержит **production** TG токен (отдельный бот), production OpenAI/Apify токены.

**Решение:** dev и prod бот = два разных TG-бота (два разных токена). Локально работаем с dev-ботом, на Mac mini — prod-бот.

> Production-бот создаётся через @BotFather на этом шаге. Username — на выбор Рената (например `@rm_recruiter_assistant_bot`). Записать username в README и в step_9 (e2e через него).

### 8.5 Инициализировать БД

```bash
ssh macmini "cd ~/projects/recruiter_assistant && .venv/bin/python -m db.client --init"
```

(создаст `data/recruiter_assistant.db` из `db/schema.sql`)

### 8.6 Создать config/whitelist.json на Mac mini

С production telegram_user_id (Ренат основной = 423915315 + опционально тестовый). Не коммитим, создаём руками с `chmod 600`.

```bash
ssh macmini "chmod 600 ~/projects/recruiter_assistant/config/whitelist.json"
```

### 8.7 Запуск бота через launchd

Создать `~/Library/LaunchAgents/work.refind.recruiter-assistant-bot.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>work.refind.recruiter-assistant-bot</string>

    <key>ProgramArguments</key>
    <array>
        <string>/Users/<USER>/projects/recruiter_assistant/.venv/bin/python</string>
        <string>-m</string>
        <string>bot.main</string>
    </array>

    <key>WorkingDirectory</key>
    <string>/Users/<USER>/projects/recruiter_assistant</string>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>/Users/<USER>/projects/recruiter_assistant/data/bot.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/<USER>/projects/recruiter_assistant/data/bot.error.log</string>
</dict>
</plist>
```

**Примечание про .env:** launchd не читает `EnvironmentFile` как systemd. Переменные окружения подхватываются внутри `bot/main.py` через `load_project_env()` (из `core/utils/env.py`) — он читает `.env` из корня репо. Этого достаточно, отдельной настройки env в plist не нужно.

Загрузка:
```bash
launchctl load ~/Library/LaunchAgents/work.refind.recruiter-assistant-bot.plist
launchctl list | grep recruiter          # проверить что запущен
```

Управление:
```bash
launchctl unload .../work.refind.recruiter-assistant-bot.plist   # остановить
launchctl load   .../work.refind.recruiter-assistant-bot.plist   # запустить
# рестарт после git pull = unload + load
```

`KeepAlive=true` — launchd перезапустит бот если упал (аналог `Restart=always` в systemd).

### 8.8 Логи

```bash
ssh macmini "tail -f ~/projects/recruiter_assistant/data/bot.log"
ssh macmini "tail -f ~/projects/recruiter_assistant/data/bot.error.log"
```

### 8.9 Graceful shutdown и cleanup при рестарте

При `git pull` + рестарт активные пайплайны (asyncio tasks в `running`) убиваются на полпути. Сессии в БД остаются в `running` навсегда.

**a) При старте бота — cleanup stale sessions:**

В `bot/main.py`:
```python
async def main():
    db = DB(os.environ["DB_PATH"])
    cleaned = db.cleanup_stale_sessions(older_than_minutes=5)
    if cleaned > 0:
        logging.warning(f"Marked {cleaned} stale sessions as error at startup")
    # ... запуск бота
```

`cleanup_stale_sessions` (определена в step_3): находит `step='running'` старше N минут → `step='error'`, `error_text='restarted_or_stalled'`.

**b) Periodic cleanup в фоне:**

```python
async def periodic_cleanup(db):
    while True:
        await asyncio.sleep(600)  # каждые 10 минут
        db.cleanup_stale_sessions(older_than_minutes=30)
```

**c) Деплой v1 — просто:**

```bash
ssh macmini "cd ~/projects/recruiter_assistant && git pull"
ssh macmini "launchctl unload ~/Library/LaunchAgents/work.refind.recruiter-assistant-bot.plist && launchctl load ~/Library/LaunchAgents/work.refind.recruiter-assistant-bot.plist"
```

cleanup_stale_sessions при старте гарантирует что зависшие сессии не останутся навсегда.

### 8.10 docs/DEPLOY_MACMINI.md

Записать в `docs/DEPLOY_MACMINI.md` нового репо: всё из этого шага (настройка не-спать, launchd plist, команды деплоя/рестарта, где логи). Чтобы будущий деплой / переустановка не требовали этот task_tracker.

### 8.11 Smoke test через TG

С production-аккаунта Рената:
- Открыть production-бота в TG
- `/start` → приветствие
- `/refind_vacancy` → "пришли вакансию" → короткий тестовый JD → boolean → "ок" → подождать → `report.md` файлом
- То же для `/refind_candidate`

## Безопасность (обязательные шаги — БЛОКИРУЮТ деплой)

- [ ] `.env` имеет права 600
- [ ] `config/whitelist.json` имеет права 600
- [ ] **OpenAI hard limit** через OpenAI dashboard: `Settings → Limits → Monthly budget` (рекомендация v1: $50). Проверено: при превышении API возвращает 429
- [ ] **Apify hard limit** через Apify Console: `Settings → Limits` (рекомендация v1: $30)
- [ ] **Cost circuit breaker в коде:** в `bot/pipelines.py` — если `run.cost_usd > MAX_COST_PER_RUN` (env, default $5) → `fail_run`, юзеру `❌ Прогон превысил лимит стоимости, прерван`

## Критерии готовности

- [ ] Mac mini не уходит в сон (`pmset` настроен)
- [ ] Репо склонирован на Mac mini в `~/projects/recruiter_assistant/`
- [ ] Venv создан, зависимости установлены
- [ ] БД инициализирована (`python -m db.client --init`), WAL режим проверен
- [ ] .env и whitelist.json на месте, права 600
- [ ] **Все пункты "Безопасность" выполнены**
- [ ] Production TG-бот создан через @BotFather, username записан в README
- [ ] launchd-агент создан и загружен (`launchctl list` показывает бота)
- [ ] `KeepAlive` перезапускает бот при падении (тест: kill процесса → launchd поднял)
- [ ] cleanup_stale_sessions вызывается при старте, periodic cleanup запущен
- [ ] Логи пишутся в `data/bot.log` / `data/bot.error.log`
- [ ] `/refind_vacancy` end-to-end через production-бота отрабатывает, `.md` приходит
- [ ] `/refind_candidate` end-to-end отрабатывает
- [ ] `docs/DEPLOY_MACMINI.md` написан
