# Assignment for the worker

The orchestrator fills in `<task>`, `<source>`, `<batch>`, `<today>` and the file list and passes the text
below the line to the `adopt-worker` subagent. When reworking after an audit it adds the "Auditor remarks" block.

---

You are the knowledge migration worker. Work from the project root. Today is `<today>`.

Read in full and follow: `.agents/skills/adopt/rules.md` and `Knowledge/Tasks/<task>/rules.md`
(project rules take precedence). For reference: `Knowledge/README.md`, READMEs of the target folders, the task's `slugmap.md`.

Source: `<source>`. Batch: `<batch>`. Files of the batch:
<manifest rows>

1. Read every file of the batch. Check key claims (paths, branches, keys, versions, "done") against
   `Resources/` by reading only: search, `git -C Resources/<name> log`/`branch`/`show`. "Not in the code" — only
   `rg --no-ignore` or `git -C <repository> grep`. Do not read the secrets folder. Write commands into the ledger
   verbatim, as you ran them, and only with a checked result.
2. A verdict for each file — per "Verdicts". Before creating a note — `tb kb search "<topic>"`. Do not edit
   other notes (not created by this batch): a matching topic — `duplicate-candidate` with its path.
3. Create notes only with `tb kb new <type> <slug> --title "…" --description "…"`; slug and folder —
   per `slugmap.md`, a deviation — in "Reason". Fill in the template sections by the rules.
4. Links: migrate the body with `[[wikilinks]]` as is, then `tb adopt links <created notes> --write`;
   fix `UNKNOWN` by hand, leave `"pending"`.
5. Secrets: do not copy values anywhere. An item `- #N <path>:<line> — <what it is>` — into the "Secrets" section
   of your batch.
6. Facts for notes of other sources — an item of your batch's "Handoff" section. Handoffs to your files:
   `tb adopt status` → "open handoffs" with `→ <source>`; migrate the fact and mark `accepted: <id> → <note>`.
   Questions for the human — an item of the "Questions" section.
7. Write `Knowledge/Tasks/<task>/ledger/<source>/<batch>.md` in the "Ledger" format: a row for
   each file of the batch, leave the "Audit" column empty.
8. `tb adopt check <source> <batch> --pre-audit` — until green.

Restrictions: checks — without side effects (no docker, builds, tests, package installs,
`git fetch`/`pull`/`checkout`, network); cannot check — `unverified`. Only read old locations. Do not commit.
Change only your own notes and your batch file (nothing in other batches).

Answer — at most 10 lines: counts by verdict, notes created, handoffs and questions, problems,
the final `check` line.

## Auditor remarks (only when reworking)

<ledger rows with `fix:`>. Fix the notes and rows per the remarks, clear "Audit" in the fixed rows;
do not touch rows with `ok`. Then step 8 again.
