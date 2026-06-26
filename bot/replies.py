"""Telegram reply templates.

Plain strings with .format() placeholders. No logic here — the state
machine and handlers pick the right template and fill it in.
"""

WELCOME = (
    "Привет! Я recruiter assistant. Команды:\n"
    "/refind_vacancy — найти кандидатов под вакансию\n"
    "/refind_candidate — найти вакансии под CV\n"
    "/vacancies — список твоих вакансий\n"
    "/vacancy <id> — карточка вакансии (searches, runs, статистика)\n"
    "/runs — последние прогоны\n"
    "/status — что сейчас в работе\n"
    "/cancel — отменить текущую сессию"
)

ASK_FOR_VACANCY_INPUT = (
    "Окей, ищем кандидатов под вакансию. Пришли описание вакансии — "
    "текстом, .txt или .md файлом.\n\n"
    "Опционально: прикрепи вторым файлом brief (visa/locations/salary/remote) "
    "— назови файл со словом 'brief' или пришли его вторым."
)

ASK_FOR_CV_INPUT = (
    "Окей, ищем вакансии под кандидата. Пришли CV — текстом, .txt или .md "
    "файлом.\n\n"
    "Опционально: вторым файлом brief с предпочтениями кандидата."
)

BOOLEAN_GENERATED = (
    "Сгенерил boolean:\n\n"
    "```\n{boolean}\n```\n\n"
    "Если ОК — ответь 'ок'. Если нужно поправить — пришли исправленный вариант."
)

PIPELINE_STARTED = (
    "Запускаю поиск... обычно 1-2 минуты, для CV→jobs до 3 минут."
)

PIPELINE_DONE = (
    "✅ Готово. Сессия #{session_id}\n\n"
    "Всего найдено в Apify: {total_found}\n"
    "Взяли в работу: {found} кандидатов\n"
    "Прошли скрининг: {screened}\n"
    "GO: {go}\n"
    "MAYBE: {maybe}\n"
    "SKIP: {skip}\n"
    "Уже видели на других вакансиях: {already_seen}\n\n"
    "Подробный отчёт в файле ниже."
)

PIPELINE_FAILED = (
    "❌ Ошибка прогона. Сессия #{session_id}\n{error_text}\n\n"
    "Начни новую через /refind_vacancy или /refind_candidate"
)

UNAUTHORIZED = "Доступ закрыт. Этот бот работает только по whitelist'у."

NOT_UNDERSTOOD = "Не понял. Используй /help для списка команд."

UNKNOWN_COMMAND = "Неизвестная команда. /help — список команд."

# No active session, user sent plain text.
NO_SESSION = (
    "Не понял. Начни через /refind_vacancy или /refind_candidate."
)

# Message arrived while a pipeline is running.
PIPELINE_IN_PROGRESS = "Идёт прогон, подождите — пришлю результат, как будет готов."

# Message arrived in a terminal session step.
SESSION_FINISHED = (
    "Сессия завершена. Начни новую через /refind_vacancy или /refind_candidate."
)

SESSION_CANCELLED = "Сессия отменена."

NOTHING_TO_CANCEL = "Нечего отменять — активной сессии нет."

# /status replies.
STATUS_NO_SESSION = "Активной сессии нет. /refind_vacancy или /refind_candidate."
STATUS_ACTIVE = (
    "Сессия #{session_id} ({pipeline_type})\nЭтап: {step}"
)

# /vacancies, /vacancy, /runs — listing commands (read-only).
VACANCIES_EMPTY = "У тебя пока нет вакансий. Начни через /refind_vacancy."
VACANCIES_LIST_HEADER = "Твои вакансии:"
VACANCIES_LIST_ITEM = "#{id} {name} ({source}) — {created_at}"

VACANCY_USAGE = "Использование: /vacancy <id>"
VACANCY_NOT_FOUND = "Вакансия #{id} не найдена."
VACANCY_CARD = (
    "Вакансия #{id}: {name}\n"
    "Источник: {source}\n"
    "Создана: {created_at}\n\n"
    "Searches (boolean'ы): {searches_count}\n"
    "Runs: {runs_count}\n"
    "Скринингов: {screenings_count}\n"
    "  GO: {go}\n"
    "  MAYBE: {maybe}\n"
    "  SKIP: {skip}\n\n"
    "JD:\n{jd_preview}"
)

RUNS_EMPTY = "У тебя пока нет прогонов."
RUNS_LIST_HEADER = "Последние прогоны:"
RUNS_LIST_ITEM = (
    "#{id} session #{session_id} ({pipeline_type}) — "
    "{status}, found {found}, passed {passed} — {created_at}"
)

# extractors.py errors.
FILE_TOO_BIG = "Файл слишком большой (>1 МБ). Пришли файл поменьше."
UNSUPPORTED_FILE = (
    "Не поддерживаю файлы {ext}. Пришли текстом, .txt или .md файлом."
)
EMPTY_INPUT = "Не вижу текста. Пришли описание вакансии или CV."
TOO_MANY_FILES = (
    "Слишком много файлов. Пришли 1 (vacancy/cv) или 2 (vacancy/cv + brief)."
)
