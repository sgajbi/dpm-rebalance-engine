# Git Workflow With Protected `main`

This repo uses branch protection on `main`.

What this means:
- Do work on a feature branch.
- Open a PR to `main`.
- Merge only after CI passes.
- Do not push directly to `main`.

Shell convention:
- Use Bash for repo commands (Linux/macOS/WSL/Git Bash).
- If currently in PowerShell, run commands as: `bash -lc "<command>"`.

## Daily Flow (Step-by-Step)

### 1. Sync local `main`

```bash
git checkout main
git pull origin main
```

### 2. Create a branch

Use a short, clear branch name.

```bash
git checkout -b feat/<short-change-name>
```

Examples:
- `feat/add-risk-metric-endpoint`
- `fix/nightly-preflight-endpoint`

### 3. Make changes and run local checks

```bash
make check
```

If your change is broader:

```bash
make check-all
```

For full PR-grade local validation (recommended before pushing):

```bash
make ci
```

For host-machine CI-shape validation without Docker build/runtime checks:

```bash
make ci-local
```

For stable CI-like runtime (Linux + Python 3.11 + Postgres) in Docker:

```bash
make ci-local-docker
make ci-local-docker-down
```

Quick command guide:

| Command | When to use | Includes |
|---|---|---|
| `make check` | Fast iteration while coding | `lint` + `typecheck` + dead-code regression gate + unit tests |
| `make check-all` | Broad local gate before opening PR | `lint` + `typecheck` + dead-code regression gate + full suite with coverage gate |
| `make ci` | Full local PR-grade gate | Dependency health + lint + mypy + governance gates + quality-baseline freshness + dead-code regression gate + combined coverage(97%) + Docker build + Postgres and production-profile runtime checks |
| `make ci-local` | CI-shape validation on host machine | Dependency health + lint + mypy + governance gates + quality-baseline freshness + dead-code regression gate + combined coverage(97%) |
| `make ci-local-docker` | Most stable local CI parity | Same as `ci-local` in Linux Python 3.11 container with Postgres service |

## Anti-Conflict Protocol (Required)

Use this protocol to prevent long-lived branch drift and large merge conflicts.

### A. Rebase before every push

Run this sequence before `git push`:

```bash
git fetch origin
git rebase origin/main
make check
git push
```

If your branch is already on remote:

```bash
git push --force-with-lease
```

### B. Keep branches short-lived

- Target PR lifetime: less than 1 day.
- Rebase at least twice per day if PR is still open.
- If branch falls behind `main`, rebase immediately.

### C. Keep PR scope small

- One concern per PR (refactor, behavior change, or CI/docs).
- For large work, use stacked PRs:
  1. move/rename only
  2. behavior changes
  3. tests/docs

### D. Hotspot file handling

For frequently-edited files (for example `src/api/main.py`):

- Rebase before opening PR and before each review response push.
- Avoid combining hotspot edits with unrelated changes.
- Split follow-up fixes into separate PRs instead of extending a stale branch.

### E. Pre-merge freshness check

Before merge, verify:

```bash
git fetch origin
git rev-list --left-right --count HEAD...origin/main
```

- Left count > 0 means your commits ahead of `main`.
- Right count must be 0 before final merge approval.

### 4. Commit

```bash
git add .
git commit -m "type: short summary"
```

Examples:
- `fix: handle empty policy pack catalog`
- `ci: tighten nightly preflight retries`

### 5. Push branch

```bash
git push -u origin feat/<short-change-name>
```

### 6. Open PR

```bash
gh pr create --fill --base main --head feat/<short-change-name>
```

If you want to edit title/body:

```bash
gh pr create --base main --head feat/<short-change-name>
```

### 7. Watch CI checks

```bash
gh pr checks <PR_NUMBER> --watch
```

### 8. Merge after green CI

```bash
gh pr merge <PR_NUMBER> --rebase --delete-branch
```

Auto-merge is opt-in via the `automerge` label and is queued through the repository-approved
rebase merge path using `LOTUS_AUTOMERGE_TOKEN`. If that token is not configured, the helper warns
and skips so an authorized human or release actor can rebase-merge the PR.
Without the `automerge` label, PRs stay manual even after CI is green.
Merged PRs dispatch `main-releasability.yml` on `main` through the separate closed-PR dispatch
workflow so release evidence binds the merged mainline commit.

### 9. Sync local after merge

```bash
git checkout main
git pull origin main
```

## If You Try to Push to `main` Directly

Protected branch rules will reject direct push.
Use branch + PR flow above.

## Dependabot PRs (Current Setup)

Dependabot opens dependency-update PRs.
Dependabot PRs may use the same flow, but only when explicitly labeled `automerge`.

Useful commands:

```bash
gh pr list --author app/dependabot
gh pr checks <PR_NUMBER>
```

Manual merge (if needed):

```bash
gh pr merge <PR_NUMBER> --rebase --delete-branch
```
