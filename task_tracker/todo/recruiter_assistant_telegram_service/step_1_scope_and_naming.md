# Step 1: Scope и naming нового репо

> Статус: Фаза A — done. Фаза B (обновление 05_refind) — pending.

## Решения (зафиксированы)

### 1.1 Имя нового репо и путь

- **Локально (разработка):** `c:\Users\renat\projects\recruiter_assistant\`
- **Боевой хостинг:** **Mac mini**, путь `~/projects/recruiter_assistant/`
- **GitHub-репо:** `recruiter_assistant` (private)
- **TG bot username:** определяется при создании production-бота на step_8 (см. примечание там)

### 1.2 Что переезжает — ТОЛЬКО КОД

Из `05_refind/services/recruiter_assistant/` → в `recruiter_assistant/core/`:
- `boolean_generator/` (весь)
- `candidate_screener/` (весь)
- `PIPELINE_vacancy_to_candidates.md`
- `PIPELINE_cv_to_jobs.md`

### 1.3 05_refind НЕ трогаем — только копируем

**Стратегия — копия, без удаления.** Код `boolean_generator` + `candidate_screener` **копируется** в новый репо. В `05_refind/services/recruiter_assistant/` **всё остаётся как есть** — ничего не удаляем, ничего не переименовываем. Ручные прогоны Рената из 05_refind продолжают работать как раньше.

После этого две копии живут своей жизнью:
- Вся дальнейшая работа (бот, рефакторинг под бота на step_5/6) — **только в новом репо**
- В 05_refind в `services/recruiter_assistant/` больше не возвращаемся
- Копии не синхронизируем — пайплайны стабильны, активной разработки в них нет, расхождение не критично

**НЕ копируем в новый репо** (данные конкретного агентства, боту не нужны — он принимает файлы из Telegram):
- `clients/` (sonia, termanova и др.)
- `candidates/` (история runs)
- `test_results/`

Recruiter_assistant как сервис = переиспользуемый инструмент (код пайплайнов), не привязанный к данным клиентов.

### 1.4 Обновление `05_refind/CLAUDE.md`

Код в `05_refind/services/recruiter_assistant/` остаётся (мы только скопировали), но активная разработка теперь в новом репо. CLAUDE.md это отражает.

**Добавить** новую секцию:
```markdown
## Связанные проекты

- **recruiter_assistant** — отдельный проект: AI-скрининг кандидатов и поиск вакансий
  через Telegram-бота. Код скопирован в отдельный репозиторий
  `c:\Users\renat\projects\recruiter_assistant\` — там идёт вся дальнейшая разработка.
  Копия в `05_refind/services/recruiter_assistant/` оставлена для локальных ручных
  прогонов (clients/, candidates/). Новый функционал — только в новом репо.
```

Блок про **Recruiter Assistant** в "Известные подводные камни" (PIPELINE_*.md) — оставить, ручные прогоны из 05_refind продолжают работать.

### 1.5 Auto-memory — копируем (как и код)

В новом репо: `c:\Users\renat\.claude\projects\c--Users-renat-projects-recruiter_assistant\memory\`

**Копируем** из `c:\Users\renat\.claude\projects\c--Users-renat-projects-05-refind\memory\`:
- `project_recruiter_assistant.md`
- `feedback_output_format.md`
- `project_vacancy_internal_notes.md`
- `screener_structure.md`
- `discover_pipeline.md`
- `boolean_generator_v2.md`

**Создать** в новом `MEMORY.md` индекс на эти файлы.

**В 05_refind эти memory-файлы НЕ удаляем** — там осталась рабочая копия кода для ручных прогонов, memory про неё релевантна. Копия memory расходится с новым репо со временем — это ок, как и копия кода.

> Дальше memory нового репо ведём независимо: правки по боту/новому функционалу — только в `c--Users-renat-projects-recruiter_assistant\memory\`.

### 1.6 Git history — с чистого листа

- Новый репо: `git init`, без переноса истории из 05_refind
- В первом коммите: код (boolean_generator, candidate_screener) + структура (bot/, db/, config/) + README, .gitignore, requirements.txt
- Commit message: `feat: initial migration from 05_refind/services/recruiter_assistant`

### 1.7 Папка task_tracker в новом репо

Создать `recruiter_assistant/task_tracker/` со структурой `todo/ done/ archive/ backlog/`.

Перенести **этот текущий план** в новый репо: `recruiter_assistant/task_tracker/todo/recruiter_assistant_telegram_service/`.

В 05_refind план оставить копией (короткоживущий артефакт, после завершения уберём из 05_refind).

## Действия

(выполняются на step_2, здесь только список)

**05_refind не трогаем вообще** — только читаем для копирования. Все действия — создание нового репо. Удаления нигде нет, риск потери кода отсутствует.

### Фаза A — создание нового репо

- [x] Создать новый локальный репо `c:\Users\renat\projects\recruiter_assistant\`
- [x] **Скопировать** (не переместить!) код `boolean_generator/` и `candidate_screener/` + `PIPELINE_*.md` из `05_refind/services/recruiter_assistant/` → `recruiter_assistant/core/`
- [x] **НЕ копировать** `clients/`, `candidates/`, `test_results/` — данные клиентов, боту не нужны
- [x] Создать `bot/`, `db/`, `config/` пустыми; `data/` (gitignored)
- [x] Создать `.gitignore`, `.env.example`, `README.md`, `requirements.txt`
- [x] Создать `MEMORY.md` (индекс на скопированные memory-файлы) — в `c--Users-renat-projects-recruiter_assistant\memory\MEMORY.md`
- [x] **Скопировать** auto-memory файлы в `c--Users-renat-projects-recruiter_assistant\memory\`
- [x] **Скопировать** текущий план в новый репо
- [x] `git init` + `git add .` + `git commit` (`9628acf`)
- [x] Репо на GitHub: `https://github.com/renatmannanov/recruiter_assistant` (создан вручную Ренатом, не через `gh repo create` — `gh` не залогинен), `origin` добавлен, ветка `main` запушена
- [x] **БАРЬЕР:** проверено через `git ls-tree origin/main` — 60 файлов, ключевые на месте, секретов (`.env`, `whitelist.json`) нет
- [x] Smoke test нового репо: boolean генерится из нового места (boolean_generator → OpenAI, реальный прогон по sonia/asr vacancy)

### Фаза B — лёгкое обновление 05_refind (необязательный порядок, безопасно)

05_refind/services/recruiter_assistant/ **не трогаем** — код там остаётся. Меняем только метаданные:

- [ ] Обновить `05_refind/CLAUDE.md` — добавить секцию "Связанные проекты" (см. 1.4)
- [ ] Разделить auto-memory согласно 1.5
- [ ] Smoke test 05_refind: `enrich_contacts.py` / `discover_people.py` работают как раньше (они и не должны были измениться)

## Критерии готовности

**Фаза A:**
- [ ] Новый репо физически существует, скопирован **только код** (без clients/candidates)
- [ ] План скопирован в новый репо
- [ ] GitHub-репо создан, первый коммит запушен, **проверено на github.com визуально**
- [ ] Smoke test нового репо проходит (boolean генерится)

**Фаза B:**
- [ ] `05_refind/services/recruiter_assistant/` содержит только `clients/`, `candidates/`, `test_results/`, README
- [ ] `05_refind/CLAUDE.md` актуализирован
- [ ] Auto-memory корректно разделена между двумя репо
- [ ] Smoke test 05_refind: основные скрипты работают как раньше
