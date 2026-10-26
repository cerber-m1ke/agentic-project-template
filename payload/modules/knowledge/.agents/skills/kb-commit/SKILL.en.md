---
name: kb-commit
description: Commit Knowledge (Knowledge/) edits right after making them — with bullet points and the authoring session; a correction goes into your own recent commit instead of a new one. Use after every finished edit of notes (created, changed, deleted), after what was applied in wrap-up, kb-review, plan-review, and when a hook asks to commit Knowledge.
---

# Knowledge commit

Knowledge is committed right after each edit, without the human asking: with parallel sessions there is
no other way to tell which session wrote what. `Toolbox/tb kb commit` commits only the given paths
(`git commit --only`): whatever else is in the index stays out of the commit. The trailer
`Agent-Session: <agent>:<id> (<title>)` is added automatically. The command does not commit outside
`Knowledge/`: everything else is committed only when the human asks, separately, with its own scope.

## When

- You finished a logical edit: a note is created, updated or deleted, the takeaways are distributed. One
  commit — one idea; do not commit a draft in the middle of an edit.
- The human cancelled or corrected something recently recorded (a plan, pitfall, decision, reminder) —
  this is a correction of your own commit: `--amend`, not a new commit.
- A hook reported uncommitted Knowledge edits of the session — commit them or tell the human why not.
- The human asks not to commit — do not, and say that the edits remain in the working tree.

## Steps

0. **Session title** — once per session, before the first commit: `Toolbox/tb kb session title "<what the
   session does>"` — the task title or the gist of the work, briefly. The human will find the session in
   the history by it (`git log --grep`). The topic changed — set a new one. Without a title the trailer
   has only the id.
1. **Paths.** Only the files this session edited (`git status --short -- Knowledge/` shows other
   sessions' files too — leave those). Deleted files are given the same way.
2. **Check.** `Toolbox/tb kb lint` (Windows PowerShell: `Toolbox\tb.cmd kb lint`): fix errors in your
   notes; ask the human about anything debatable. A link to another session's uncommitted note — make
   it a pending one (`[text](path.md "pending")`).
3. **Commit:**
   ```
   Toolbox/tb kb commit Knowledge/Gotchas/uv-proxy-ssl.md Knowledge/Tasks/auth-token-refresh.md \
     -m "uv behind a proxy" -m "- Gotcha: uv behind a proxy needs SSL_CERT_FILE" \
     -m "- Task auth-token-refresh: progress"
   ```
   The first `-m` is the gist (the `knowledge:` prefix is added), the next ones are points about meaning,
   not about files.
4. **Correction** of your own recent commit: `Toolbox/tb kb commit <paths> --amend [-m …]`.
   - The last commit is this session's and not pushed → an amend (without `-m` the message is kept).
   - Other sessions' commits came after it → a `fixup! <subject>` commit. `Toolbox/tb kb squash` folds it
     in, only with a clean working tree, once parallel sessions have committed everything. Offer it to
     the human; do not run it in the middle of other sessions' work.
   - Pushed commits are never rewritten: you get an ordinary commit.
5. **The pre-commit hook** checks notes and secrets. If it fails, fix the cause. Never bypass it: no
   `--no-verify`, no `git commit-tree`, no disabling the hook. `tb kb commit` refuses when hooks are not
   enabled (`Toolbox/tb setup`).
6. **Tell the human** in one line: hash, gist, files — `Knowledge: a1b2c3d "uv behind a proxy" (2 files)`.
   A correction — the same, marked amend or fixup.
