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

## [0.1.0] — не выпущено

### Добавлено

- Раскладка шаблона: инсталлятор `setup/` и модули `payload/modules/<module>/`; модули `core`,
  `knowledge`, `resources`, `obsidian` и необязательный `devcontainer`; профили `software` и `generic`.
- Инициализация: `init.sh` / `init.cmd` → `setup/init.py` (флаги `--name`, `--language`, `--profile`,
  `--with`, `--without`, `--agents`, `--yes`, `--dry-run`), новый git-репозиторий с коммитом
  `agentic: init from template vX.Y.Z`, настройка машины. Инструкция Агенту — `setup/INIT.md`,
  включая обёртывание существующих репозиториев (adopt).
- `.agents/agentic.lock`: источник, версия и коммит шаблона, параметры проекта, классы владения
  (`managed`, `seeded`, `block`) и хэши установленных файлов.
- Toolbox: `Toolbox/tb` и `Toolbox/tb.cmd` скачивают закреплённый uv (0.12.23, проверка sha256) и Python
  в `Runtime/`; команды `tb version`, `tb kb`, `tb secrets scan`, `tb hook`, `tb agents`, `tb resources`,
  `tb setup`, `tb obsidian setup`, `tb update fetch`, `tb run`.
- Знания: типы Decisions, Entities, Examples, Gotchas, Plans, Tasks с README и шаблонами заметок; поиск
  BM25 со стеммингом Snowball (RU/EN), проверка `tb kb lint` (frontmatter, ссылки, имена файлов, бюджет
  `AGENTS.md`), кандидаты на перепроверку `tb kb stale`.
- Skills `kb-lookup`, `kb-commit`, `kb-review`, `wrap-up`, `agentic-update`; субагент `librarian`.
- Адаптеры `claude` (Claude Code) и `codex` (Codex): skills, субагенты, хук `kb-suggest`
  на `prompt-submit`, MCP из `.agents/mcp.toml`, отключение встроенной памяти агентов.
- Git: `pre-commit` (`tb kb lint` для Знаний и поиск секретов), настройки `core.hooksPath`,
  `core.quotePath=false`, на Windows — `core.longpaths=true`.
- Обновление: `tb update fetch`, `setup/update.py` (`plan`, `diff`, `apply`), инструкция `setup/UPDATE.md`,
  миграции `setup/migrations/`.
- Языки `ru` и `en`; проверка переводов `setup/i18n_check.py`; smoke-тест `setup/tests/smoke_test.py`.

### Миграции

Нет.
