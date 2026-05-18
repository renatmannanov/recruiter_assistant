# CV → Jobs Pipeline — runbook

> **Если ты агент и тебе сказали "найди вакансии для кандидата X" / "прогони CV → jobs" / "обнови jobs_results для X" — ЭТО точка входа.**
> Не пиши код заново, не выдумывай команды. Найди свой сценарий ниже.
>
> **Этот пайплайн обратный к [PIPELINE_vacancy_to_candidates.md](PIPELINE_vacancy_to_candidates.md).**
> Там: вакансия → кандидаты в Notion. Здесь: CV кандидата → открытые вакансии в EU + recruiter контакты для outreach.

---

## Когда какой пайплайн

| У тебя есть | Что хочешь | Используй |
|-------------|-----------|-----------|
| Открытая вакансия от клиента | Найти кандидатов и положить в Notion | [PIPELINE_vacancy_to_candidates.md](PIPELINE_vacancy_to_candidates.md) |
| Готовый кандидат (CV + brief) | Найти открытые вакансии в EU и recruiter контакты | **этот файл** |

---

## Что делает пайплайн

```
candidates/<name>/cv.md + brief.md
        ↓ (cv_parser, gpt-4o)
структурированный профиль (skills, seniority, locations)
        ↓ (boolean_generator --target jobs)
candidates/<name>/boolean.md  (LinkedIn boolean string)
        ↓ (run_jobs: Apify → screen → report)
candidates/<name>/jobs_results.md  (top matches + recruiter contacts)
candidates/<name>/runs/<timestamp>/  (полный архив итерации)
```

Бизнес-смысл: имея готового кандидата, заходим в TIER 1-2 компании через **их же** открытые вакансии. Outreach получает crispный hook: "у меня есть [имя] на вашу позицию [title]".

---

## Структура папки кандидата

```
services/recruiter_assistant/
└── candidates/
    └── <candidate-name>/
        ├── cv.md             ← резюме (markdown). PII — в .gitignore.
        ├── brief.md          ← visa, salary, locations, remote, blocklist, notes
        ├── config.yaml       ← пока почти пустой (Notion DB задел на будущее)
        ├── boolean.md        ← последний сгенерированный boolean (plain string)
        ├── jobs_results.md   ← последний отчёт (для quick read)
        └── runs/
            └── <YYYYMMDD_HHMMSS>/   ← каждая итерация поиска
                ├── boolean.md           ← boolean из этого прогона
                ├── search_params.json   ← все CLI-параметры
                ├── raw_jobs.json        ← сырой Apify dump (для re-screen без $)
                ├── screening_results.json  ← cleaned + scored результаты
                └── jobs_results.md      ← markdown отчёт этой итерации
```

`brief.md` — зеркало internal brief'а из `clients/`, но с другими секциями (visa/salary/locations/remote/blocklist).

---

## Сценарий A: Новый кандидат — найти ему вакансии (полный прогон)

**Когда:** "найди вакансии для <имя>", "прогони пайплайн на новом CV", "обнови jobs_results".

**Стоимость одного прогона на 10 jobs:** ~$0.012 Apify + ~$0.30-0.62 OpenAI = **~$0.50** (зависит от длины JD-текстов).

### 0. Подготовить папку кандидата

Положи в `candidates/<name>/`:
- `cv.md` — резюме на английском, markdown. Из PDF можно скопировать руками — форматирование не критично, парсер LLM-based.
- `brief.md` — заполни секции (см. шаблон в `candidates/test_python/brief.md`):
  - **Visa / sponsorship** — критично для EU search'а
  - **Locations open to** — города или страны
  - **Remote preference** — remote-only / hybrid / onsite
  - **Salary expectation** — TBD ОК
  - **Blocklist** — компании которые избегаем
- `config.yaml` — пока почти пустой (Notion DB задел на будущее, можно скопировать с `test_python`)

> **Без brief.md** скрининг работает только по CV, теряет visa filter и career direction.

### 1. Сгенерировать boolean (target=jobs)

```bash
cd services/recruiter_assistant

python -m boolean_generator.generator \
  candidates/<name>/cv.md \
  --brief candidates/<name>/brief.md
```

Что произойдёт:
- target автодетект `jobs` (по пути `candidates/`)
- CV распарсится через `cv_parser` (~$0.005 gpt-4o)
- Сгенерится boolean (~$0.01 gpt-4o)
- В `candidates/<name>/boolean.md` сохранится **plain boolean string**
- В **stdout** напечатается markdown: Boolean / Apify params / Reasoning / **Ready-to-run**

> Если `boolean.md` уже есть — генератор печатает его и просит `--force` для перегенерации.

**Сейчас промпт жёстко требует включать primary language anchor:**
- Для Go-разработчика: `(Go OR Golang) AND ("Backend Engineer" OR ...) AND (Senior OR ...)`
- Для ASR-специалиста (domain-anchored): `("Speech Scientist" OR "ASR Engineer" OR ...) AND (Senior OR ...)`
- Для EM роли (role-anchored, exception): без обязательного language gate.

### 2. Запустить run_jobs

Скопируй команду из секции **Ready-to-run** stdout'а шага 1, или собери руками:

```bash
python -m candidate_screener.cli.run_jobs \
  --candidate <name> \
  --locations "Germany" "Netherlands" "France" "Spain" \
  --experience senior \
  --posted-within past_month \
  --remote any \
  --count 10
```

Что произойдёт:
1. Прочтёт `candidates/<name>/cv.md` + `brief.md` + `boolean.md`
2. Apify-search через `curious_coder/linkedin-jobs-scraper` (~$0.012 за 10 jobs)
3. Каждый job: `clean_job` → `screen_job` (gpt-4o JD vs CV) → SCORE/RECOMMENDATION
4. Сохранит итерацию в `candidates/<name>/runs/<timestamp>/` (5 файлов)
5. Скопирует latest report в `candidates/<name>/jobs_results.md`

В stdout — счётчики `GO / MAYBE / SKIP` и стоимость.

### 3. Проверить результат

Открой `candidates/<name>/jobs_results.md`:
- **Top matches table** — ранжировано по score
- **Detailed evaluations** per-job — почему GO/MAYBE/SKIP, какие concerns, какие вопросы задать на intake call
- **Recruiter contact column** — имя + LinkedIn URL если есть в выдаче

> **Recruiter contact pattern:** обычно есть у staffing-агентств и mid-tier компаний (~30-60% jobs), реже у топовых (Datadog, Back Market и пр.). Если нет — outreach делается через careers page компании.

---

## Сценарий B: Перегон существующих jobs после правки промпта (без новой Apify-цены)

**Когда:** "поправил `prompts_jd_screening`, хочу перегон без нового Apify", "сравнить screening старого/нового промпта на тех же jobs".

В архиве `candidates/<name>/runs/<ts>/raw_jobs.json` лежит сырой Apify dump последнего прогона. Можно прогнать только OpenAI screening на нём (платим только OpenAI, не Apify).

> **Сейчас отдельного CLI под это нет** — пиши одноразовый скрипт в `_baseline_cv_to_jobs/` (`json.load(raw)` → `clean_job` → `screen_job` → `format_jobs_report`). Если такие итерации станут регулярными — добавим CLI флаг `--from-archive <ts>` в `run_jobs.py`.

---

## Сценарий C: Боолеан плох — итерация только на boolean (без screening'а)

**Когда:** boolean возвращает шумную выдачу (много irrelevant jobs), хочется покрутить query без полного прогона.

```bash
# Регенерировать boolean с новыми входами
python -m boolean_generator.generator \
  candidates/<name>/cv.md \
  --brief candidates/<name>/brief.md \
  --force

# Проверить URL без вызова Apify (бесплатно)
python -m candidate_screener.sources.from_apify_jobs \
  --query "$(cat candidates/<name>/boolean.md)" \
  --locations "Germany" "Netherlands" \
  --experience senior \
  --remote any \
  --dry-run
```

Глазами проверь финальный LinkedIn URL — попробуй открыть в incognito и посмотри что выдача релевантна.

---

## Где что лежит

| Что | Путь |
|-----|------|
| CV кандидата | `candidates/<name>/cv.md` |
| Candidate brief | `candidates/<name>/brief.md` |
| Boolean (последний) | `candidates/<name>/boolean.md` |
| Latest report | `candidates/<name>/jobs_results.md` |
| История итераций | `candidates/<name>/runs/<timestamp>/` |
| Тестовые данные / debugging | `_baseline_cv_to_jobs/` (в .gitignore) |

Вся папка `candidates/` в `.gitignore` — содержимое не попадает в git (PII).

## Какой файл за что отвечает

| Слой | Файлы | Ответственность |
|------|-------|-----------------|
| `boolean_generator/` | `generator.py`, `prompts_jobs.py`, `prompts_candidates.py` | Boolean для двух targets (`--target candidates|jobs`) |
| `core/` | `cv_parser.py`, `prompts_cv.py`, `screener.py`, `prompts_jd_screening.py`, `job_cleaner.py`, `report.py`, `response_parser.py` | Логика парсинга CV + JD-vs-CV скрининга, без I/O |
| `sources/` | `from_apify_jobs.py` | Apify Jobs Search + LinkedIn URL builder |
| `cli/` | `run_jobs.py` | **Оркестрация — вся логика pipeline здесь** |

---

## Apify actor: curious_coder/linkedin-jobs-scraper

- **Pricing:** $0.001 per result (минимум 10 jobs за один run = $0.010)
- **Input:** `{urls, count, scrapeCompany}` — NO native `experience`/`posted` фильтров.
  Все фильтры идут через **LinkedIn URL query params** — наш `build_linkedin_jobs_url()` собирает: `keywords`, `location`, `f_E` (experience), `f_TPR` (posted_within), `f_WT` (remote workplace type), `f_JT` (employment type).
- **Output поля для recruiter:** `jobPosterName`, `jobPosterTitle`, `jobPosterProfileUrl`, `jobPosterPhoto` (top-level, не nested).
- **Output поля для job:** `id`, `link`, `title`, `companyName`, `descriptionText`, `seniorityLevel` (`'Mid-Senior level'`/`'Senior level'`/...), `employmentType`, `workRemoteAllowed`, `postedAt`, `applicantsCount`, `companyLinkedinUrl`.
- При `scrapeCompany=True` добавляются `companyDescription`, `companyEmployeesCount`, `companyWebsite`, `companyAddress`, `companySlogan`.

Один URL = одна локация. Если `--locations Germany Netherlands` — actor получит 2 URL и распределит `count` между ними.

---

## Чего НЕ делать

- ❌ НЕ запускать `run_jobs` без brief.md — visa/locations теряются, скрининг работает вслепую.
- ❌ НЕ запускать `--count > 50` без `--confirm-large-run` — sanity cap. 50 jobs = ~$0.05 Apify + до ~$2 OpenAI.
- ❌ НЕ удалять `candidates/<name>/runs/` — это history аудита и backup для re-screen без Apify.
- ❌ НЕ коммитить ничего из `candidates/` в git (PII резюме / briefs / recruiter имена). Папка в `.gitignore`.
- ❌ НЕ путать `candidates/<name>/boolean.md` (для cv-to-jobs) и `clients/<client>/<vacancy>/boolean.md` (для vacancy-to-candidates) — это разные boolean'ы под разные target'ы.
- ❌ НЕ забывать что Москва / другие не-EU локации в CV кандидата → автодетект `--locations` положит туда же. Override обязателен через `--locations "Germany" ...` если кандидат хочет EU.
- ❌ НЕ вычислять цены руками — `from_apify_jobs.py` печатает estimate перед run, `run_jobs.py` печатает финальную стоимость по `total_tokens`.

---

## Известные ограничения / planned improvements

- **Recruiter contact density** — 30-60% jobs в типичной выдаче. Топовые компании (Datadog, etc.) часто без публичного poster'а.
- **Один кандидат — один Apify call** — пока нет batch'а под несколько кандидатов. Если нужно много кандидатов — отдельные запуски.
- **Re-screen из архива без CLI** — пока пишется руками одноразовый скрипт. Вариант: добавить `run_jobs --from-archive <ts>`.
- **Только `.md` CV** — PDF parsing в backlog'е.
- **Notion-интеграция для кандидатов** — пока только файлы. Notion DB кандидатов — отдельный план в backlog'е.
