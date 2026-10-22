# Resources and decisions on them

The draft table — `Runtime/adopt/inventory/<date>/resources.md` (`tb adopt inventory`); details per
repository — `details/` in the same place. The human decides on every row in one batch.

Decisions: `clone` (+ branch), `mv` (state bound to the path: snapshot, "yes", rollback), `folder`, `secret`,
`toolbox`, `knowledge` (goes to the migration), `push-first` (the human pushes, then `clone`), `archive`
(git bundle or tar), `discard` (with a reason).

| Repository | Remote | Branch | Local work | Decision | Note |
|---|---|---|---|---|---|
