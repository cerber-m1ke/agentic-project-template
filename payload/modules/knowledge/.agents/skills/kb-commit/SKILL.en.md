---
name: kb-commit
description: Commit changes to Knowledge (Knowledge/) with checks and a bullet-point message. Use only when the human explicitly asks to commit Knowledge or agrees to a commit proposed after wrap-up, kb-review or plan-review.
---

# Knowledge commit

Only when the human asks. The commit contains only `Knowledge/`; other changes are committed
separately, with their own scope and also only on request.

1. **Changes.** `git status --porcelain -- Knowledge/` and `git diff -- Knowledge/`. Nothing there — say
   so and stop.
2. **Staging area.** `git diff --cached --name-only`. If it already contains files outside `Knowledge/`,
   leave them alone and ask the human what to do.
3. **Knowledge check.** `Toolbox/tb kb lint` (Windows PowerShell: `Toolbox\tb.cmd kb lint`).
   Fix the errors; ask the human about anything debatable.
4. **Secrets.** `Toolbox/tb secrets scan <added and modified files>`. If anything is found, remove the secret from the note.
   Do not commit until the check passes.
5. **Message.**
   ```
   knowledge: <the gist in one line>

   - <a point about the content: what was learned, decided, changed>
   - …
   ```
   Points are about meaning, not files: "Gotcha: uv behind a proxy requires SSL_CERT_FILE", "Task
   auth-token-refresh is done, takeaways moved to Entities/api".
6. **Confirmation.** Show the human the file list and the message, and wait for their approval.
7. **Stage explicit paths:** `git add -- Knowledge/Gotchas/uv-proxy-ssl.md Knowledge/Tasks/auth-token-refresh.md`.
   Deleted files are staged the same way. Never `git add -A`, `git add .`, `git commit -a`.
   Make sure `git diff --cached --name-only` shows only these paths, and check what the hook will see:
   `Toolbox/tb kb lint --staged`. A `not staged yet` warning is a link to a note outside the commit, broken
   in history: include that note in the commit (with the human's consent) or make the link
   `[text](path.md "pending")`.
8. **Commit.** Write the message to `Runtime/commit-msg.txt` and run `git commit -F Runtime/commit-msg.txt`,
   then delete the file. The pre-commit hook repeats `kb lint --staged` and the secret scan: if it fails, fix
   the cause. Never bypass the hook — no `--no-verify`, no `git commit-tree`, no disabling it: it catches
   secrets.
9. **Report:** the commit hash (`git log -1 --oneline`) and the file list.
