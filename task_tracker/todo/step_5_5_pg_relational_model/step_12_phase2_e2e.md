# Шаг 12: Phase 2 E2E через бот

> Зависит от: step_11
> Статус: [ ] pending

## Задача

Прогнать полный сценарий с новой моделью через живой Telegram:
1. Базовый `/refind_vacancy` — должен создать vacancy + search + candidates +
   candidate_screenings.
2. `/vacancies` — должна показать созданную вакансию.
3. `/vacancy <id>` — карточка с правильной статистикой.
4. `/candidate <linkedin_url>` — карточка одного из найденных кандидатов.
5. `/runs` — показывает свежий run.
6. `/rescreen <run_id> <new_vacancy_id>` — для новой вакансии (создать руками
   через `/refind_vacancy` второй раз) — прогон БЕЗ Apify, только OpenAI.
7. Проверить что один и тот же LinkedIn-URL = одна строка в `candidates`,
   но 2 строки в `candidate_screenings` (по двум вакансиям).
8. `replies.PIPELINE_DONE` должен показывать "X из 25 кандидатов уже видели"
   во втором прогоне.

## Сценарий (по шагам в TG)

1. **Запустить бот:** `python -m bot.main`
2. **Чистая БД:** убедиться что PG-таблицы пустые
   (или дропнуть-восстановить через `--init`).
3. **Чат:**
   - `/start`
   - `/refind_vacancy` → отправить JD #1 (Python role, Berlin)
   - "ок" на предложенный boolean
   - Дождаться отчёта. Сохранить `run_id`, `session_id`.
4. **Чат:** `/vacancies` — должна быть 1 вакансия.
5. **Чат:** `/vacancy 1` — карточка с searches=1, runs=1, screenings=25.
6. **Чат:** `/runs` — 1 run.
7. **Чат:** `/candidate <первый-url-из-отчёта>` — карточка с 1 screening.
8. **Чат:**
   - `/refind_vacancy` → отправить JD #2 (Python role, **другой** контекст —
     skewed toward seniors)
   - "ок"
   - Дождаться отчёта. Должно прийти сообщение PIPELINE_DONE с пометкой
     "X из 25 уже видели" (если Apify нашёл пересечение).
9. **Чат:** `/rescreen <run_id_1> 2` — прогнать кандидатов из run #1 на
   вакансии #2.
10. **Проверить:**
    - В `candidates` 25 (или больше, если JD #2 нашёл новых) уникальных
      строк.
    - В `candidate_screenings` минимум 25 + 25 (или больше) записей —
      по две на каждого кандидата если он попал в оба прогона.
11. **Чат:** `/candidate <тот-же-url>` — должна показать 2 скрининга (или 3
    с rescreen).

## Команды для верификации

```bash
# Проверить уникальность candidates
python -c "
import asyncio, os, asyncpg
from dotenv import load_dotenv; load_dotenv()
async def main():
    conn = await asyncpg.connect(...)  # from env
    n_uniq = await conn.fetchval('SELECT count(*) FROM candidates')
    n_screenings = await conn.fetchval('SELECT count(*) FROM candidate_screenings')
    print(f'candidates: {n_uniq}, screenings: {n_screenings}')
    await conn.close()
asyncio.run(main())
"
```

## Критерии готовности

- [ ] Базовый `/refind_vacancy` создаёт vacancy + search + 25 candidates + 25 screenings
- [ ] `/vacancies`, `/vacancy <id>`, `/runs`, `/candidate <url>` отвечают корректно
- [ ] Второй прогон не дублирует кандидатов в `candidates` (UNIQUE linkedin_url работает)
- [ ] PIPELINE_DONE показывает "X из 25 уже видели" во втором прогоне
- [ ] `/rescreen` создаёт новые screenings БЕЗ Apify-стоимости
- [ ] `/candidate` показывает 2-3 screenings на одного человека
- [ ] Никаких ошибок в логах
- [ ] Результаты записаны в `progress.md` (фактические числа и cost)
