# Changelog

Версии шаблона `agentic-project-template`. Новые — сверху. Релиз — git-тег `vX.Y.Z` (semver, правила
нумерации — `setup/DESIGN.md` §5.4); номер версии совпадает с `setup/VERSION`.

Формат раздела:

```
## [X.Y.Z] — YYYY-MM-DD

### Добавлено
### Изменено
### Исправлено
### Миграции
```

- Пустые подразделы «Добавлено», «Изменено», «Исправлено» опускаются.
- «Миграции» обязательны всегда: скрипты `setup/migrations/<x.y.z>_*.py`, что они меняют в проекте
  (особенно в Знаниях) и что проверить после них. Если миграций нет — «Нет».
- Пишите так, чтобы Агент при обновлении мог объяснить человеку, что меняется и чем это грозит: ломающие
  изменения команд `tb`, протокола в `AGENTS.md` и структуры проекта отмечайте явно.
- Невыпущенная версия помечается «не выпущено» вместо даты.

## [0.2.0] — 2026-10-13

### Добавлено

- Skill `plan-review` — ревью бэклога Plans. Проверяет, что сделано или неактуально (с доказательством),
  находит дубликаты и пересечения с активными задачами и проверяет критерии готовности к работе.
  Человек получает предложенный порядок работ.
- `tb ide setup`, вызывается и из `tb setup`: IDE не индексируют `Resources/` и `Runtime/`. Для JetBrains
  команда добавляет `excludeFolder` в модуль `.idea/*.iml` (а если `.idea/` нет, пишет минимальный проект),
  для VS Code — `search.exclude` и `files.watcherExclude` в `.vscode/settings.json`. Остальные настройки
  пользователя сохраняются, папки остаются видимыми.
- Субагент `kb-auditor` (только чтение) проверяет пачку заметок по Ресурсам и истории git и возвращает
  по каждой вердикт с доказательством. Правила он берёт из `SKILL.md` вызвавшего skill.

### Изменено

- Skill `kb-review` переписан. Появились цель и критерии приёмки, границы (охват, только чтение при
  сверке, подтверждение человека) и вердикты `keep`/`fix`/`shrink`/`merge`/`delete`/`ask`. Каждый вердикт
  требует проверяемого доказательства, для каждого типа заметок заданы критерии. Проверка идёт пачками
  по ресурсу через параллельных субагентов `kb-auditor`, отчёт — в фиксированном формате. Plans перешли
  в `plan-review`.
- `AGENTS.md` (блок шаблона): в протоколе и списке skills появился `plan-review`.
- **Знания хранят только живое.** Отжившая заметка удаляется, история остаётся в git. Упразднены статусы
  `superseded` и поле `superseded_by` у decision, `dropped` у plan. У gotcha и example поля `status` больше
  нет. Заменённое решение удаляется, а причина замены записывается в новое; отвергнутый план удаляется,
  важная причина отказа оформляется решением. `deprecated` у entity означает «выводится, но ещё есть».
- `tb kb lint` для упразднённых статусов, `superseded_by` и `status` у gotcha/example выдаёт
  предупреждения, а не ошибки, поэтому коммиты Знаний они не блокируют. `tb kb stale` показывает
  заметки с упразднёнными статусами как кандидатов на удаление. В выводе `tb kb` у заметок без
  статуса — только тип.
- README Знаний и типов, skills `wrap-up`, `kb-lookup`, `kb-review`, субагент `librarian` и шаблоны
  заметок `gotcha`, `example` переписаны под новые правила. Шаблоны seeded: update предложит изменения,
  а их часть, касающуюся `status`, применит миграция.

### Миграции

- Для исключений в IDE миграции нет: после обновления выполните `Toolbox/tb setup` или `Toolbox/tb ide setup`
  на каждой машине.
- `0.2.0_drop-status-gotcha-example.py` убирает строку `status: active` из frontmatter заметок
  `Knowledge/Gotchas/`, `Knowledge/Examples/` и шаблонов `Knowledge/_templates/gotcha.md`, `example.md`.
  Заметки с упразднёнными статусами (`resolved`, `outdated`, `superseded`, `dropped`) миграция не трогает.
  После обновления выполните `tb kb lint` или skill `kb-review`: такие заметки нужно удалить с согласия
  человека.

## [0.1.1] — 2026-10-13

### Добавлено

- `tb resources clone <name> --from <путь>`: клон из локальной копии, пока upstream недоступен; `origin`
  выставляется на url каталога. `tb resources add <локальная копия> --clone` делает это сам, если
  upstream не отвечает.

### Исправлено

- Init отказывается работать в клоне шаблона внутри другого Agentic Project (например, ресурс
  `Resources/agentic-project-template`): раньше он заменил бы `.git` ресурса.
- Init ставит в проект только файлы payload, которые git отслеживает или готов отследить. Раньше
  игнорируемые git файлы внутри `payload/` (`.idea/`, `.obsidian/`, `Runtime/`) тоже попадали в проект
  и в `agentic.lock`, а проверка чистоты клона их не видела. Без git (распакованный архив) пропускаются
  те же служебные каталоги.
- Копия `tb` в `payload/modules/core/Toolbox/` без `TB_ROOT` отказывается работать (хук молча выходит
  с 0). Раньше она создавала `Runtime/` с uv и Python внутри payload. На `tb` развёрнутого проекта
  это не влияет.
- Документация: ветка обновления в `setup/UPDATE.md` называется по `setup/VERSION` скачанной копии,
  а не по имени каталога; `setup/DESIGN.md` §5.2 — хэши в lock есть у файлов всех классов.

### Миграции

Нет.

## [0.1.0] — 2026-10-09

### Добавлено

- Раскладка шаблона: инсталлятор `setup/` и модули `payload/modules/<module>/`; модули `core`,
  `knowledge`, `resources`, `obsidian` и необязательный `devcontainer`; профили `software` и `generic`.
- Инициализация: `init.sh` / `init.cmd` → `setup/init.py` (флаги `--name`, `--language`, `--profile`,
  `--with`, `--without`, `--agents`, `--yes`, `--dry-run`), новый git-репозиторий с коммитом
  `agentic: init from template vX.Y.Z` из явного списка файлов (остатки папки шаблона не коммитятся,
  локальная git-identity клона сохраняется), настройка машины. Init предупреждает о развёртывании
  из состояния разработки. Инструкция Агенту — `setup/INIT.md`, включая обёртывание существующих
  репозиториев (adopt).
- Версии: релиз `X.Y.Z` (тег `vX.Y.Z`), между релизами `setup/VERSION` = `X.Y.Z-dev`; проект из состояния
  разработки получает релиз обновлением.
- `.agents/agentic.lock`: источник, версия и коммит шаблона, параметры проекта, классы владения
  (`managed`, `seeded`, `block`) и хэши установленных файлов. `block`-файлы — `AGENTS.md`, `.gitignore`,
  `.gitattributes`, `.ignore` (маркер — целая строка); шаблоны заметок и `devcontainer.json` — `seeded`.
- Toolbox: `Toolbox/tb` и `Toolbox/tb.cmd` скачивают закреплённый uv (0.12.23, проверка sha256) и Python
  в `Runtime/`; команды `tb version`, `tb kb`, `tb secrets scan`, `tb hook`, `tb agents`, `tb resources`,
  `tb setup`, `tb obsidian setup`, `tb update fetch`, `tb run`. `tb hook` никогда не блокирует агента
  и ничего не скачивает; унаследованный `TB_ROOT` не перенаправляет `tb` проекта.
- Знания: типы Decisions, Entities, Examples, Gotchas, Plans, Tasks с README и шаблонами заметок; поиск
  BM25 со стеммингом Snowball (RU/EN), проверка `tb kb lint` (frontmatter, ссылки, имена файлов, бюджет
  `AGENTS.md`; `--staged` — по содержимому индекса git), `tb kb new --description`, кандидаты
  на перепроверку `tb kb stale`.
- Skills `kb-lookup`, `kb-commit`, `kb-review`, `wrap-up`, `agentic-update`; субагент `librarian`.
- Адаптеры `claude` (Claude Code) и `codex` (Codex): skills, субагенты, хук `kb-suggest`
  на `prompt-submit`, MCP из `.agents/mcp.toml`, отключение встроенной памяти агентов. Claude получает
  генерируемый `CLAUDE.md` с `@AGENTS.md`; хук Codex находит корень проекта сам (без абсолютных путей).
- Ресурсы: `tb resources add <путь к локальной копии>` записывает её `origin` и предупреждает о работе,
  которой нет в upstream; `tb resources status` и `tb agents doctor` перечисляют настройки агентов
  внутри ресурсов, которые из корня проекта не загружаются.
- Git: `pre-commit` (`tb kb lint --staged` для Знаний и поиск секретов: ключи провайдеров, JWT, `Bearer`,
  пароли в URL и присваиваниях), настройки `core.hooksPath`,
  `core.quotePath=false`, на Windows — `core.longpaths=true`.
- Обновление: `tb update fetch`, `setup/update.py` (`plan`, `diff`, `apply`), инструкция `setup/UPDATE.md`,
  миграции `setup/migrations/`. Изменение состава проекта: `--add-module`, `--remove-module`, `--language`,
  `--profile`.
- Языки `ru` и `en`; проверка переводов `setup/i18n_check.py`; unit-тесты `setup/tests/unit_test.py`
  и smoke-тест `setup/tests/smoke_test.py`.

### Миграции

Нет.
