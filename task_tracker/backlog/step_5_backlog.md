# Backlog from step_5 (vacancy → candidates wiring)

Темы, отложенные во время step_5. Не блокируют step_5, но возвращаемся к ним
после step_6 (cv → jobs) или до деплоя.

## Apify — реальный cost_usd

В `core/candidate_screener/core/discover.py` cost считается грубой эвристикой
($0.20/страница). Apify run object возвращает реальную стоимость через
`run["usage"]` или `run["stats"]` (зависит от actor'а) — её надо протащить:

1. В `core/candidate_screener/sources/from_apify_search.py`:
   `search_linkedin_profiles()` сейчас возвращает `(items, total)`. Расширить
   до `(items, total, cost_usd)` (или вернуть `dict`).
2. В `discover_candidates()` пробросить.
3. CLI `discover.py` (Notion-флоу) принимает изменение прозрачно.

Why: учёт стоимости в `runs.cost_usd` нужен для аналитики (когда подключим
веб-интерфейс из v2 бэклога) — приближение в 20% точности уже сейчас вводит
в заблуждение для multi-page прогонов.

## Locations / experience / seniority — извлекать из boolean_generator

В v1 бот зовёт `discover_candidates(boolean, locations=None, pages=1)` —
никакой геолокации, опыта, сеньорности. На реальных вакансиях это сильно
бьёт по качеству выдачи (Германия — кандидат из Бразилии в боолевый запрос
не должен попадать).

`boolean_generator` уже выдаёт markdown с секциями `## Apify params`
(locations, experience, seniority — оператор копипастит в CLI). Нужно:

1. Парсить эти секции из markdown-ответа LLM.
2. Сохранять параметры в `sessions` (новые колонки: `apify_locations`,
   `apify_experience`, `apify_seniority` — или один JSON-блоб).
3. Прокидывать в `discover_candidates()`.
4. Опционально: позволить юзеру отредактировать их (как сейчас boolean) —
   но это уже расширение state-машины (новый шаг `WAITING_PARAMS_CONFIRM`).

Why: ASR-кейс на Sonia показал что Apify params (особенно locations) — это
не "дополнение к boolean", а **критично важная часть** запроса.

## vacancy_name для отчёта — извлекать из boolean LLM-ответа

Сейчас отчёт у юзера называется `session_42` — функционально, но безлико.
LLM в `boolean_generator` уже строит короткую сводку вакансии в reasoning;
можно попросить отдельным полем в системном промпте `## Vacancy summary`
(одна строка типа "Senior Python @ Germany") и подставлять в
`format_markdown_report(vacancy_name=...)`.

Why: при работе с несколькими сессиями подряд отчёты `session_41`,
`session_42`, `session_43` неотличимы — нужен человекочитаемый якорь.

## from_apify_search.py — убрать sys.exit, добавить ApifyError

`search_linkedin_profiles()` делает `sys.exit(1)` если нет
`APIFY_AI_TOKEN_V2` — это плохо для библиотечной функции (бот не должен
умирать процессом из-за отсутствия токена). Бросать кастомный
`ApifyError` / `EnvironmentError`, CLI ловит и печатает сам.

## Прогресс прогона — статусы в одном редактируемом TG-сообщении

Сейчас юзер отправил `ок` и получает только `PIPELINE_STARTED`
("Запускаю поиск… 1-2 минуты"), потом тишина до `PIPELINE_DONE` с
report.md. На длинных прогонах (CV→jobs до 3 мин) — тревожно.

Идея: после `PIPELINE_STARTED` бот сохраняет `chat_id + message_id`
этого сообщения и **редактирует** его через `bot.edit_message_text`
на каждом значимом шаге пайплайна:

```
[1/4] Запускаю поиск...
[1/4] Apify: нашёл 4510 профилей, забираю страницу 1 (25 шт)
[2/4] Дедуп: 3 уже видели, 22 новых на скрининг
[3/4] Скрининг через gpt-4o... [12/22]
[4/4] Готово ✅
```

Как реализовать чисто:

1. В `pipelines.run_pipeline(...)` добавить опциональный
   `on_status: Callable[[str], Awaitable[None]] | None` — async callback,
   pipelines дёргают на каждом шаге.
2. В `bot/handlers.py` после `PIPELINE_STARTED` запомнить
   `status_msg = await reply_text(PIPELINE_STARTED)`, передать в pipeline
   `on_status=lambda text: status_msg.edit_text(text)`.
3. Для прогресса screening — `screen_runner.screen_candidates` уже
   принимает `on_progress` (i, total, name, score, recommendation,
   usage_total) — нужен мост в async (`on_status` синхронный нельзя
   звать из to_thread напрямую, нужен `asyncio.run_coroutine_threadsafe`
   или промежуточный buffer).

Why: текущая модель "запускаю → тишина → результат" нормальна на 30
секундах, но мы делаем 1-3 минуты — без статуса юзер не знает, бот живой
или повис. Edit одного сообщения чище чем 5 новых.

Подводные камни: Telegram rate-limit на edit_message_text (~1 в секунду на
chat). Скрининг 25 кандидатов = до 25 эдитов — нужно троттлить
(обновлять каждые ~3 секунды или каждый N-й кандидат).

## CLI discover.py — отделить от Notion

Сейчас `cli/discover.py` обязательно требует `--config` + `--vacancy` +
читает Notion. Если хочется просто Apify search без Notion (что бот и
делает через `core.discover_candidates`), CLI не помогает. Сделать Notion-
dedup опциональным через флаг `--dedup-notion`.

Why: единая точка входа полезна и для ручных прогонов вне Notion-флоу.
