# Recruiter Pipeline — runbook

> **Если ты агент и тебе сказали "найди кандидатов / прогони скрининг / запушь в Notion" — ЭТО точка входа.**
> Не пиши код заново, не выдумывай команды. Найди свой сценарий ниже.

---

## Сценарий A: Новые кандидаты на вакансию (vacancy → Notion)

**Когда:** "найди кандидатов на <вакансию>", "наполни воронку", "запусти discover".

### 1. Boolean + Apify params (одна команда)

```bash
python -m boolean_generator.generator \
  clients/<client>/<vacancy>/vacancy.md \
  --brief clients/<client>/<vacancy>/brief.md
```

Что произойдёт:
- В файл `clients/<client>/<vacancy>/boolean.md` сохранится **plain boolean string** (используется discover'ом автоматически)
- В **stdout** напечатается полный markdown с секциями Boolean / Apify params / Reasoning / **Ready-to-run**
- Секция Ready-to-run содержит готовую команду для шага 2 — копипаст в терминал

Если `boolean.md` уже существует — генератор печатает его и просит `--force` для перегенерации.

### 2. Discover — search + dedup

Скопировать команду из секции **Ready-to-run** (вывод шага 1) и запустить **сразу с `--output`** (без отдельного `--dry-run`).

```bash
# из stdout шага 1
python -m candidate_screener.cli.discover \
  --config clients/<client>/config.yaml \
  --vacancy <vacancy_key> \
  --locations <locations> \
  --experience <experience> \
  --exclude-titles <excludes> \
  --pages 1 \
  --output candidate_screener/test_results/<client>_<vacancy>_new.json
```

В stdout сразу видны счётчики `found / existing / new` и топ имён — этого достаточно для проверки качества выдачи. JSON сохранится автоматически.

> **Не запускай `--dry-run` отдельно** — он стоит столько же ($0.20 Apify), сколько и реальный прогон, и не даёт ничего нового. Если выдача плохая — просто не идём в шаг 3, JSON-файл удалить бесплатно. Используй `--dry-run` только если вообще не хочешь сохранять JSON (например, прикидываешь стоимость или дебажишь параметры).

### 3. Screen + push

```bash
python -m candidate_screener.cli.run_local \
  --profiles candidate_screener/test_results/<client>_<vacancy>_new.json \
  --vacancy clients/<client>/<vacancy>/vacancy.md \
  --brief clients/<client>/<vacancy>/brief.md \
  --config clients/<client>/config.yaml \
  --vacancy-key <vacancy_key> \
  --push-to-notion
```

После: новые карточки в Notion с `Name`, `Linkedin_url`, `Vacancy`, `ai_score`, `ai_status`, `ai_comment`, `ai_iteration`.

**Первый раз на новой вакансии** — обязательно запустить с `--limit 1` сначала, проверить что 1 карточка корректно создалась, и только потом снимать лимит.

---

## Сценарий B: Перегон существующих в Notion (поменялся brief / промпт)

**Когда:** "перегон скрининг", "обновили brief", "новая итерация по существующим".

```bash
python -m candidate_screener.cli.run_notion \
  --config clients/<client>/config.yaml \
  --vacancy <vacancy_key>
```

`ai_iteration` инкрементнется автоматически (max+1 per-vacancy).
Берёт всех кандидатов с `Vacancy = <filter_value>` из Notion, скринит, апдейтит страницы.

> Опциональный `--dry-run` для `run_notion` **бесплатный** (не дёргает Apify/OpenAI, только читает Notion и показывает кого нашёл). Используй если хочешь сначала увидеть список кандидатов — например, чтобы прикинуть стоимость скрининга или убедиться что фильтр настроен правильно.

---

## Сценарий C: Калибровка промпта на 1-3 кандидатах

**Когда:** "потести промпт", "проверь brief на одном", "посмотри как AI оценит этого".

```bash
python -m candidate_screener.cli.run_local \
  --profiles candidate_screener/test_results/<existing>.json \
  --vacancy clients/<client>/<vacancy>/vacancy.md \
  --brief clients/<client>/<vacancy>/brief.md \
  --limit 1 \
  --output candidate_screener/test_results/calibration.md
```

В Notion **НЕ пушим** (без `--push-to-notion`). Только markdown отчёт.

---

## Где что лежит

| Что | Путь |
|-----|------|
| JD клиента | `clients/<client>/<vacancy>/vacancy.md` |
| Internal brief | `clients/<client>/<vacancy>/brief.md` |
| Boolean | `clients/<client>/<vacancy>/boolean.md` |
| Notion config | `clients/<client>/config.yaml` |
| Промежуточные JSON | `candidate_screener/test_results/` |
| Markdown отчёты | `candidate_screener/test_results/` |

## Какой файл за что отвечает

| Слой | Файлы | Ответственность |
|------|-------|-----------------|
| `core/` | screener.py, prompts_candidates.py, profile_cleaner.py, response_parser.py, report.py | Логика скрининга, без I/O |
| `sources/` | from_notion, from_apify_search, from_apify_urls, from_json | Чтение |
| `sinks/` | to_notion, to_markdown, to_json | Запись |
| `cli/` | discover, run_local, run_notion | **Оркестрация — вся логика pipeline здесь** |

Запись в Notion: `update_page` (PATCH существующей), `create_page` (POST новой), `build_properties` (общая сборка). Не дублируй HTTP-логику.

---

## Чего НЕ делать

- ❌ НЕ писать новые CLI без необходимости. Комбинируй существующие.
- ❌ НЕ обходить дедуп в discover — это деньги (Apify $0.004/full профиль).
- ❌ НЕ дублировать логику записи в Notion — `build_properties` + `update_page`/`create_page` уже всё умеют.
- ❌ НЕ запускать `--push-to-notion` без `--limit 1` сначала на новой вакансии — проверь маппинг полей.
- ❌ НЕ забывать brief — без `--brief` AI-скоринг работает только по JD, теряет priority signals.
- ❌ НЕ вычислять `ai_iteration` руками — `run_notion` и `run_local --push-to-notion` ставят сами (max+1).
- ❌ НЕ удалять карточки из Notion без явного "да" от пользователя (см. глобальный CLAUDE.md).
- ❌ НЕ запускать `discover --dry-run` отдельно перед реальным прогоном. Цена та же ($0.20 Apify), JSON-файл легко удалить если выдача плохая. Запускай сразу с `--output`.
