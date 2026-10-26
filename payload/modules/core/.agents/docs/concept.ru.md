# Концепция Agentic Project

Справка для Агента: читай, когда нужно понять устройство проекта глубже, чем описано в `AGENTS.md`.

## Суть

Agentic Project — рабочая среда, в которой Агент работает над всеми Ресурсами проекта. Проект — не один
репозиторий, а связанное целое: корневой git-репозиторий с инструкциями, инструментами и Знаниями плюс
Ресурсы — отдельные репозитории или папки. Проект развёрнут из шаблона `agentic-project-template`
и обновляется из него.

Принципы:

- `.agents/` — единственный источник правды для системного. `.claude/`, `.codex/`, `.mcp.json`,
  `CLAUDE.md` (импортирует `AGENTS.md`) генерируются `tb agents link` и в git не попадают.
- Достаточно уровня 0: читать `AGENTS.md` и выполнять команды. Нативные skills, субагенты и хуки —
  улучшение, а не требование.
- Память проекта — только `Knowledge/`, не встроенная память агента (`~/.claude`, `~/.codex`).
  В Знаниях — только то, что не выводится из Ресурсов и истории git.
- Механику делает `tb`, смысл — Агент: интервью, анализ и тексты — в skills.
- Дешёвый старт: при старте — только `AGENTS.md` и описания skills, Знания — по требованию.
- Необратимое (удаление данных, обновление, коммиты вне `Knowledge/`) — только с подтверждения человека.

## Структура

| Путь | Что это |
|---|---|
| `AGENTS.md` | Точка входа: карта, правила, протокол сессии |
| `.agents/agentic.lock` | Происхождение из шаблона, параметры проекта, классы и хэши файлов. Руками не править |
| `.agents/local.toml` | Агенты этой машины; не в git |
| `.agents/skills/<name>/SKILL.md` | Процедуры |
| `.agents/agents/<name>.md` | Субагенты в каноническом формате |
| `.agents/hooks/hooks.toml` | Хуки на абстрактных событиях; команда — `Toolbox/tb hook <name>` |
| `.agents/git-hooks/` | `pre-commit`: `tb kb lint` для Знаний, поиск секретов |
| `.agents/adapters/<agent>/` | Манифесты адаптеров агентов |
| `.agents/mcp.toml` | MCP-серверы |
| `.agents/permissions.toml` | Правила разрешений (deny/ask/allow) для всех агентов |
| `Knowledge/` | Знания, хранилище Obsidian; правила — `Knowledge/README.md` и README папок |
| `Resources/` | Ресурсы; правила — `Resources/README.md`, каталог — `Resources/resources.toml` |
| `Toolbox/` | `tb` / `tb.cmd`, инструменты шаблона в `agentic/`, инструменты проекта; индекс — `Toolbox/README.md` |
| `Runtime/` | Временное и среда (`tools/`, `cache/`, `update/` зарезервированы); не в git |

## Владение файлами

Класс каждого файла из шаблона записан в `.agents/agentic.lock`.

| Класс | Владелец | Как править |
|---|---|---|
| `managed` | шаблон | Не правь. Локальная правка при обновлении станет конфликтом. Проектное — в файлы проекта |
| `seeded` | проект | Правь свободно: шаблон создал файл один раз и больше не трогает |
| `block` | смешанный | `AGENTS.md`, `.gitignore`, `.gitattributes`, `.ignore`: правь только вне маркеров `agentic:begin` / `agentic:end`, строки маркеров не удаляй; блок между ними обновляет шаблон |
| нет в lock | проект | Правь свободно |

Генерируемые `.claude/`, `.codex/`, `.mcp.json`, `CLAUDE.md` не правь: меняй источник в `.agents/`, затем
`Toolbox/tb agents link`. Заметки только для Claude — `.claude/CLAUDE.md` или `CLAUDE.local.md`.

## Знания

| Тип | Что хранит |
|---|---|
| Decisions | Архитектурные решения (ADR), пока действуют |
| Entities | Карточки сущностей: назначение, где лежит, связи, инварианты, владельцы |
| Examples | Переиспользуемые примеры и шаблоны |
| Gotchas | Грабли: симптом, причина, обход, проверка актуальности |
| Plans | Идеи и отложенное |
| Tasks | Текущие задачи; после `done` итоги разносятся по другим типам, задача удаляется |
| Reminders | Что рассмотреть в ближайшее время: ссылки на заметки, планы, задачи; рассмотрели — удалить |

Хранится только живое: устаревшее исправляют, отжившее удаляют — прежние версии есть в истории git.

Работа: `tb kb search` → `tb kb show` → сверка с Ресурсами. Конец сессии: `tb kb nearby` — близкие
напоминания, планы и задачи. Skills: `kb-lookup`, `wrap-up`, `kb-commit`, `kb-review`, `plan-review`;
субагенты `librarian`, `kb-auditor`.

## Агенты

Уровни: 0 — `AGENTS.md` и команды; 1 — нативные skills; 2 — субагенты; 3 — хуки. Без нативных skills:
найди skill в `.agents/skills/` и прочитай его `SKILL.md`. Адаптеры: `tb agents list`, `tb agents link`,
`tb agents doctor`.

## Git

- Корневой репозиторий: `AGENTS.md`, `README.md`, `.agents/`, `Knowledge/`, `Toolbox/`,
  `Resources/README.md`, `Resources/resources.toml`. Не в git: `Resources/*`, `Runtime/`, выходы
  адаптеров, `.agents/local.toml`, `Knowledge/.obsidian/`, `.env*`.
- Ресурсы коммитятся внутри себя: `git -C Resources/<name> …`.
- Настройки агентов внутри ресурсов (`.claude/settings.json`, `.mcp.json`, `.codex/`, skills) агент,
  запущенный из корня, не загружает — нужное проекту переносится в `.agents/` (`tb resources status`
  их перечисляет).
- Знания коммитятся сразу после правки: `tb kb commit <пути> -m "…"` — только эти пути
  (`git commit --only`), с трейлером `Agent-Session: <агент>:<id> (<заголовок>)`. Правку своего недавнего коммита —
  `--amend`: amend, если он HEAD, иначе `fixup!`, который склеивает `tb kb squash`. Запушенное не
  переписывается. Хуки `kb-track` и `kb-uncommitted` напоминают о забытом.
- Остальные коммиты — по просьбе, явными путями, формат `<scope>: <суть>`; scopes: `knowledge`,
  `agents`, `toolbox`, `resources`, `agentic`. Хук pre-commit (`tb kb lint`, поиск секретов) не обходят:
  ни `--no-verify`, ни `git commit-tree`. Упал — исправь причину.

## Жизненный цикл

- **Новая машина:** `git clone <репозиторий-проекта>`, затем `Toolbox/tb setup --agents <a,b>` (Windows:
  `Toolbox\tb.cmd setup --agents <a,b>`): uv и Python в `Runtime/`, адаптеры перечисленных агентов
  (список запоминается в `.agents/local.toml`), настройки git и Obsidian, список недостающих ресурсов
  (`--clone-missing` — склонировать их). Та же команда восстанавливает
  среду после удаления `Runtime/`; новый агент — `Toolbox/tb setup --agents <a,b>`.
- **Обновление:** skill `agentic-update` → `Toolbox/tb update fetch` загружает последний релиз шаблона
  в `Runtime/update/<v>/` → выполняется `Runtime/update/<v>/setup/UPDATE.md` из этой копии. Изменения —
  в ветке `agentic/update-<v>`, коммит и слияние — после подтверждения человека. Источник — URL из
  `agentic.lock`; менять его может только человек.
- **Версия шаблона:** `Toolbox/tb version`.

## Где что искать

| Вопрос | Где |
|---|---|
| Правила Знаний, формат заметок | `Knowledge/README.md`, `Knowledge/<Folder>/README.md`, `Knowledge/_templates/` |
| Ресурсы, что склонировано | `Resources/README.md`, `Toolbox/tb resources status` |
| Инструменты | `Toolbox/README.md`, `Toolbox/tb --help`, `Toolbox/tb <command> --help` |
| Процедуры | `.agents/skills/` |
| Параметры проекта и версия | `Toolbox/tb version`, `.agents/agentic.lock` |
| Проблемы с агентом | `Toolbox/tb agents doctor` |
