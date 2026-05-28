# Шаг 6: Phase 1 E2E через бот

> Зависит от: step_5
> Статус: [ ] pending

## Задача

Проверить, что бот работает на PG end-to-end. Это контрольная точка перед
переходом на новую модель (фаза 2).

Тест проводится **через живой Telegram** с реальным `/refind_vacancy` —
но без реального Apify (использовать сохранённый `data/sessions/4/raw_apify.json`
через resume-logic) или с минимальным Apify-прогоном (если предыдущие dumps
почищены).

## Конкретные действия

1. Убедиться что бот запускается:
   ```bash
   python -m bot.main
   # ожидаем 'Application started'
   ```
2. На Mac mini БД пустая после миграции. Юзер ещё не зарегистрирован.
3. В Telegram отправить `/start` → должен прийти приветственный текст.
4. Проверить через PG что юзер появился:
   ```sql
   SELECT * FROM users;
   ```
5. Отправить `/refind_vacancy` → бот спрашивает JD.
6. Отправить короткий JD текстом (синтетический, типа "Senior Python Engineer,
   Germany, FastAPI"):
   - generate_boolean уйдёт в OpenAI (~$0.01)
   - вернётся boolean
7. Ответить "ок" — пайплайн пойдёт.
8. Бот сделает Apify-прогон (1 страница, ~$0.20), screening (~$0.50).
9. Получить `report.md`, проверить что:
   - В PG таблица `runs` имеет запись (status=done)
   - В PG таблица `candidates_found` содержит 25 строк
   - `sessions.step = 'done'`, `sessions.report_path` указывает на файл
10. Скрин/лог в `progress.md`: счётчики, время прогона, total cost.

## Тесты

Юнит-тесты уже зелёные (step_5). На этом шаге — только live e2e.

## Команды для верификации

```bash
# Бот стартует
python -m bot.main &
BOT_PID=$!

# Проверить через psql (или один-строчный python) что бот пишет в PG
python -c "
import asyncio, os
from dotenv import load_dotenv; load_dotenv()
import asyncpg
async def main():
    conn = await asyncpg.connect(host=os.environ['PG_HOST'], port=int(os.environ['PG_PORT']), user=os.environ['PG_USER'], password=os.environ['PG_PASSWORD'], database=os.environ['PG_DATABASE'])
    for tbl in ['users', 'sessions', 'runs', 'candidates_found']:
        n = await conn.fetchval(f'SELECT count(*) FROM {tbl}')
        print(f'{tbl}: {n}')
    await conn.close()
asyncio.run(main())
"

# Стопнуть бот
kill $BOT_PID
```

## Критерии готовности

- [ ] Бот запускается на PG, держит polling
- [ ] `/refind_vacancy` → boolean → ок → report.md проходит end-to-end
- [ ] В PG создаются записи: 1 user, 1 session, 1 run, 25 candidates_found
- [ ] `sessions.step = 'done'`, `runs.status = 'done'`
- [ ] Резюме записано в `progress.md` (фактические числа и cost)
- [ ] Никаких ошибок в логах бота
