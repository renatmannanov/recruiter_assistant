# Step 9: End-to-end тест

> Статус: pending
> Зависит от: step_8 (задеплоено на Mac mini)

## Цель

Проверить что система работает в реальных условиях с двух TG-аккаунтов (основной Renat + тестовый). Убедиться в изоляции данных, корректности результатов, отсутствии регрессий.

## Сценарии

### Сценарий 1: vacancy → candidates (основной юзер)

**Дано:** Renat основной TG-аккаунт, реальная вакансия (например Sonia ASR).

**Шаги:**
1. Открыть production бота с основного TG
2. `/refind_vacancy`
3. Прислать JD как .md файл (~5KB)
4. Дождаться boolean
5. Поправить boolean (добавить/убрать что-то)
6. Прислать отредактированный boolean
7. Дождаться "идёт прогон"
8. Дождаться финального сообщения + `report.md` файлом
9. Открыть `report.md` — проверить:
   - Список кандидатов есть
   - У каждого: имя, LinkedIn, AI Status, AI Score, AI Comment
   - Формат читаемый

**Проверки в SQLite (по ssh на Mac mini):**
```bash
sqlite3 ~/projects/recruiter_assistant/data/recruiter_assistant.db
> SELECT * FROM sessions ORDER BY created_at DESC LIMIT 5;
> SELECT * FROM runs WHERE session_id = <last_id>;
> SELECT COUNT(*) FROM candidates_found WHERE run_id = <run_id>;
> SELECT ai_status, COUNT(*) FROM candidates_found WHERE run_id = <run_id> GROUP BY ai_status;
```

### Сценарий 2: cv → jobs (основной юзер)

То же, но с CV. Реальное CV.

**Дополнительные проверки:**
- Auto-detect locations и experience сработали
- Вакансии релевантные (хотя бы по title)
- `report.md` содержит список вакансий с company/location/score
- В `vacancies_found` появились записи

### Сценарий 3: brief вторым файлом

**Шаги:**
1. `/refind_vacancy`
2. Прислать **2 файла**: `vacancy.md` + `brief.md` (brief с visa/locations)
3. Проверить: оба извлеклись, boolean учитывает brief (location anchors)
4. Прогон → отчёт релевантнее чем без brief

### Сценарий 4: Изоляция между юзерами

**Дано:** Renat основной + Renat тестовый (другой аккаунт).

**Шаги:**
1. С основного TG: `/refind_vacancy` + JD #1, дождаться результата
2. С тестового TG: `/refind_vacancy` + JD #2, дождаться результата
3. Каждый получил **свой** `report.md` — без смешения
4. SQLite: `SELECT user_id, COUNT(*) FROM candidates_found GROUP BY user_id;` — каждая запись правильный user_id

### Сценарий 5: Параллельные сессии

**Шаги:**
1. С основного TG: `/refind_vacancy` + длинная JD
2. **Сразу же** с тестового TG: `/refind_candidate` + CV
3. Подтвердить boolean у обоих
4. Оба пайплайна работают параллельно, каждый получает свой результат
5. Проверки: бот не путает ответы, разные session_id/user_id, нет race conditions

### Сценарий 6: Отмена

1. `/refind_vacancy` → прислать JD → получить boolean → `/cancel`
2. Бот: "сессия отменена"
3. Прислать "ок" → "нет активной сессии, начни через /refind_*"
4. SQLite: `step = 'cancelled'`

### Сценарий 7: Ошибка пайплайна

1. `/refind_vacancy` → прислать **намеренно сломанный** boolean
2. Дождаться ошибки от Apify
3. Бот присылает понятное сообщение (не stack trace)
4. SQLite: `step = 'error'`, `error_text` заполнен

### Сценарий 8: Не-whitelisted юзер

1. TG-аккаунт не в whitelist → `/start`
2. Получить отказ доступа
3. Никаких записей в SQLite

### Сценарий 9: Длинный текст / неподдерживаемый файл

1. `/refind_candidate` + большое CV (~30KB .md) → работает без ошибок
2. `/refind_vacancy` + .pdf → "Поддерживаются только текст / .txt / .md"; сессия в `waiting_input`, не падает

## Регрессии (что НЕ должно было сломаться)

- [ ] Локальные ручные прогоны через CLI работают (smoke test из нового репо)
- [ ] CLI-прогоны через config.yaml (Notion-флоу для ручной работы) не сломаны рефакторингом

## Метрики (зафиксировать)

- Время прогона vacancy → candidates: ___ сек
- Время прогона cv → jobs: ___ сек
- Cost vacancy → candidates: $___
- Cost cv → jobs: $___
- Найдено кандидатов / вакансий: ___ / ___
- Прошли скрининг: ___

## Критерии готовности

- [ ] Все 9 сценариев пройдены успешно
- [ ] Регрессии не выявлены
- [ ] Метрики зафиксированы в `docs/E2E_RESULTS.md`
- [ ] Найденные баги исправлены или записаны в backlog с пометкой "найдено в e2e"
