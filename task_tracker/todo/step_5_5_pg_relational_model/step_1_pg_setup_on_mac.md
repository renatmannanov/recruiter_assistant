# Шаг 1: PG на Mac mini + сетевой доступ с Windows

> Зависит от: нет
> Статус: [x] done (2026-05-28)

## Задача

Поднять Postgres-инстанс на Mac mini (если ещё нет), создать БД
`recruiter_assistant_dev`, выдать сетевой доступ с Windows-машины Рената,
заполнить `.env` параметрами подключения.

Это инфраструктурный шаг. Часть требует физического доступа к маку — Ренат
выполняет на Mac mini, агент с Windows-машины помогает командами и
проверяет подключение.

## Конкретные действия

1. **На Mac mini** (Ренат): проверить наличие PG (`brew services list | grep postgres`).
   Если нет — установить через `brew install postgresql@16 && brew services start postgresql@16`.
2. **На Mac mini**: создать БД и роль:
   ```sql
   CREATE ROLE recruiter_assistant WITH LOGIN PASSWORD '<пароль>';
   CREATE DATABASE recruiter_assistant_dev OWNER recruiter_assistant;
   ```
3. **На Mac mini**: настроить сетевой доступ.
   - В `postgresql.conf`: `listen_addresses = '*'`
   - В `pg_hba.conf` добавить строку для IP Windows-машины (или `0.0.0.0/0` если за NAT):
     ```
     host    recruiter_assistant_dev    recruiter_assistant    <windows_ip>/32    scram-sha-256
     ```
   - Перезапустить: `brew services restart postgresql@16`
4. **На Windows** (агент): обновить `.env`, добавить переменные:
   ```
   PG_HOST=<mac_ip_in_lan>
   PG_PORT=5432
   PG_USER=recruiter_assistant
   PG_PASSWORD=<пароль>
   PG_DATABASE=recruiter_assistant_dev
   ```
5. **На Windows**: обновить `.env.example` теми же ключами (без значений).
6. **На Windows**: установить `asyncpg`:
   ```
   pip install asyncpg
   ```
   Добавить в `requirements.txt`: `asyncpg>=0.29`.

## Тесты

- Smoke-test через CLI psql (если установлен) или однострочник на Python:
  ```python
  python -c "import asyncio, asyncpg, os; asyncio.run(asyncpg.connect(host=os.environ['PG_HOST'], port=int(os.environ['PG_PORT']), user=os.environ['PG_USER'], password=os.environ['PG_PASSWORD'], database=os.environ['PG_DATABASE']).close())"
  ```
- Никаких новых юнит-тестов на этом шаге.

## Команды для верификации

```bash
# С Windows: проверить, что Python может подключиться
python -c "import asyncio, asyncpg, os; from dotenv import load_dotenv; load_dotenv(); asyncio.run(asyncpg.connect(host=os.environ['PG_HOST'], port=int(os.environ['PG_PORT']), user=os.environ['PG_USER'], password=os.environ['PG_PASSWORD'], database=os.environ['PG_DATABASE']).close()); print('PG OK')"

# Проверить, что pip-зависимость зафиксирована
grep asyncpg requirements.txt
```

## Критерии готовности

- [ ] Postgres работает на Mac mini, `recruiter_assistant_dev` создана
- [ ] С Windows-машины успешно открывается соединение через `asyncpg`
- [ ] `.env` содержит PG_* переменные, `.env.example` синхронизирован
- [ ] `asyncpg>=0.29` в `requirements.txt`, `pip install -r requirements.txt` проходит чисто
- [ ] В `progress.md` записан финальный способ подключения (Tailscale / прямой LAN / SSH-туннель)
