# {{agentic.project_name}}

<!-- Опишите проект в 2–3 строках: что делаем, для кого, какие Ресурсы главные. -->

<!-- agentic:begin -->
## Карта

- `Resources/` — Ресурсы проекта; каталог — `Resources/resources.toml`, правила — `Resources/README.md`.
- `Knowledge/` — Знания: постоянная память проекта (хранилище Obsidian).
- `Toolbox/` — инструменты; вход — `Toolbox/tb` (Windows PowerShell: `Toolbox\tb.cmd`).
- `.agents/` — источник правды для агентов: skills, субагенты, хуки, адаптеры, документация.
- `Runtime/` — временные файлы, кэш, среда; не в git.

## Правила

- Постоянная память — только `Knowledge/`. Встроенную память агента не используй.
- В Знания пиши только то, что не выводится из Ресурсов и истории git. Одна заметка — одна тема: сначала найди и обнови существующую. Правила — `Knowledge/README.md`.
- Временные файлы и одноразовые скрипты — только в `Runtime/`. Постоянные инструменты — в `Toolbox/` с записью в `Toolbox/README.md`.
- Коммить только по просьбе человека, только явные пути (не `git add -A`/`.`). Сообщение: `<scope>: <суть>` + тезисы; scope — `knowledge|agents|toolbox|resources|agentic`.
- Не правь `.agents/agentic.lock` и генерируемые `.claude/`, `.codex/`: меняй `.agents/`, затем `Toolbox/tb agents link`.
- Нужного ресурса нет в `Resources/` — предложи `Toolbox/tb resources clone <name>`.
- Секреты не пиши в `Knowledge/`, `Toolbox/`, `.agents/`.
- Удаление данных, обновление шаблона, коммиты — только после подтверждения человека.
- Процедуры — `.agents/skills/<name>/SKILL.md`. Если твой агент не загружает skills сам, найди подходящий skill и прочитай его `SKILL.md`.
- Подробности — `.agents/docs/concept.md` (по необходимости).

{{agentic.profile_rules}}

## Протокол сессии

1. Старт: Знания целиком не читай; активные задачи — `Toolbox/tb kb search --type task --status active --brief`.
2. Перед планированием и решениями, при первом касании сущности, при знакомой ошибке — skill `kb-lookup`.
3. Конец сессии или этапа — skill `wrap-up`.
4. Периодически — skill `kb-review`.

Skills шаблона: `kb-lookup` — поиск в Знаниях; `wrap-up` — итоги сессии; `kb-commit` — коммит Знаний; `kb-review` — ревью Знаний; `agentic-update` — обновление из шаблона.

## Команды `Toolbox/tb`

- `kb search <запрос>`, `kb show <путь|slug>`, `kb related <путь|slug>` — поиск и чтение Знаний.
- `kb new <type> <slug> --title "…"` — новая заметка; `kb lint` — проверка; `kb stale` — что перепроверить.
- `resources status`, `resources clone <name>` — Ресурсы.
- `agents link`, `agents doctor` — адаптеры агентов.
- `secrets scan` — поиск секретов; `run <script>` — скрипт проекта; `setup` — настройка машины.
<!-- agentic:end -->

## Особенности проекта

<!-- Правила и соглашения этого проекта. Блок выше обновляет шаблон — не правьте его; этот раздел ваш. -->
