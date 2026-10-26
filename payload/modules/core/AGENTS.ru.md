# {{agentic.project_name}}

<!-- Опишите проект в 2–3 строках: что делаем, для кого, какие Ресурсы главные. -->

<!-- agentic:begin -->
## Карта

- `Resources/` — Ресурсы проекта; каталог — `Resources/resources.toml`, правила — `Resources/README.md`.
- `Knowledge/` — Знания, постоянная память проекта (хранилище Obsidian).
- `Toolbox/` — инструменты; вход — `Toolbox/tb` (Windows PowerShell: `Toolbox\tb.cmd`).
- `.agents/` — источник правды для агентов: skills, субагенты, хуки, адаптеры; устройство проекта — `.agents/docs/concept.md`.
- `Runtime/` — временное, кэш, среда; не в git.

## Правила

- Постоянная память — только `Knowledge/`. Встроенную память агента не используй.
- В Знания пиши только то, что не выводится из Ресурсов и истории git. Одна заметка — одна тема: сначала найди и обнови существующую. Правила — `Knowledge/README.md`.
- Временные файлы и одноразовые скрипты — только в `Runtime/`, постоянные инструменты — в `Toolbox/` с записью в `Toolbox/README.md`.
- Знания коммить сразу после правки (skill `kb-commit`) и сообщи человеку. Остальное — только по просьбе, явными путями (не `git add -A`/`.`): `<scope>: <суть>` + тезисы, scope — `knowledge|agents|toolbox|resources|agentic`. Хук pre-commit не обходи и не отключай (`--no-verify`, `commit-tree`): он ловит секреты.
- Не правь `.agents/agentic.lock` и генерируемые `.claude/`, `.codex/`, `CLAUDE.md`: меняй `.agents/`, затем `Toolbox/tb agents link`.
- Нужного ресурса нет в `Resources/` — предложи `Toolbox/tb resources clone <name>`.
- Секреты не пиши в `Knowledge/`, `Toolbox/`, `.agents/`.
- Удаление данных и обновление шаблона — только после подтверждения человека.
- Процедуры — `.agents/skills/<name>/SKILL.md`. Если агент не загружает skills сам — прочитай `SKILL.md` подходящего.

{{agentic.profile_rules}}

## Протокол сессии

1. Старт: Знания целиком не читай; задачи — `Toolbox/tb kb search --type task --status active --brief`.
2. Перед планированием и решениями, при первом касании сущности, при знакомой ошибке — skill `kb-lookup`.
3. Конец сессии или этапа — skill `wrap-up`.
4. Периодически — skills `kb-review` (Знания) и `plan-review` (планы).

## Команды `Toolbox/tb`

- `kb search <запрос>`, `kb show|related <путь|slug>` — поиск и чтение Знаний.
- `kb new <type> <slug> --title "…"` — новая заметка; `kb lint` — проверка; `kb stale` — что перепроверить.
- `resources status|clone <name>` — Ресурсы; `agents link|doctor` — адаптеры агентов.
- `secrets scan` — поиск секретов; `run <script>` — скрипт проекта; `setup` — настройка машины.
<!-- agentic:end -->

## Особенности проекта

<!-- Правила и соглашения этого проекта. Блок выше обновляет шаблон — не правьте его; этот раздел ваш. -->
