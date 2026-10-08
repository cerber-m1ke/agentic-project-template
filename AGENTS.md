# agentic-project-template

Шаблон Agentic Project: из него разворачиваются проекты и через него обновляются. Архитектура и принятые
решения — `setup/DESIGN.md`.

## Режим

- Просят создать, инициализировать, развернуть проект или обернуть существующие репозитории → выполняй
  `setup/INIT.md`. Файлы шаблона не правь.
- Исключение: этот клон лежит внутри другого Agentic Project (например, `Resources/<name>/`) — это ресурс,
  только разработка шаблона. Init здесь не запускай (он и сам откажется); новый проект — отдельный клон.
- Иначе — разработка шаблона по правилам ниже. `init.sh`/`init.cmd` здесь не запускай: init удаляет
  `setup/`, `payload/` и `.git`. Проверяй на копии вне репозитория.

## Карта

- `setup/` — инсталлятор, в проект не попадает: `DESIGN.md`, `INIT.md`, `UPDATE.md`, `init.py`, `update.py`,
  `installer_lib.py`, `i18n_check.py`, `VERSION`, `profiles/`, `migrations/`, `tests/`.
- `payload/modules/<module>/` — файлы модуля в раскладке проекта + `module.toml`. Модули: `core`,
  `knowledge`, `resources`, `obsidian`, `devcontainer`.
- `init.sh`, `init.cmd` — вход в инициализацию. `README.md`/`README.en.md` — для человека.
- `CHANGELOG.md` — версии и миграции.

Шаблон сам не Agentic Project: не создавай здесь `Knowledge/`, `Resources/`. Решения по шаблону — в
`setup/DESIGN.md` и `CHANGELOG.md`.

## Правила

- Перед изменением архитектуры прочитай нужный раздел `setup/DESIGN.md`. Расходишься с ним — обсуди
  с человеком и обнови DESIGN.
- Источник правды — русский `*.ru.*` (и `README.md`). После правки обнови пару `*.en.*` (`README.en.md`)
  и запусти i18n-проверку. Не переводятся: этот файл, `setup/DESIGN.md`, `setup/INIT.md`,
  `setup/UPDATE.md`, `CHANGELOG.md`.
- Суффикс языка: `<name>.ru.md` ставится как `<name>.md` при языке `ru`; файл без суффикса — как есть.
  Два модуля с одним путём назначения — ошибка.
- `module.toml`: пути — назначения (после снятия суффикса). Файл вне `seeded`/`block` — `managed`
  (владеет шаблон, локальная правка = конфликт при update). `seeded` — ставится один раз, дальше
  принадлежит проекту. `block` — шаблону принадлежит только блок между маркерами `agentic:begin` и
  `agentic:end`. Файл, который проект будет править, делай `seeded` или `block`.
- Плейсхолдеры init/update: `{{agentic.project_name}}`, `{{agentic.language}}`, `{{agentic.profile}}`,
  `{{agentic.date}}`, `{{agentic.profile_rules}}`. `{{title}}`, `{{date}}` в `Knowledge/_templates/` —
  плейсхолдеры Obsidian, не трогай их.
- Python: `>=3.12`, PEP 723 с `exclude-newer`, только stdlib + `pyyaml`, `tomli-w`, `snowballstemmer`.
  Сообщения `tb`, `init.py`, `update.py` — на английском.
- Изменил формат проекта или Знаний — добавь миграцию в `setup/migrations/`.
- Между релизами `setup/VERSION` = следующая версия с `-dev` (`0.1.1-dev`). Изменение требует шага больше
  (minor/major, DESIGN §5.4) — подними её; суффикс снимает только релизный коммит.
- Маркер блока — целая строка `<!-- agentic:begin -->` / `# agentic:begin`. Новый `block`-файл — маркеры
  в payload и путь в `block` модуля.
- Файлы агентов в payload — повелительно и кратко: `AGENTS.md` проекта ≤ ~1500 токенов.
- Коммиты и теги — только по просьбе человека.

## Windows (DESIGN §14)

- Симлинки не коммить; каталоги связываются symlink/junction, ссылок на файлы нет.
- Входы парами `.sh` + `.cmd`; PowerShell — только с `-ExecutionPolicy Bypass`. Последняя строка
  запуска в `.cmd` — одной строкой `"…" … %* & exit /b`.
- `.gitattributes`: `eol=lf`, для `*.cmd`/`*.bat` — `eol=crlf`.
- Имена: латиница, kebab-case, фиксированный регистр, без зарезервированных имён (`CON`, `NUL`, …).
- Python: `pathlib`; UTF-8 и `\n` при записи; `subprocess` со списком аргументов, без shell; пути в выводе
  относительные через `/`; при удалении деревьев снимай read-only.

## Проверки

uv и Python скачиваются в `Runtime/` шаблона.

```sh
TB_ROOT=. payload/modules/core/Toolbox/tb run setup/i18n_check.py
TB_ROOT=. payload/modules/core/Toolbox/tb run setup/tests/unit_test.py
TB_ROOT=. payload/modules/core/Toolbox/tb run setup/tests/smoke_test.py
```

Windows (cmd):

```bat
set TB_ROOT=.
payload\modules\core\Toolbox\tb.cmd run setup\i18n_check.py
payload\modules\core\Toolbox\tb.cmd run setup\tests\unit_test.py
payload\modules\core\Toolbox\tb.cmd run setup\tests\smoke_test.py
```

## Релиз (по просьбе человека)

1. Раздел версии в `CHANGELOG.md`: «Добавлено», «Изменено», «Исправлено» и обязательно «Миграции»;
   дата вместо «не выпущено».
2. Версия в `setup/VERSION` без `-dev` (semver, DESIGN §5.4).
3. Миграции — `setup/migrations/<x.y.z>_<name>.py` с `migrate(root: Path) -> None`, детерминированные
   и идемпотентные.
4. i18n-проверка, unit- и smoke-тесты зелёные.
5. Коммит и тег `vX.Y.Z` на нём.
6. Следующим коммитом — `setup/VERSION` = следующий patch с `-dev` и раздел «не выпущено» в `CHANGELOG.md`.
