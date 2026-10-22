---
type: task
title: "{{title}}"
description: "Перенос проекта по skill adopt: инвентаризация, ресурсы, перенос знаний с реестрами, финальный аудит, очистка старого"
status: active
created: {{date}}
verified: {{date}}
tags: [adopt]
aliases: []
resources: []
---

# {{title}}

## Цель

Всё ценное из старых мест — в Ресурсах и Знаниях, ничего не потеряно молча; старое удалено по манифесту
после GO финального аудита. Процедура — skill `adopt`.

## Спецификация

- Этапы, сессии и статус — [plan.md](plan.md); правила проекта — [rules.md](rules.md) (поверх
  `.agents/skills/adopt/rules.md`); настройки `tb adopt` — `adopt.toml`.
- Инвентаризация и решения по ресурсам — [resources.md](resources.md); вопросы вне пачек —
  [questions.md](questions.md); реестры — `ledger/<источник>/`.
- Финальный аудит — [final-audit.md](final-audit.md), манифест удаления —
  [deletion-manifest.md](deletion-manifest.md).
- Где перенос сейчас: `Toolbox/tb adopt status --task {{slug}}`.

## Решения по ходу

<!-- Дата — решение — почему. -->

## Прогресс

<!-- Сессия, дата, итог в 1–3 строки. Подробности — в реестрах и plan.md. -->

## Что в работе

<!-- Этап 6: активные задачи с ресурсами, ветками, push/MR и следующим шагом. -->

## Замечания к шаблону

<!-- Что мешало в шаблоне и skill adopt: этап — проблема — предложение. -->

## Итоги для Знаний

<!-- Что перенести в Decisions, Gotchas, Entities при закрытии задачи. -->
